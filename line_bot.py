"""FUDO - LINE Bot Webhook サーバー

「おはよう」→ 事前戦略一覧を返す
起動: python line_bot.py
"""

import json
import hashlib
import hmac
import base64

from flask import Flask, request, abort
from analytics import load_config
from notifier import build_morning_strategy, reply_line

app = Flask(__name__)


def _get_channel_secret() -> str:
    config = load_config()
    return config.get("line", {}).get("channel_secret", "")


@app.route("/callback", methods=["POST"])
def callback():
    """LINE Webhook エンドポイント"""
    # 署名検証
    signature = request.headers.get("X-Line-Signature", "")
    body = request.get_data(as_text=True)

    channel_secret = _get_channel_secret()
    if channel_secret:
        hash_val = hmac.new(
            channel_secret.encode("utf-8"),
            body.encode("utf-8"),
            hashlib.sha256,
        ).digest()
        expected = base64.b64encode(hash_val).decode("utf-8")
        if signature != expected:
            abort(403)

    # イベント処理
    data = json.loads(body)
    for event in data.get("events", []):
        if event.get("type") != "message":
            continue
        if event.get("message", {}).get("type") != "text":
            continue

        text = event["message"]["text"].strip()
        reply_token = event["replyToken"]

        handle_message(text, reply_token)

    return "OK"


def handle_message(text: str, reply_token: str):
    """受信メッセージに応じて返信する"""
    # おはよう → 事前戦略
    if text in ("おはよう", "おはよ", "おは", "戦略", "今日"):
        msg = build_morning_strategy()
        reply_line(reply_token, msg)

    elif text in ("ヘルプ", "help", "？"):
        msg = (
            "📖 FUDO コマンド一覧\n"
            "━━━━━━━━━━━━━━━\n"
            "「おはよう」→ 本日の事前戦略\n"
            "「戦略」→ 本日の事前戦略\n"
            "「今日」→ 本日の事前戦略"
        )
        reply_line(reply_token, msg)


if __name__ == "__main__":
    print("[LINE Bot] 起動中... http://localhost:5000/callback")
    print("[LINE Bot] Webhook URL を LINE Developers で設定してください")
    app.run(host="0.0.0.0", port=5000, debug=False)
