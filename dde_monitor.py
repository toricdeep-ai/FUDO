"""FUDO - MarketSpeed II DDE 値上がりランキング監視

MarketSpeed II（DDEサーバ: MKSPD2）から値上がりランキングを取得し、
条件フィルタ後にLINE通知する。

注意: このモジュールはMarketSpeed IIが起動しているローカルPC専用。
      Streamlit Cloud上では try/except により無害にスキップされる。
"""

from __future__ import annotations

import time
from datetime import datetime

from analytics import load_config
from data_fetch import _get_market_cap_cached

# 前回通知時の前日比率（重複通知防止用）
_last_notified: dict[str, float] = {}

# DDE設定
DDE_SERVER = "MKSPD2"
DDE_TOPIC = "@RANKING"
RANKING_COUNT = 30


def get_ranking_dde() -> list[dict]:
    """MarketSpeed II から値上がりランキング上位30位を取得する。

    Returns:
        [{"ticker", "name", "price", "change_pct", "volume"}, ...]
    Raises:
        ImportError: pywin32が未インストールの場合
        Exception: MarketSpeed IIが起動していない場合
    """
    import win32com.client  # type: ignore  # pywin32

    results = []
    dde = win32com.client.Dispatch("DDEInitiate.Application")

    try:
        channel = dde.DDEInitiate(DDE_SERVER, DDE_TOPIC)
        try:
            for i in range(1, RANKING_COUNT + 1):
                idx = f"{i:03d}"
                try:
                    ticker = dde.DDERequest(channel, f"UP_CODE_{idx}").strip()
                    if not ticker or not ticker.isdigit():
                        continue
                    name = dde.DDERequest(channel, f"UP_NAME_{idx}").strip()
                    price_str = dde.DDERequest(channel, f"UP_PRICE_{idx}").strip().replace(",", "")
                    pct_str = dde.DDERequest(channel, f"UP_PRCRNG_{idx}").strip().replace(",", "").replace("%", "")
                    vol_str = dde.DDERequest(channel, f"UP_VOL_{idx}").strip().replace(",", "")

                    try:
                        price = float(price_str) if price_str else 0.0
                    except ValueError:
                        price = 0.0
                    try:
                        change_pct = float(pct_str) if pct_str else 0.0
                    except ValueError:
                        change_pct = 0.0
                    try:
                        volume = int(vol_str) if vol_str else 0
                    except ValueError:
                        volume = 0

                    results.append({
                        "ticker": ticker,
                        "name": name,
                        "price": price,
                        "change_pct": change_pct,
                        "volume": volume,
                    })
                except Exception as _item_err:
                    print(f"[DDE] ランキング{i}位取得エラー: {_item_err}")
                    continue
        finally:
            dde.DDETerminate(channel)
    finally:
        pass

    print(f"[DDE] ランキング取得: {len(results)}件")
    return results


def check_and_notify_ranking() -> None:
    """値上がりランキングを取得し、条件フィルタ適用後にLINE通知する。

    フィルタ条件:
        - 前日比 +5% 以上
        - 出来高 100万株以上
        - 時価総額 100億円以下

    重複通知防止:
        同一銘柄は前日比率が前回通知時より +0.5% 以上上昇した場合のみ再通知。
    """
    config = load_config()
    alert_cfg = config.get("api", {}).get("alert_filter", {})
    cap_max = alert_cfg.get("market_cap_max", 10_000_000_000)
    vol_min = alert_cfg.get("volume_min", 1_000_000)
    pct_min = alert_cfg.get("ranking_pct_min", 5.0)
    pct_renotify_delta = alert_cfg.get("ranking_pct_renotify_delta", 0.5)

    try:
        items = get_ranking_dde()
    except ImportError:
        print("[DDE] pywin32 未インストール。DDE監視をスキップします。")
        return
    except Exception as e:
        print(f"[DDE] MarketSpeed II 接続エラー（起動中か確認してください）: {e}")
        return

    notify_targets = []
    for item in items:
        ticker = item["ticker"]
        change_pct = item["change_pct"]
        volume = item["volume"]

        # 前日比フィルタ
        if change_pct < pct_min:
            continue

        # 出来高フィルタ
        if volume < vol_min:
            continue

        # 時価総額フィルタ
        cap = _get_market_cap_cached(ticker)
        if cap is not None and cap > cap_max:
            continue
        item["market_cap"] = cap

        # 重複通知チェック
        last_pct = _last_notified.get(ticker)
        if last_pct is not None and (change_pct - last_pct) < pct_renotify_delta:
            continue

        notify_targets.append(item)

    if not notify_targets:
        print(f"[DDE] ランキング通知対象なし")
        return

    try:
        from notifier import send_line
        lines = ["【値上がりランキング通知】"]
        for item in notify_targets:
            cap_str = f"{item['market_cap'] / 100_000_000:.0f}億" if item.get("market_cap") else "不明"
            lines.append(
                f"{item['name']}（{item['ticker']}）"
                f" +{item['change_pct']:.1f}%"
                f" 出来高{item['volume'] // 10000}万株"
                f" 時価総額{cap_str}"
            )
        message = "\n".join(lines)
        ok = send_line(message)
        if ok:
            for item in notify_targets:
                _last_notified[item["ticker"]] = item["change_pct"]
            print(f"[DDE] LINE通知送信: {len(notify_targets)}件")
        else:
            print(f"[DDE] LINE通知失敗")
    except Exception as e:
        print(f"[DDE] LINE通知エラー: {e}")


if __name__ == "__main__":
    # 単体テスト用
    print("[DDE] 接続テスト開始...")
    try:
        items = get_ranking_dde()
        print(f"取得件数: {len(items)}")
        for it in items[:5]:
            print(f"  {it['ticker']} {it['name']} +{it['change_pct']:.1f}% vol={it['volume']}")
    except Exception as e:
        print(f"エラー: {e}")
