"""FUDO - TDnet適時開示取得モジュール"""
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

_market_cap_cache: dict[str, float | None] = {}


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


def fetch_tdnet_disclosures(target_date: str | None = None) -> list[dict]:
    """TDnet（適時開示情報閲覧サービス）から当日の開示一覧を取得し、
    時価総額100億以下の銘柄のみ返す。

    Args:
        target_date: 取得対象日（YYYYMMDD形式。Noneなら当日）

    Returns:
        [{"ticker", "company_name", "title", "disclosed_at", "url",
          "market_cap", "source"}, ...]
    """
    config = load_config()
    disc_cfg = config.get("disclosure", {})
    cap_max = disc_cfg.get("market_cap_max", 10_000_000_000)

    if target_date is None:
        target_date = datetime.now().strftime("%Y%m%d")

    url = f"https://www.release.tdnet.info/inbs/I_list_001_{target_date}.html"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.encoding = "utf-8"
        if resp.status_code != 200:
            print(f"[TDnet] HTTP {resp.status_code}: {url}")
            return []

        soup = BeautifulSoup(resp.text, "html.parser")

        results = []
        today_str = datetime.now().strftime("%Y-%m-%d")

        # テーブルセレクタ（id/class が変わってもフォールバック）
        table = (
            soup.select_one("table#main-list-table")
            or soup.select_one("table.listbox")
            or soup.select_one("table")  # 属性なしテーブルにも対応
        )
        rows = table.select("tr") if table else soup.select("tr")

        for tr in rows:
            tds = tr.select("td")
            if len(tds) < 3:
                continue

            time_text = tds[0].get_text(strip=True)
            if not re.match(r"\d{2}:\d{2}", time_text):
                continue

            code_text = tds[1].get_text(strip=True)
            ticker = re.sub(r"\D", "", code_text)
            # 4桁または5桁コードを受け付ける（5桁は社債・ワラント等の場合もある）
            if not re.match(r"^\d{4,5}$", ticker):
                continue

            company_name = tds[2].get_text(strip=True) if len(tds) > 2 else ""

            title = ""
            pdf_url = ""
            if len(tds) > 3:
                title_tag = tds[3].select_one("a") or tds[-1].select_one("a")
                if title_tag:
                    title = title_tag.get_text(strip=True)
                    href = title_tag.get("href", "")
                    if href:
                        if not href.startswith("http"):
                            href = f"https://www.release.tdnet.info{href}"
                        pdf_url = href
                else:
                    title = tds[3].get_text(strip=True)

            if not title:
                continue

            # ETF/ETN排除：タイトルまたは会社名にETF・ETN・投資信託キーワードを含む場合スキップ
            _etf_keywords = ("上場投信", "ＥＴＦ", "ETF", "ＥＴＮ", "ETN", "投資信託", "NEXT FUNDS", "上場投資信託", "上場ETN")
            if any(kw in title or kw in company_name for kw in _etf_keywords):
                continue

            # 決算短信排除：定例の決算短信はスキップ
            _kessan_keywords = ("決算短信", "四半期報告書")
            if any(kw in title for kw in _kessan_keywords):
                continue

            # 時価総額フィルタ（5桁コードはkabutan検索用に4桁prefix試行）
            lookup_ticker = ticker[:4] if len(ticker) == 5 else ticker
            cap = _get_market_cap_cached(lookup_ticker)
            if cap is not None and cap > cap_max:
                continue

            results.append({
                "ticker": ticker,
                "company_name": company_name,
                "market": "",
                "disclosure_type": "",
                "title": title,
                "url": pdf_url,
                "disclosed_at": f"{today_str} {time_text}",
                "market_cap": cap,
                "source": "tdnet",
            })

        time.sleep(1)
        print(f"[TDnet] {len(results)}件取得（時価総額{cap_max / 100_000_000:.0f}億以下）")
        return results

    except Exception as e:
        print(f"[TDnet] スクレイプエラー: {e}")
        return []
