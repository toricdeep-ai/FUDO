"""FUDO - 値上がり率ランキング監視（kabutan.jp スクレイピング）

条件: 貸借銘柄 / 時価総額100億以下 / 出来高100万株以上 / 前日比+5%以上
"""
from __future__ import annotations

import re
import time
from datetime import datetime

import requests
from bs4 import BeautifulSoup

from analytics import load_config

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}

# セッション内キャッシュ（繰り返しリクエストを抑制）
_market_cap_cache: dict[str, float | None] = {}
_taishaku_cache: dict[str, bool] = {}


def _get_market_cap_cached(ticker: str) -> float | None:
    if ticker in _market_cap_cache:
        return _market_cap_cache[ticker]
    try:
        from data_fetch import fetch_kabutan_basic
        info = fetch_kabutan_basic(ticker)
        cap = info["market_cap"] if info and info.get("market_cap") else None
    except Exception:
        cap = None
    _market_cap_cache[ticker] = cap
    return cap


def _is_taishaku_cached(ticker: str) -> bool:
    """kabutan 銘柄ページで貸借区分を確認（結果をキャッシュ）"""
    if ticker in _taishaku_cache:
        return _taishaku_cache[ticker]
    url = f"https://kabutan.jp/stock/?code={ticker}"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=10)
        resp.encoding = "utf-8"
        # 銘柄ページ内に「貸借」という文字列があれば貸借銘柄
        result = "貸借" in resp.text
        _taishaku_cache[ticker] = result
        time.sleep(0.5)
        return result
    except Exception:
        _taishaku_cache[ticker] = False
        return False


def fetch_kabutan_rising_stocks(
    pct_min: float = 5.0,
    vol_min: int = 1_000_000,
    cap_max: float = 10_000_000_000,
    top_n: int = 50,
    taishaku_only: bool = True,
) -> list[dict]:
    """kabutan.jp 値上がり率ランキングから条件に合う銘柄を取得する。

    フィルタ条件:
        pct_min : 前日比率 % の下限（デフォルト +5%）
        vol_min : 出来高株数の下限（デフォルト 100万株）
        cap_max : 時価総額の上限（デフォルト 100億円）
        top_n   : ランキング上位何位まで取得するか

    Returns:
        [{"ticker", "name", "price", "change_pct", "volume", "market_cap"}, ...]
    """
    url = "https://kabutan.jp/warning/?mode=2_1"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.encoding = "utf-8"
        if resp.status_code != 200:
            print(f"[Ranking] HTTP {resp.status_code}")
            return []

        soup = BeautifulSoup(resp.text, "html.parser")

        # kabutan warning ページのランキングテーブル
        table = soup.select_one("table.stock_table")
        if not table:
            print("[Ranking] テーブルが見つかりません")
            return []

        candidates = []
        for tr in table.select("tbody tr")[:top_n]:
            tds = tr.select("td")
            if len(tds) < 5:
                continue

            # --- 証券コード ---
            code_text = tds[0].get_text(strip=True)
            ticker = re.sub(r"\D", "", code_text)
            if not re.match(r"^\d{4}$", ticker):
                continue

            # --- 銘柄名（リンクテキストを優先、市場区分が混入しないようにする） ---
            # 現在の列順: コード/銘柄名/市場/株価/前日比/前日比率/出来高/PER/PBR/利回り
            name_td = tds[1] if len(tds) > 1 else None
            if name_td:
                name_link = name_td.select_one("a")
                name = name_link.get_text(strip=True) if name_link else name_td.get_text(strip=True)
            else:
                name = ""

            # --- 現在値（td[3]） ---
            price = 0.0
            try:
                price = float(tds[3].get_text(strip=True).replace(",", "")) if len(tds) > 3 else 0.0
            except ValueError:
                pass

            # --- 前日比率(%)（td[5]） ---
            # 現在の列順: コード/銘柄名/市場/株価/前日比/前日比率/出来高/PER/PBR/利回り
            pct = 0.0
            try:
                pct_text = tds[5].get_text(strip=True).replace(",", "").replace("%", "").replace("+", "").replace("▲", "-")
                pct = float(pct_text)
            except (ValueError, IndexError):
                # fallback: 全tdから0〜50の範囲の値を探す
                for td in tds:
                    t = td.get_text(strip=True).replace(",", "").replace("%", "")
                    try:
                        v = float(t.replace("+", "").replace("▲", ""))
                        if 0 < v < 50:
                            pct = v
                            break
                    except ValueError:
                        pass

            if pct < pct_min:
                continue

            # --- 出来高（td[6]） ---
            vol = 0
            try:
                vol_text = tds[6].get_text(strip=True).replace(",", "") if len(tds) > 6 else "0"
                vol = int(vol_text)
            except (ValueError, IndexError):
                # fallback: 大きな数値のtdを探す
                for td in tds:
                    num = re.sub(r"[^\d]", "", td.get_text(strip=True))
                    if num and len(num) >= 6:
                        try:
                            v = int(num)
                            if v > vol:
                                vol = v
                        except ValueError:
                            pass

            if vol < vol_min:
                continue

            candidates.append({
                "ticker": ticker,
                "name": name,
                "price": price,
                "change_pct": pct,
                "volume": vol,
            })

        print(f"[Ranking] 一次候補: {len(candidates)}件（pct≥{pct_min}%, vol≥{vol_min // 10000}万株）")

        # --- 時価総額・貸借チェック（キャッシュ活用） ---
        results = []
        for c in candidates:
            cap = _get_market_cap_cached(c["ticker"])
            if cap is not None and cap > cap_max:
                continue
            if taishaku_only and not _is_taishaku_cached(c["ticker"]):
                continue
            c["market_cap"] = cap
            results.append(c)

        print(f"[Ranking] 最終HIT: {len(results)}件（時価総額{cap_max / 100_000_000:.0f}億以下 / 貸借銘柄）")
        return results

    except Exception as e:
        print(f"[Ranking] スクレイプエラー: {e}")
        return []
