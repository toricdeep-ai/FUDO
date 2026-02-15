"""FUDO - 株価API モジュール（yfinance + 株探スクレイピング）

Excel/楽天RSSの代替として、無料APIで株価データを取得する。

データソース:
  - yfinance: 現在値・前日比・出来高・銘柄名（15-20分遅延）
  - kabutan: 時価総額・貸借区分（24時間キャッシュ）

制限事項:
  - 板データ（売買気配）は取得不可
  - yfinance のレート制限: ~360 req/hour 程度
"""

import time
import threading
from datetime import datetime

import yfinance as yf

from analytics import load_config
from data_fetch import fetch_kabutan_basic, HEADERS

import requests
from bs4 import BeautifulSoup


class _Cache:
    """TTL付きインメモリキャッシュ"""

    def __init__(self, ttl: int = 30):
        self._store: dict[str, tuple[float, object]] = {}
        self._ttl = ttl
        self._lock = threading.Lock()

    def get(self, key: str):
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            ts, value = entry
            if time.time() - ts > self._ttl:
                del self._store[key]
                return None
            return value

    def set(self, key: str, value):
        with self._lock:
            self._store[key] = (time.time(), value)

    def clear(self):
        with self._lock:
            self._store.clear()


# 株価キャッシュ（TTL: config の cache_ttl、デフォルト30秒）
_price_cache = _Cache(ttl=30)

# kabutan 補足データキャッシュ（24時間）
_kabutan_cache = _Cache(ttl=86400)


def _get_api_config() -> dict:
    config = load_config()
    return config.get("api", {})


def _init_caches():
    """config の cache_ttl でキャッシュTTLを再設定"""
    global _price_cache
    cfg = _get_api_config()
    ttl = cfg.get("cache_ttl", 30)
    _price_cache = _Cache(ttl=ttl)


def get_prices(tickers: list[str]) -> list[dict]:
    """yfinance で株価を一括取得し、kabutan で補足データを付与する。

    Args:
        tickers: 証券コードのリスト（例: ["6920", "3856"]）

    Returns:
        [{"ticker", "name", "price", "change", "volume",
          "market_cap", "taishaku", "timestamp"}, ...]
    """
    if not tickers:
        return []

    # キャッシュ済みとキャッシュ切れを分離
    results = {}
    fetch_needed = []
    for t in tickers:
        cached = _price_cache.get(t)
        if cached is not None:
            results[t] = cached
        else:
            fetch_needed.append(t)

    # yfinance でバルク取得
    if fetch_needed:
        yf_data = _fetch_yfinance(fetch_needed)
        for t, data in yf_data.items():
            # kabutan 補足データ（時価総額・貸借区分）
            supplement = _get_kabutan_supplement(t)
            if supplement:
                data["market_cap"] = supplement.get("market_cap", 0)
                data["taishaku"] = supplement.get("taishaku", "")

            results[t] = data
            _price_cache.set(t, data)

    # 入力順序を保持して返す
    return [results[t] for t in tickers if t in results]


def _fetch_yfinance(tickers: list[str]) -> dict[str, dict]:
    """yfinance でバルク取得する。

    .T サフィックスで東証対応。
    """
    result = {}
    yf_symbols = [f"{t}.T" for t in tickers]
    symbol_map = {f"{t}.T": t for t in tickers}

    try:
        # バルク取得（複数銘柄を1リクエストで）
        data = yf.Tickers(" ".join(yf_symbols))

        for sym, ticker_code in symbol_map.items():
            try:
                info = data.tickers[sym].info
                price = info.get("currentPrice") or info.get("regularMarketPrice", 0)
                prev_close = info.get("previousClose") or info.get("regularMarketPreviousClose", 0)
                change = round(price - prev_close, 1) if price and prev_close else 0
                volume = info.get("volume") or info.get("regularMarketVolume", 0)
                name = info.get("shortName") or info.get("longName", "")

                result[ticker_code] = {
                    "ticker": ticker_code,
                    "name": name,
                    "price": price or 0,
                    "change": change,
                    "volume": int(volume) if volume else 0,
                    "market_cap": 0,
                    "taishaku": "",
                    "timestamp": datetime.now().isoformat(),
                }
            except Exception as e:
                print(f"[API] yfinance 個別エラー ({ticker_code}): {e}")

    except Exception as e:
        print(f"[API] yfinance バルク取得エラー: {e}")
        # フォールバック: 1銘柄ずつ取得
        for t in tickers:
            try:
                tk = yf.Ticker(f"{t}.T")
                info = tk.info
                price = info.get("currentPrice") or info.get("regularMarketPrice", 0)
                prev_close = info.get("previousClose") or info.get("regularMarketPreviousClose", 0)
                change = round(price - prev_close, 1) if price and prev_close else 0
                volume = info.get("volume") or info.get("regularMarketVolume", 0)
                name = info.get("shortName") or info.get("longName", "")

                result[t] = {
                    "ticker": t,
                    "name": name,
                    "price": price or 0,
                    "change": change,
                    "volume": int(volume) if volume else 0,
                    "market_cap": 0,
                    "taishaku": "",
                    "timestamp": datetime.now().isoformat(),
                }
            except Exception as e2:
                print(f"[API] yfinance フォールバックエラー ({t}): {e2}")

    return result


def _get_kabutan_supplement(ticker: str) -> dict | None:
    """kabutan から時価総額・貸借区分を取得する（24時間キャッシュ）"""
    cached = _kabutan_cache.get(ticker)
    if cached is not None:
        return cached

    try:
        # 基本情報（時価総額）
        basic = fetch_kabutan_basic(ticker)
        market_cap = basic["market_cap"] if basic and basic.get("market_cap") else 0

        # 貸借区分
        taishaku = _fetch_kabutan_taishaku(ticker)

        supplement = {
            "market_cap": market_cap,
            "taishaku": taishaku,
        }
        _kabutan_cache.set(ticker, supplement)
        return supplement

    except Exception as e:
        print(f"[API] kabutan 補足データ取得エラー ({ticker}): {e}")
        return None


def _fetch_kabutan_taishaku(ticker: str) -> str:
    """kabutan から貸借区分を取得する。

    Returns:
        "貸借" / "制度" / ""
    """
    url = f"https://kabutan.jp/stock/?code={ticker}"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.encoding = "utf-8"
        if resp.status_code != 200:
            return ""

        soup = BeautifulSoup(resp.text, "html.parser")

        # 貸借区分を探す
        for td in soup.select("td"):
            text = td.get_text(strip=True)
            if text in ("貸借", "制度"):
                return text

        return ""

    except Exception:
        return ""


def test_connection() -> tuple[bool, str]:
    """API接続テストを行う。

    Returns:
        (成功フラグ, メッセージ)
    """
    try:
        tk = yf.Ticker("7203.T")  # トヨタでテスト
        info = tk.info
        price = info.get("currentPrice") or info.get("regularMarketPrice")
        if price:
            return True, f"yfinance 接続OK（トヨタ: ¥{price:,.0f}）"
        else:
            return False, "yfinance: 価格データを取得できません"
    except Exception as e:
        return False, f"yfinance 接続エラー: {e}"
