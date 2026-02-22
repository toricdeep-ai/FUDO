"""FUDO - 定期実行スケジューラ

各モジュールを定期実行する。
単体でも実行可能: python scheduler.py
"""

import time
from datetime import datetime

import schedule

from analytics import load_config
from notifier import notify_watchlist_summary, notify_disclosures, notify_taishaku_new
from notion_sync import sync_all_to_notion
from tdnet_fetch import fetch_tdnet_disclosures
from data_fetch import fetch_kabutan_taishaku_new
import database as db


def job_morning_summary():
    """朝のウォッチリストサマリー送信（8:30）"""
    today = datetime.now().strftime("%Y-%m-%d")
    stocks = db.get_stocks(today)
    if stocks:
        notify_watchlist_summary(stocks)
        print(f"[Scheduler] 朝サマリー送信: {len(stocks)}銘柄")
    else:
        print("[Scheduler] 本日の登録銘柄なし")


def job_notion_sync():
    """Notion同期（定期）"""
    config = load_config()
    notion_cfg = config.get("notion", {})
    if not notion_cfg.get("api_key"):
        return
    today = datetime.now().strftime("%Y-%m-%d")
    sync_all_to_notion(today)
    print(f"[Scheduler] Notion同期完了")


def job_evening_summary():
    """夕方のサマリー送信（15:30）"""
    today = datetime.now().strftime("%Y-%m-%d")
    stocks = db.get_stocks(today)
    if stocks:
        notify_watchlist_summary(stocks)
        print(f"[Scheduler] 夕方サマリー送信: {len(stocks)}銘柄")


_last_offhours_run: datetime | None = None


def _is_zaraba() -> bool:
    """ザラバ中かどうか（前場 9:00〜11:30 / 後場 12:30〜15:00）"""
    now = datetime.now()
    t = now.hour * 60 + now.minute
    return (540 <= t <= 690) or (750 <= t <= 900)  # 9:00-11:30, 12:30-15:00


def job_check_tdnet():
    """TDnet適時開示チェック（ザラバ中5分間隔 / それ以外30分間隔）"""
    global _last_offhours_run

    # ザラバ外は30分間隔にスロットリング
    if not _is_zaraba():
        now = datetime.now()
        if _last_offhours_run and (now - _last_offhours_run).total_seconds() < 1800:
            return
        _last_offhours_run = now

    config = load_config()
    disc_cfg = config.get("disclosure", {})
    auto_notify = disc_cfg.get("auto_notify", True)

    new_items = []

    # TDnet 適時開示取得
    try:
        tdnet_items = fetch_tdnet_disclosures()
        for item in tdnet_items:
            disc_id = db.add_disclosure(item)
            if disc_id is not None:
                item["id"] = disc_id
                new_items.append(item)
        print(f"[Scheduler] TDnet開示: {len(tdnet_items)}件取得, {len(new_items)}件新規")
    except Exception as e:
        print(f"[Scheduler] TDnet開示エラー: {e}")

    # LINE通知
    if new_items and auto_notify:
        notify_disclosures(new_items, source="TDnet")

        # 通知済みマーク
        for item in new_items:
            if item.get("id"):
                db.mark_disclosure_notified(item["id"])

    print(f"[Scheduler] TDnet開示チェック完了: 新規{len(new_items)}件")


def job_check_dde_ranking():
    """値上がりランキング監視（MarketSpeed IIローカル専用）"""
    try:
        from dde_monitor import check_and_notify_ranking
        check_and_notify_ranking()
    except ImportError:
        pass
    except Exception as e:
        print(f"[Scheduler] DDE rankingエラー: {e}")


# Track already-notified taishaku tickers per session
_notified_taishaku: set[str] = set()


def job_check_taishaku():
    """貸借銘柄指定チェック（時価総額100億以下 / 出来高100万以上）"""
    try:
        items = fetch_kabutan_taishaku_new()
        # Deduplicate within session
        new_items = [d for d in items if d["ticker"] not in _notified_taishaku]
        if new_items:
            notify_taishaku_new(new_items)
            for d in new_items:
                _notified_taishaku.add(d["ticker"])
            print(f"[Scheduler] 貸借銘柄指定: {len(new_items)}件通知")
        else:
            print(f"[Scheduler] 貸借銘柄指定: 新規なし")
    except Exception as e:
        print(f"[Scheduler] 貸借銘柄指定エラー: {e}")


def is_weekday() -> bool:
    """平日かどうか（土日はスキップ）"""
    return datetime.now().weekday() < 5


def start_scheduler():
    """スケジューラを起動する"""
    # 朝サマリー（平日 8:30）
    schedule.every().day.at("08:30").do(
        lambda: job_morning_summary() if is_weekday() else None
    )

    # Notion同期（平日 9:00, 12:00, 15:00）
    for t in ["09:00", "12:00", "15:00"]:
        schedule.every().day.at(t).do(
            lambda: job_notion_sync() if is_weekday() else None
        )

    # TDnet適時開示チェック（ザラバ中5分 / それ以外30分）
    schedule.every(5).minutes.do(job_check_tdnet)

    # 貸借銘柄指定チェック（平日 5分間隔）
    schedule.every(5).minutes.do(
        lambda: job_check_taishaku() if is_weekday() else None
    )

    # DDE値上がりランキング監視（ザラバ中30秒間隔、ローカル専用）
    schedule.every(30).seconds.do(
        lambda: job_check_dde_ranking() if is_weekday() and _is_zaraba() else None
    )

    # 夕方サマリー（平日 15:30）
    schedule.every().day.at("15:30").do(
        lambda: job_evening_summary() if is_weekday() else None
    )

    print("[Scheduler] 起動しました")
    print("  - 08:30  朝サマリー（LINE）")
    print("  - 09:00 / 12:00 / 15:00  Notion同期")
    print("  - 5分間隔   TDnet開示チェック（ザラバ中5分 / 時間外30分）")
    print("  - 5分間隔   貸借銘柄指定チェック（時価総額100億以下/出来高100万以上）")
    print("  - 30秒間隔  DDE値上がりランキング監視（ザラバ中・ローカル専用）")
    print("  - 15:30  夕方サマリー（LINE）")
    print("  ※ 平日のみ実行。Ctrl+C で終了。")

    while True:
        try:
            schedule.run_pending()
            time.sleep(30)
        except KeyboardInterrupt:
            print("[Scheduler] 終了します")
            break


if __name__ == "__main__":
    start_scheduler()
