"""FUDO - Notion連携モジュール

Notion APIを使ってウォッチリストを双方向同期する。
"""

import requests

from analytics import load_config
import database as db

NOTION_API_URL = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"


def _get_notion_config() -> dict:
    config = load_config()
    return config.get("notion", {})


def _headers() -> dict:
    cfg = _get_notion_config()
    api_key = cfg.get("api_key", "")
    if not api_key:
        raise ValueError("Notion API キーが未設定です。config.yaml の notion.api_key を設定してください。")
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Notion-Version": NOTION_VERSION,
    }


def push_to_notion(stock: dict) -> str | None:
    """銘柄1件をNotionデータベースに追加する。

    Returns:
        作成されたNotionページID / None（失敗時）
    """
    cfg = _get_notion_config()
    database_id = cfg.get("database_id", "")
    if not database_id:
        print("[Notion] database_id が未設定です。")
        return None

    market_cap_oku = stock.get("market_cap", 0) / 100_000_000 if stock.get("market_cap") else 0

    properties = {
        "銘柄名": {"title": [{"text": {"content": stock.get("name", "")}}]},
        "証券コード": {"rich_text": [{"text": {"content": stock.get("ticker", "")}}]},
        "日付": {"date": {"start": stock.get("date", "")}},
        "時価総額（億）": {"number": market_cap_oku},
        "信用買残%": {"number": stock.get("margin_buy_ratio", 0)},
        "節目": {"rich_text": [{"text": {"content": stock.get("fushi", "") or ""}}]},
        "PTS出来高": {"number": stock.get("pts_volume", 0)},
        "日々公表": {"number": stock.get("daily_disclosure_count", 0)},
        "日足位置": {"checkbox": bool(stock.get("hiduke_position_good", 0))},
        "低位/貸借": {"select": {"name": stock.get("teii_or_taishaku", "なし")}},
        "銘柄質": {"select": {"name": stock.get("meigara_quality", "その他")}},
        "級": {"select": {"name": stock.get("grade", "A")}},
        "最大R": {"number": stock.get("max_r", 1)},
        "ロット戦略": {"rich_text": [{"text": {"content": stock.get("lot_strategy", "") or ""}}]},
        "メモ": {"rich_text": [{"text": {"content": stock.get("memo", "") or ""}}]},
    }

    payload = {
        "parent": {"database_id": database_id},
        "properties": properties,
    }

    try:
        resp = requests.post(
            f"{NOTION_API_URL}/pages",
            headers=_headers(),
            json=payload,
            timeout=15,
        )
        if resp.status_code == 200:
            page_id = resp.json().get("id", "")
            print(f"[Notion] 追加成功: {stock.get('name')} ({page_id})")
            return page_id
        else:
            print(f"[Notion] 追加失敗: {resp.status_code} {resp.text}")
            return None
    except requests.RequestException as e:
        print(f"[Notion] 通信エラー: {e}")
        return None


def sync_all_to_notion(target_date: str = None):
    """ウォッチリストの全銘柄をNotionに同期する。"""
    stocks = db.get_stocks(target_date)
    if not stocks:
        print("[Notion] 同期対象の銘柄がありません。")
        return

    success = 0
    for stock in stocks:
        result = push_to_notion(stock)
        if result:
            success += 1

    print(f"[Notion] 同期完了: {success}/{len(stocks)} 件")


def fetch_from_notion(limit: int = 100) -> list[dict]:
    """Notionデータベースからエントリを取得する。"""
    cfg = _get_notion_config()
    database_id = cfg.get("database_id", "")
    if not database_id:
        print("[Notion] database_id が未設定です。")
        return []

    payload = {
        "page_size": limit,
        "sorts": [{"property": "日付", "direction": "descending"}],
    }

    try:
        resp = requests.post(
            f"{NOTION_API_URL}/databases/{database_id}/query",
            headers=_headers(),
            json=payload,
            timeout=15,
        )
        if resp.status_code != 200:
            print(f"[Notion] 取得失敗: {resp.status_code}")
            return []

        results = []
        for page in resp.json().get("results", []):
            props = page.get("properties", {})
            results.append({
                "notion_id": page.get("id"),
                "name": _extract_title(props.get("銘柄名", {})),
                "ticker": _extract_text(props.get("証券コード", {})),
                "grade": _extract_select(props.get("級", {})),
                "max_r": props.get("最大R", {}).get("number", 0),
                "date": _extract_date(props.get("日付", {})),
            })
        return results

    except requests.RequestException as e:
        print(f"[Notion] 通信エラー: {e}")
        return []


def _extract_title(prop: dict) -> str:
    items = prop.get("title", [])
    return items[0].get("text", {}).get("content", "") if items else ""


def _extract_text(prop: dict) -> str:
    items = prop.get("rich_text", [])
    return items[0].get("text", {}).get("content", "") if items else ""


def _extract_select(prop: dict) -> str:
    sel = prop.get("select")
    return sel.get("name", "") if sel else ""


def _extract_date(prop: dict) -> str:
    d = prop.get("date")
    return d.get("start", "") if d else ""
