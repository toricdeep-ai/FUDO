"""FUDO - LINE Messaging API + Discord notification module."""

from __future__ import annotations

import json

import requests
from analytics import load_config
from discord_notify import send_discord

LINE_PUSH_URL = "https://api.line.me/v2/bot/message/push"


def _get_line_config() -> dict:
    config = load_config()
    line_cfg = config.get("line", {})

    # Streamlit Cloud: st.secrets からも読み込む（config.yamlがgitignoreの場合）
    try:
        import streamlit as st
        secrets = st.secrets.get("line", {})
        if secrets:
            # secrets の値で上書き（空文字でなければ）
            for key in ("channel_access_token", "user_id", "channel_secret"):
                val = secrets.get(key, "")
                if val:
                    line_cfg[key] = val
    except Exception:
        pass

    return line_cfg


_last_line_status = {"ok": None, "msg": ""}


def get_last_line_status() -> dict:
    """直近のLINE送信結果を返す"""
    return _last_line_status


def send_line(message: str) -> bool:
    """LINE Messaging API でプッシュメッセージを送信する。

    Returns:
        True: 送信成功 / False: 送信失敗
    """
    cfg = _get_line_config()
    token = cfg.get("channel_access_token", "")
    user_id = cfg.get("user_id", "")

    if not token:
        _last_line_status["ok"] = False
        _last_line_status["msg"] = "channel_access_token 未設定。Streamlit Cloud の Secrets に line.channel_access_token を設定してください。"
        print(f"[LINE] {_last_line_status['msg']}")
        return False
    if not user_id:
        _last_line_status["ok"] = False
        _last_line_status["msg"] = "user_id 未設定。Streamlit Cloud の Secrets に line.user_id を設定してください。"
        print(f"[LINE] {_last_line_status['msg']}")
        return False

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
    }
    payload = {
        "to": user_id,
        "messages": [
            {"type": "text", "text": message}
        ],
    }

    try:
        resp = requests.post(
            LINE_PUSH_URL, headers=headers,
            data=json.dumps(payload), timeout=10,
        )
        if resp.status_code == 200:
            _last_line_status["ok"] = True
            _last_line_status["msg"] = "送信成功"
            print("[LINE] 送信成功")
            return True
        else:
            _last_line_status["ok"] = False
            _last_line_status["msg"] = f"送信失敗: {resp.status_code} {resp.text}"
            print(f"[LINE] {_last_line_status['msg']}")
            return False
    except requests.RequestException as e:
        _last_line_status["ok"] = False
        _last_line_status["msg"] = f"通信エラー: {e}"
        print(f"[LINE] {_last_line_status['msg']}")
        return False


def _send_all(message: str):
    """LINE + Discord both."""
    send_line(message)
    send_discord(message)


def notify_grade_change(name: str, ticker: str, old_grade: str, new_grade: str):
    """級変更を通知する"""
    cfg = _get_line_config()
    if not cfg.get("notify_on_grade_change", True):
        return
    message = (
        f"📊 級変更通知\n"
        f"銘柄: {name}（{ticker}）\n"
        f"変更: {old_grade} → {new_grade}"
    )
    _send_all(message)


def notify_price_alert(name: str, ticker: str, price: float, fushi: str, direction: str):
    """節目到達を通知する"""
    cfg = _get_line_config()
    if not cfg.get("notify_on_price_alert", True):
        return
    message = (
        f"🔔 価格アラート\n"
        f"銘柄: {name}（{ticker}）\n"
        f"現在値: ¥{price:,.0f}\n"
        f"節目: {fushi}\n"
        f"方向: {direction}"
    )
    _send_all(message)


def notify_watchlist_summary(stocks: list[dict]):
    """ウォッチリストのサマリーを通知する"""
    msg = build_morning_strategy(stocks)
    _send_all(msg)


def build_morning_strategy(stocks: list[dict] = None) -> str:
    """おはよう → 事前戦略一覧テキストを生成する"""
    from datetime import date as _date
    import database as db
    from analytics import load_config, calc_lot_r

    config = load_config()
    r_unit = config.get("risk", {}).get("r_unit", 10000)

    if stocks is None:
        stocks = db.get_stocks(str(_date.today()))

    if not stocks:
        return "☀️ おはようございます\n\n本日の登録銘柄はありません。\nサイドバーから追加してください。"

    lines = [
        f"☀️ おはようございます",
        f"📋 本日の事前戦略（{stocks[0].get('date', '')}）",
        f"━━━━━━━━━━━━━━━",
    ]

    for i, s in enumerate(stocks, 1):
        grade = s.get("grade", "?")
        max_r = s.get("max_r", 1)
        risk_amount = max_r * r_unit
        name = s.get("name", "")
        ticker = s.get("ticker", "")
        fushi = s.get("fushi", "")
        quality = s.get("meigara_quality", "")
        memo = s.get("memo", "")
        market_cap = s.get("market_cap", 0)
        cap_oku = f"{market_cap / 100_000_000:.0f}億" if market_cap else "-"

        # 節目からロット概算（最初の節目をエントリー目安にする）
        lot_text = "-"
        if fushi:
            try:
                fushi_prices = [float(f.strip()) for f in fushi.split(",") if f.strip()]
                if len(fushi_prices) >= 2:
                    entry = fushi_prices[0]
                    stop = fushi_prices[1]
                    result = calc_lot_r(entry, stop, max_r)
                    lot_text = f"{result['lot']}株"
                elif len(fushi_prices) == 1:
                    entry = fushi_prices[0]
                    stop = entry * 0.95
                    result = calc_lot_r(entry, stop, max_r)
                    lot_text = f"{result['lot']}株(概算)"
            except (ValueError, ZeroDivisionError):
                pass

        lines.append(f"\n【{i}】{name}（{ticker}）")
        lines.append(f"  級: {grade}  |  時価総額: {cap_oku}")
        lines.append(f"  最大: {max_r}R（¥{risk_amount:,}）")
        lines.append(f"  ロット: {lot_text}")
        if fushi:
            lines.append(f"  節目: {fushi}")
        if quality:
            lines.append(f"  銘柄質: {quality}")
        if memo:
            lines.append(f"  📝 {memo}")

    lines.append(f"\n━━━━━━━━━━━━━━━")
    lines.append(f"💰 1R = ¥{r_unit:,}  |  全{len(stocks)}銘柄")

    return "\n".join(lines)


def notify_taishaku_new(items: list[dict]):
    """新規貸借銘柄指定をLINE通知する"""
    if not items:
        return

    lines = [
        "🔄 貸借銘柄指定（新規）",
        "━━━━━━━━━━━━━━━",
    ]

    for i, d in enumerate(items, 1):
        company = d.get("company_name", "")
        ticker = d.get("ticker", "")
        cap = d.get("market_cap", 0)
        cap_oku = f"{cap / 100_000_000:.0f}億" if cap else "-"
        vol = d.get("volume", 0)
        vol_man = f"{vol / 10_000:.0f}万" if vol else "-"
        title = d.get("title", "")
        disclosed_at = d.get("disclosed_at", "")

        lines.append(f"\n【{i}】{company}（{ticker}）")
        lines.append(f"  時価総額: {cap_oku}  |  出来高: {vol_man}")
        lines.append(f"  📄 {title}")
        if disclosed_at:
            lines.append(f"  🕐 {disclosed_at}")

    lines.append(f"\n━━━━━━━━━━━━━━━")
    lines.append(f"条件: 時価総額100億以下 / 出来高100万以上")
    lines.append(f"検出: {len(items)}件")

    _send_all("\n".join(lines))


def notify_disclosures(disclosures: list[dict], source: str = "株探"):
    """適時開示をLINE通知する"""
    cfg = _get_line_config()
    if not disclosures:
        return

    lines = [
        "📢 適時開示（時価総額100億以下）",
        "━━━━━━━━━━━━━━━",
    ]

    for i, d in enumerate(disclosures, 1):
        company = d.get("company_name", "")
        ticker = d.get("ticker", "")
        cap = d.get("market_cap", 0)
        cap_oku = f"{cap / 100_000_000:.0f}億" if cap else "-"
        market = d.get("market", "")
        dtype = d.get("disclosure_type", "")
        title = d.get("title", "")
        disclosed_at = d.get("disclosed_at", "")
        # 時刻部分のみ抽出
        time_part = disclosed_at.split(" ")[-1] if " " in disclosed_at else disclosed_at

        lines.append(f"\n【{i}】{company}（{ticker}）")
        lines.append(f"  時価総額: {cap_oku}  |  市場: {market}")
        if dtype:
            lines.append(f"  種別: {dtype}")
        lines.append(f"  📄 {title}")
        lines.append(f"  🕐 {time_part}")

    lines.append(f"\n━━━━━━━━━━━━━━━")
    lines.append(f"検出: {len(disclosures)}件 / ソース: {source}")

    _send_all("\n".join(lines))


def reply_line(reply_token: str, message: str) -> bool:
    """LINE Messaging API でリプライする（Webhook応答用）"""
    cfg = _get_line_config()
    token = cfg.get("channel_access_token", "")

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
    }
    payload = {
        "replyToken": reply_token,
        "messages": [
            {"type": "text", "text": message}
        ],
    }

    try:
        resp = requests.post(
            "https://api.line.me/v2/bot/message/reply",
            headers=headers,
            data=json.dumps(payload), timeout=10,
        )
        return resp.status_code == 200
    except requests.RequestException:
        return False
