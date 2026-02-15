"""FUDO - 株価監視モジュール

yfinance + 株探スクレイピングで株価データを取得・監視する。

スクリーニング条件（config.yaml で設定）:
  - 貸借銘柄
  - 時価総額100億以下
  - 出来高100万以上
  → 条件合致で LINE 通知

データソース:
  - yfinance: 現在値・前日比・出来高・銘柄名（15-20分遅延）
  - kabutan: 時価総額・貸借区分（24時間キャッシュ）
  - 板データ: 無料APIでは取得不可（常にNone）
"""

from __future__ import annotations

import time
from collections import deque
from datetime import datetime

from analytics import load_config
from notifier import notify_price_alert, send_line
import database as db
from stock_api import get_prices, test_connection


def get_rss_board(ticker: str) -> dict | None:
    """板データを取得する。

    無料APIでは板情報は取得不可のため、常に None を返す。
    app.py のタブ8は None 時のフォールバック表示あり（「板データなし」）。
    """
    return None


# 同一銘柄の重複通知を防ぐ（1セッション内）
_notified_tickers: set[str] = set()


def _get_api_config() -> dict:
    config = load_config()
    return config.get("api", {})


def get_rss_prices(tickers: list[str] = None) -> list[dict]:
    """APIから株価データを取得する。

    Args:
        tickers: 証券コードのリスト。None の場合は空リストを返す。

    Returns:
        [{"ticker", "name", "price", "change", "volume",
          "market_cap", "taishaku", "timestamp"}, ...]
    """
    if not tickers:
        return []

    try:
        return get_prices(tickers)
    except Exception as e:
        print(f"[API] データ取得エラー: {e}")
        return []


# ========== スクリーニング ==========

def screen_and_notify(prices: list[dict]):
    """条件フィルタに合致した銘柄をLINE通知する。

    条件（config.yaml api.alert_filter）:
      - 貸借銘柄
      - 時価総額100億以下
      - 出来高100万以上
    """
    api_cfg = _get_api_config()
    filt = api_cfg.get("alert_filter", {})

    taishaku_only = filt.get("taishaku_only", True)
    cap_max = filt.get("market_cap_max", 10_000_000_000)
    vol_min = filt.get("volume_min", 1_000_000)

    hits = []

    for p in prices:
        ticker = p["ticker"]

        # 既に通知済みならスキップ
        if ticker in _notified_tickers:
            continue

        # 貸借チェック
        if taishaku_only and p.get("taishaku", "") != "貸借":
            continue

        # 時価総額チェック
        if p.get("market_cap", 0) <= 0 or p["market_cap"] > cap_max:
            continue

        # 出来高チェック
        if p.get("volume", 0) < vol_min:
            continue

        hits.append(p)
        _notified_tickers.add(ticker)

    if hits:
        _send_screen_alert(hits)

    return hits


def _send_screen_alert(hits: list[dict]):
    """スクリーニング合致銘柄をLINEに送信"""
    lines = [
        f"🔍 スクリーニング通知",
        f"━━━━━━━━━━━━━━━",
        f"条件: 貸借 / 時価総額100億以下 / 出来高100万以上",
        f"",
    ]

    for h in hits:
        cap_oku = h["market_cap"] / 100_000_000 if h["market_cap"] else 0
        vol_man = h["volume"] / 10_000 if h["volume"] else 0
        lines.append(
            f"🎯 {h['name']}（{h['ticker']}）\n"
            f"  現在値: ¥{h['price']:,.0f}（{h['change']:+.0f}）\n"
            f"  時価総額: {cap_oku:.0f}億 / 出来高: {vol_man:.0f}万株\n"
            f"  貸借: {h['taishaku']}"
        )

    lines.append(f"\n━━━━━━━━━━━━━━━")
    lines.append(f"検出: {len(hits)}銘柄 / {datetime.now().strftime('%H:%M:%S')}")

    send_line("\n".join(lines))
    print(f"[API] スクリーニング通知: {len(hits)}銘柄")


# ========== 任意銘柄アラート ==========

# 前回出来高を記録（出来高急増判定用）
_prev_volumes: dict[str, int] = {}


def check_price_alerts(prices: list[dict]):
    """登録済みの価格アラート・出来高アラートをチェックし、LINE通知する。

    alert_type:
      - "price"  : 指定株価到達
      - "volume" : 出来高急増（前回比 volume_ratio 倍以上）
    """
    alerts = db.get_active_alerts()
    if not alerts:
        return

    price_map = {p["ticker"]: p for p in prices}

    for alert in alerts:
        ticker = alert["ticker"]
        if ticker not in price_map:
            continue

        p = price_map[ticker]
        alert_type = alert.get("alert_type", "price")

        if alert_type == "price":
            _check_price_target(alert, p)
        elif alert_type == "volume":
            _check_volume_surge(alert, p)


def _check_price_target(alert: dict, p: dict):
    """指定株価到達チェック"""
    target = alert.get("target_price")
    if not target:
        return

    price = p.get("price", 0)
    direction = alert.get("direction", "above")

    triggered = False
    if direction == "above" and price >= target:
        triggered = True
    elif direction == "below" and price <= target:
        triggered = True

    if triggered:
        direction_text = "上抜け" if direction == "above" else "下抜け"
        memo = alert.get("memo", "")
        memo_text = f"\n  📝 {memo}" if memo else ""

        msg = (
            f"🚨 価格アラート発動！\n"
            f"━━━━━━━━━━━━━━━\n"
            f"銘柄: {alert['name']}（{alert['ticker']}）\n"
            f"現在値: ¥{price:,.0f}\n"
            f"設定値: ¥{target:,.0f}（{direction_text}）{memo_text}"
        )
        send_line(msg)
        db.trigger_alert(alert["id"])
        print(f"[ALERT] 価格到達: {alert['name']} ¥{price:,.0f} {direction_text} ¥{target:,.0f}")


def _check_volume_surge(alert: dict, p: dict):
    """出来高急増チェック"""
    ticker = alert["ticker"]
    current_vol = p.get("volume", 0)
    ratio_threshold = alert.get("volume_ratio", 2.0)

    prev_vol = _prev_volumes.get(ticker, 0)
    _prev_volumes[ticker] = current_vol

    # 初回は比較不可
    if prev_vol == 0:
        return

    # 出来高が前回の ratio_threshold 倍以上に増加
    if prev_vol > 0 and current_vol >= prev_vol * ratio_threshold:
        increase = current_vol / prev_vol
        vol_man = current_vol / 10_000
        memo = alert.get("memo", "")
        memo_text = f"\n  📝 {memo}" if memo else ""

        msg = (
            f"📈 出来高急増アラート！\n"
            f"━━━━━━━━━━━━━━━\n"
            f"銘柄: {alert['name']}（{alert['ticker']}）\n"
            f"現在値: ¥{p.get('price', 0):,.0f}\n"
            f"出来高: {vol_man:.0f}万株（{increase:.1f}倍に急増）{memo_text}"
        )
        send_line(msg)
        db.trigger_alert(alert["id"])
        print(f"[ALERT] 出来高急増: {alert['name']} {increase:.1f}倍")


# ========== 3分間急騰アラート ==========

# 銘柄ごとの価格履歴: {ticker: deque([(timestamp, price), ...], maxlen=200)}
_price_history: dict[str, deque] = {}

# 同一銘柄の急騰通知を連続で送らないためのクールダウン（最終通知時刻）
_surge_notified_at: dict[str, datetime] = {}

SURGE_THRESHOLD_PCT = 4.0    # 急騰判定: 4%以上
SURGE_WINDOW_SEC = 180       # 判定ウィンドウ: 3分（180秒）
SURGE_COOLDOWN_SEC = 300     # 同一銘柄の再通知クールダウン: 5分


def record_price(ticker: str, price: float):
    """価格を履歴に記録する（タイムスタンプ付き）"""
    if price <= 0:
        return
    if ticker not in _price_history:
        _price_history[ticker] = deque(maxlen=200)
    _price_history[ticker].append((datetime.now(), price))


def check_surge_alerts(prices: list[dict]) -> list[dict]:
    """3分前と比較して4%以上上昇した銘柄をLINE通知する。

    Returns:
        通知した銘柄のリスト
    """
    now = datetime.now()
    hits = []

    for p in prices:
        ticker = p["ticker"]
        current_price = p.get("price", 0) or 0
        if current_price <= 0:
            continue

        # 価格を記録
        record_price(ticker, current_price)

        # 履歴が無ければスキップ
        history = _price_history.get(ticker)
        if not history or len(history) < 2:
            continue

        # 3分前の価格を探す（ウィンドウ内で最も古いもの）
        base_price = None
        for ts, price in history:
            elapsed = (now - ts).total_seconds()
            if elapsed >= SURGE_WINDOW_SEC:
                base_price = price
                break

        if base_price is None or base_price <= 0:
            continue

        change_pct = (current_price - base_price) / base_price * 100
        if change_pct < SURGE_THRESHOLD_PCT:
            continue

        # クールダウン確認
        last_notified = _surge_notified_at.get(ticker)
        if last_notified and (now - last_notified).total_seconds() < SURGE_COOLDOWN_SEC:
            continue

        # LINE通知
        name = p.get("name", ticker)
        vol_man = (p.get("volume", 0) or 0) / 10_000
        msg = (
            f"🚀 3分間急騰アラート！\n"
            f"━━━━━━━━━━━━━━━\n"
            f"銘柄: {name}（{ticker}）\n"
            f"現在値: ¥{current_price:,.0f}\n"
            f"3分前: ¥{base_price:,.0f} → +{change_pct:.1f}%\n"
            f"出来高: {vol_man:,.0f}万株\n"
            f"━━━━━━━━━━━━━━━\n"
            f"検出: {now.strftime('%H:%M:%S')}"
        )
        send_line(msg)
        _surge_notified_at[ticker] = now
        hits.append(p)
        print(f"[SURGE] {name}（{ticker}）+{change_pct:.1f}% / 3分間")

    return hits


# ========== 節目アラート ==========

def check_fushi_alerts(prices: list[dict]):
    """節目付近の銘柄をLINE通知する。"""
    for p in prices:
        ticker = p["ticker"]
        price = p["price"]
        if not price:
            continue

        stocks = db.get_stocks_by_ticker(ticker)
        if not stocks:
            continue

        latest = stocks[0]
        fushi_str = latest.get("fushi", "")
        if not fushi_str:
            continue

        for fushi_val in fushi_str.split(","):
            fushi_val = fushi_val.strip()
            try:
                fushi_price = float(fushi_val)
            except ValueError:
                continue

            if price >= fushi_price * 0.995 and price <= fushi_price * 1.005:
                notify_price_alert(
                    name=latest["name"],
                    ticker=ticker,
                    price=price,
                    fushi=fushi_val,
                    direction="節目付近",
                )


# ========== 監視ループ ==========

def monitor_loop(interval: int = None):
    """監視ループ。Ctrl+Cで終了。"""
    api_cfg = _get_api_config()
    if interval is None:
        interval = api_cfg.get("update_interval", 60)

    filt = api_cfg.get("alert_filter", {})
    cap_oku = filt.get("market_cap_max", 10_000_000_000) / 100_000_000
    vol_man = filt.get("volume_min", 1_000_000) / 10_000

    active_alerts = db.get_active_alerts()

    print(f"[API] 監視開始（{interval}秒間隔）… Ctrl+C で終了")
    print(f"[API] スクリーニング条件:")
    print(f"  - 貸借銘柄のみ: {filt.get('taishaku_only', True)}")
    print(f"  - 時価総額: {cap_oku:.0f}億以下")
    print(f"  - 出来高: {vol_man:.0f}万以上")
    print(f"[API] 個別アラート: {len(active_alerts)}件")

    while True:
        try:
            prices = get_rss_prices()
            if prices:
                # スクリーニング → LINE通知
                hits = screen_and_notify(prices)

                # 個別アラート（価格到達・出来高急増）
                check_price_alerts(prices)

                # 節目アラート
                check_fushi_alerts(prices)

                # 3分間急騰アラート
                surge_hits = check_surge_alerts(prices)

                now = datetime.now().strftime("%H:%M:%S")
                hit_text = f" / HIT: {len(hits)}件" if hits else ""
                print(f"[API] {now} - {len(prices)}銘柄取得{hit_text}")

            time.sleep(interval)

        except KeyboardInterrupt:
            print(f"\n[API] 監視終了（通知済み: {len(_notified_tickers)}銘柄）")
            break
        except Exception as e:
            print(f"[API] エラー: {e}")
            time.sleep(interval)


def reset_notified():
    """通知済みリストをリセットする（日替わり等に使用）"""
    _notified_tickers.clear()
    print("[API] 通知済みリストをリセットしました")


if __name__ == "__main__":
    monitor_loop()
