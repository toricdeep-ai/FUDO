"""FUDO - データ取得モジュール（PRTimes・株探）"""

from __future__ import annotations

import re
import time
from datetime import datetime

import requests
from bs4 import BeautifulSoup

from analytics import load_config

# 同一セッション内の時価総額キャッシュ
_market_cap_cache: dict[str, float | None] = {}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}


def _get_config():
    config = load_config()
    return config.get("data_fetch", {})


def _request_interval():
    return _get_config().get("request_interval", 1)


# ========== 株探 ==========

def fetch_kabutan_basic(ticker: str) -> dict | None:
    """株探から銘柄の基本情報を取得する。

    Returns:
        {
            "ticker": str,
            "name": str,
            "market_cap": float,     # 時価総額（円）
            "shares_outstanding": int,
            "sector": str,
        }
    """
    url = f"https://kabutan.jp/stock/?code={ticker}"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.encoding = "utf-8"
        if resp.status_code != 200:
            print(f"[株探] HTTP {resp.status_code}: {ticker}")
            return None

        soup = BeautifulSoup(resp.text, "html.parser")

        # 銘柄名
        name_tag = soup.select_one("div.company_block h3")
        name = name_tag.get_text(strip=True) if name_tag else ""

        # 時価総額
        market_cap = _parse_kabutan_market_cap(soup)

        # セクター
        sector_tag = soup.select_one("div.company_block p.category")
        sector = sector_tag.get_text(strip=True) if sector_tag else ""

        time.sleep(_request_interval())

        return {
            "ticker": ticker,
            "name": name,
            "market_cap": market_cap,
            "sector": sector,
        }

    except Exception as e:
        print(f"[株探] 取得エラー ({ticker}): {e}")
        return None


def _parse_kabutan_market_cap(soup) -> float | None:
    """株探ページから時価総額を抽出する"""
    try:
        table = soup.select_one("div#stockinfo_i3 table")
        if not table:
            return None
        for tr in table.select("tr"):
            th = tr.select_one("th")
            td = tr.select_one("td")
            if th and "時価総額" in th.get_text():
                text = td.get_text(strip=True) if td else ""
                # 「123億円」→ 12300000000
                m = re.search(r"([\d,.]+)\s*億", text)
                if m:
                    val = float(m.group(1).replace(",", ""))
                    return val * 100_000_000
                # 「1,234百万円」→ 1234000000
                m = re.search(r"([\d,.]+)\s*百万", text)
                if m:
                    val = float(m.group(1).replace(",", ""))
                    return val * 1_000_000
        return None
    except Exception:
        return None


def fetch_kabutan_signal(ticker: str) -> dict | None:
    """株探から売買シグナル・テクニカル情報を取得する。

    Returns:
        {
            "ticker": str,
            "signal": str,          # シグナル概要
            "support": str,         # 下値支持
            "resistance": str,      # 上値抵抗
        }
    """
    url = f"https://kabutan.jp/stock/kabuka_value/?code={ticker}"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.encoding = "utf-8"
        if resp.status_code != 200:
            return None

        soup = BeautifulSoup(resp.text, "html.parser")

        signal = ""
        support = ""
        resistance = ""

        # シグナル情報テーブルを探す
        tables = soup.select("table.stock_kabuka_table")
        for table in tables:
            for tr in table.select("tr"):
                th = tr.select_one("th")
                td = tr.select_one("td")
                if not th or not td:
                    continue
                label = th.get_text(strip=True)
                value = td.get_text(strip=True)
                if "シグナル" in label:
                    signal = value
                elif "下値" in label or "サポート" in label:
                    support = value
                elif "上値" in label or "レジスタンス" in label:
                    resistance = value

        time.sleep(_request_interval())

        return {
            "ticker": ticker,
            "signal": signal,
            "support": support,
            "resistance": resistance,
        }

    except Exception as e:
        print(f"[株探] シグナル取得エラー ({ticker}): {e}")
        return None


# ========== PRTimes ==========

def fetch_kabutan_volume(ticker: str) -> int | None:
    """kabutan from ticker's volume."""
    url = f"https://kabutan.jp/stock/?code={ticker}"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.encoding = "utf-8"
        if resp.status_code != 200:
            return None
        soup = BeautifulSoup(resp.text, "html.parser")
        table = soup.select_one("div#stockinfo_i3 table")
        if not table:
            return None
        for tr in table.select("tr"):
            th = tr.select_one("th")
            td = tr.select_one("td")
            if th and "出来高" in th.get_text():
                text = td.get_text(strip=True) if td else ""
                num = re.sub(r"[^\d]", "", text)
                if num:
                    return int(num)
        return None
    except Exception as e:
        print(f"[kabutan] volume error ({ticker}): {e}")
        return None


def fetch_jpx_taishaku_new() -> list[dict]:
    """JPX new margin trading stock designations.

    Returns:
        [{"ticker": str, "name": str, "date": str}, ...]
    """
    url = "https://www.jpx.co.jp/markets/public/margin/index.html"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.encoding = "utf-8"
        if resp.status_code != 200:
            print(f"[JPX] HTTP {resp.status_code}")
            return []

        soup = BeautifulSoup(resp.text, "html.parser")

        results = []
        # Look for tables with margin stock info
        tables = soup.select("table")
        for table in tables:
            rows = table.select("tr")
            for tr in rows:
                tds = tr.select("td")
                if len(tds) < 2:
                    continue
                text = " ".join(td.get_text(strip=True) for td in tds)
                # Extract ticker (4 digits)
                m = re.search(r"(\d{4})", text)
                if not m:
                    continue
                ticker = m.group(1)
                name = tds[1].get_text(strip=True) if len(tds) > 1 else ""
                results.append({
                    "ticker": ticker,
                    "name": name,
                    "date": datetime.now().strftime("%Y-%m-%d"),
                })

        time.sleep(_request_interval())
        return results

    except Exception as e:
        print(f"[JPX] taishaku fetch error: {e}")
        return []


def fetch_kabutan_taishaku_new() -> list[dict]:
    """kabutan disclosure search for new taishaku designations.

    Returns:
        [{"ticker": str, "company_name": str, "title": str,
          "disclosed_at": str, "market_cap": float | None,
          "volume": int | None}, ...]
    """
    config = load_config()
    alert_cfg = config.get("api", {}).get("alert_filter", {})
    cap_max = alert_cfg.get("market_cap_max", 10_000_000_000)
    vol_min = alert_cfg.get("volume_min", 1_000_000)

    url = "https://kabutan.jp/disclosures/"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.encoding = "utf-8"
        if resp.status_code != 200:
            return []

        soup = BeautifulSoup(resp.text, "html.parser")
        table = soup.select_one("table.stock_table")
        if not table:
            return []

        results = []
        for tr in table.select("tbody tr"):
            tds = tr.select("td")
            if len(tds) < 5:
                continue

            title_tag = tds[-1].select_one("a") if tds else None
            title = title_tag.get_text(strip=True) if title_tag else ""

            # Check if it's taishaku designation
            if "貸借" not in title and "信用" not in title:
                continue

            time_text = tds[0].get_text(strip=True)
            ticker_text = tds[1].get_text(strip=True)
            ticker = re.sub(r"\D", "", ticker_text)
            if not ticker:
                continue

            company_name = tds[2].get_text(strip=True)

            # Market cap check（取得できない場合は除外しない）
            cap = _get_market_cap_cached(ticker)
            if cap is not None and cap > cap_max:
                continue

            # Volume check（取得できない場合は除外しない）
            vol = fetch_kabutan_volume(ticker)
            if vol is not None and vol < vol_min:
                continue

            today = datetime.now().strftime("%Y-%m-%d")
            results.append({
                "ticker": ticker,
                "company_name": company_name,
                "title": title,
                "disclosed_at": f"{today} {time_text}",
                "market_cap": cap,
                "volume": vol,
            })

        time.sleep(_request_interval())
        return results

    except Exception as e:
        print(f"[kabutan] taishaku scan error: {e}")
        return []


def fetch_prtimes_news(ticker: str, limit: int = 5) -> list[dict]:
    """PRTimesから銘柄関連のプレスリリースを取得する。

    Returns:
        [{"title": str, "url": str, "date": str, "company": str}, ...]
    """
    url = f"https://prtimes.jp/main/action.php?run=html&page=searchkey&search_word={ticker}"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.encoding = "utf-8"
        if resp.status_code != 200:
            print(f"[PRTimes] HTTP {resp.status_code}")
            return []

        soup = BeautifulSoup(resp.text, "html.parser")
        articles = soup.select("article.list-article__item")

        results = []
        for art in articles[:limit]:
            title_tag = art.select_one("h2.list-article__title a")
            date_tag = art.select_one("time")
            company_tag = art.select_one("span.list-article__company")

            if not title_tag:
                continue

            href = title_tag.get("href", "")
            if href and not href.startswith("http"):
                href = f"https://prtimes.jp{href}"

            results.append({
                "title": title_tag.get_text(strip=True),
                "url": href,
                "date": date_tag.get_text(strip=True) if date_tag else "",
                "company": company_tag.get_text(strip=True) if company_tag else "",
            })

        time.sleep(_request_interval())
        return results

    except Exception as e:
        print(f"[PRTimes] 取得エラー ({ticker}): {e}")
        return []


# ========== 信用残 ==========

def fetch_margin_data(ticker: str) -> dict | None:
    """株探から信用残データを取得する。

    Returns:
        {
            "ticker": str,
            "margin_buy": int,        # 信用買残
            "margin_sell": int,       # 信用売残
            "margin_buy_ratio": float, # 信用倍率
        }
    """
    url = f"https://kabutan.jp/stock/kabuka_value/?code={ticker}"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.encoding = "utf-8"
        if resp.status_code != 200:
            return None

        soup = BeautifulSoup(resp.text, "html.parser")

        margin_buy = 0
        margin_sell = 0

        tables = soup.select("table")
        for table in tables:
            for tr in table.select("tr"):
                th = tr.select_one("th")
                td = tr.select_one("td")
                if not th or not td:
                    continue
                label = th.get_text(strip=True)
                value = td.get_text(strip=True).replace(",", "")
                if "買残" in label:
                    try:
                        margin_buy = int(value)
                    except ValueError:
                        pass
                elif "売残" in label:
                    try:
                        margin_sell = int(value)
                    except ValueError:
                        pass

        ratio = margin_buy / margin_sell if margin_sell > 0 else 0

        time.sleep(_request_interval())

        return {
            "ticker": ticker,
            "margin_buy": margin_buy,
            "margin_sell": margin_sell,
            "margin_buy_ratio": round(ratio, 2),
        }

    except Exception as e:
        print(f"[株探] 信用残取得エラー ({ticker}): {e}")
        return None


# ========== 適時開示一括取得 ==========

def _get_market_cap_cached(ticker: str) -> float | None:
    """時価総額をキャッシュ付きで取得する"""
    if ticker in _market_cap_cache:
        return _market_cap_cache[ticker]
    info = fetch_kabutan_basic(ticker)
    cap = info["market_cap"] if info and info.get("market_cap") else None
    _market_cap_cache[ticker] = cap
    return cap


def fetch_kabutan_disclosures(max_pages: int = None) -> list[dict]:
    """株探 適時開示一覧をスクレイプし、時価総額100億以下の銘柄のみ返す。

    Returns:
        [{"ticker", "company_name", "market", "disclosure_type",
          "title", "url", "disclosed_at", "market_cap", "source"}, ...]
    """
    config = load_config()
    disc_cfg = config.get("disclosure", {})
    if max_pages is None:
        max_pages = disc_cfg.get("kabutan_max_pages", 3)
    cap_max = disc_cfg.get("market_cap_max", 10_000_000_000)

    results = []
    for page in range(1, max_pages + 1):
        url = f"https://kabutan.jp/disclosures/?page={page}"
        try:
            resp = requests.get(url, headers=HEADERS, timeout=15)
            resp.encoding = "utf-8"
            if resp.status_code != 200:
                print(f"[株探開示] HTTP {resp.status_code} (page={page})")
                break

            soup = BeautifulSoup(resp.text, "html.parser")
            table = soup.select_one("table.stock_table")
            if not table:
                break

            rows = table.select("tbody tr")
            if not rows:
                break

            for tr in rows:
                tds = tr.select("td")
                if len(tds) < 5:
                    continue

                # 時刻
                time_text = tds[0].get_text(strip=True)
                # 証券コード
                ticker_text = tds[1].get_text(strip=True)
                ticker = re.sub(r"\D", "", ticker_text)
                if not ticker:
                    continue
                # 会社名
                company_name = tds[2].get_text(strip=True)
                # 市場
                market = tds[3].get_text(strip=True) if len(tds) > 3 else ""
                # タイトル（リンク付き）
                title_tag = tds[4].select_one("a") if len(tds) > 4 else None
                if not title_tag:
                    title_tag = tds[-1].select_one("a")
                title = title_tag.get_text(strip=True) if title_tag else ""
                pdf_url = ""
                if title_tag and title_tag.get("href"):
                    href = title_tag["href"]
                    if not href.startswith("http"):
                        href = f"https://kabutan.jp{href}"
                    pdf_url = href
                # 種別
                disclosure_type = tds[4].get_text(strip=True) if len(tds) > 5 else ""

                # 時価総額チェック（取得できない場合は除外しない）
                cap = _get_market_cap_cached(ticker)
                if cap is not None and cap > cap_max:
                    continue

                # 開示日時を構築
                today = datetime.now().strftime("%Y-%m-%d")
                disclosed_at = f"{today} {time_text}" if time_text else today

                results.append({
                    "ticker": ticker,
                    "company_name": company_name,
                    "market": market,
                    "disclosure_type": disclosure_type,
                    "title": title,
                    "url": pdf_url,
                    "disclosed_at": disclosed_at,
                    "market_cap": cap,
                    "source": "kabutan",
                })

            time.sleep(_request_interval())

        except Exception as e:
            print(f"[株探開示] スクレイプエラー (page={page}): {e}")
            break

    print(f"[株探開示] {len(results)}件取得（時価総額{cap_max / 100_000_000:.0f}億以下）")
    return results


def fetch_prtimes_latest(max_pages: int = None) -> list[dict]:
    """PRTimesトップページから最新プレスリリースを取得し、
    証券コードを含むリリースで時価総額100億以下の銘柄のみ返す。

    Returns:
        [{"ticker", "company_name", "title", "url",
          "disclosed_at", "market_cap", "source"}, ...]
    """
    config = load_config()
    disc_cfg = config.get("disclosure", {})
    if max_pages is None:
        max_pages = disc_cfg.get("prtimes_max_pages", 3)
    cap_max = disc_cfg.get("market_cap_max", 10_000_000_000)

    # 証券コードを抽出するパターン（4桁数字）
    ticker_pattern = re.compile(r"[（(](\d{4})[)）]")

    results = []
    for page in range(1, max_pages + 1):
        url = f"https://prtimes.jp/main/html/searchrlp/company_id/{page}"
        if page == 1:
            url = "https://prtimes.jp/"
        try:
            resp = requests.get(url, headers=HEADERS, timeout=15)
            resp.encoding = "utf-8"
            if resp.status_code != 200:
                print(f"[PRTimes] HTTP {resp.status_code} (page={page})")
                break

            soup = BeautifulSoup(resp.text, "html.parser")
            articles = soup.select("article.list-article__item")
            if not articles:
                break

            for art in articles:
                title_tag = art.select_one("h2.list-article__title a")
                if not title_tag:
                    continue

                title = title_tag.get_text(strip=True)
                company_tag = art.select_one("span.list-article__company")
                company_name = company_tag.get_text(strip=True) if company_tag else ""
                date_tag = art.select_one("time")
                date_text = date_tag.get_text(strip=True) if date_tag else ""

                href = title_tag.get("href", "")
                if href and not href.startswith("http"):
                    href = f"https://prtimes.jp{href}"

                # テキストから証券コードを探す
                full_text = f"{title} {company_name}"
                match = ticker_pattern.search(full_text)
                if not match:
                    continue

                ticker = match.group(1)

                # 時価総額チェック
                cap = _get_market_cap_cached(ticker)
                if cap is None or cap > cap_max:
                    continue

                results.append({
                    "ticker": ticker,
                    "company_name": company_name,
                    "market": "",
                    "disclosure_type": "プレスリリース",
                    "title": title,
                    "url": href,
                    "disclosed_at": date_text,
                    "market_cap": cap,
                    "source": "prtimes",
                })

            time.sleep(_request_interval())

        except Exception as e:
            print(f"[PRTimes] スクレイプエラー (page={page}): {e}")
            break

    print(f"[PRTimes] {len(results)}件取得（時価総額{cap_max / 100_000_000:.0f}億以下）")
    return results
