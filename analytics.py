"""FUDO - 統計・期待値計算モジュール"""

from __future__ import annotations

import math
from pathlib import Path

import yaml


def load_config() -> dict:
    base = Path(__file__).parent
    config_path = base / "config.yaml"
    if config_path.exists():
        with open(config_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)
    default_path = base / "config.default.yaml"
    if default_path.exists():
        with open(default_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)
    return {}


# ---------- 級判定 ----------

def judge_grade(
    market_cap: float | None,
    hiduke_position_good: bool = False,
    teii_or_taishaku: str = "なし",
) -> tuple[str, int]:
    """級（SS / S / A）を判定し、最大R数も返す。

    Returns:
        (grade, max_r)  例: ("SS", 10)
    """
    config = load_config()
    rules = config.get("grade_rules", {})
    r_unit = config.get("risk", {}).get("r_unit", 10000)

    # SS判定: 時価総額60億以下 & 日足位置良い & 低位or貸借
    ss_rule = rules.get("SS", {})
    if (market_cap is not None
            and market_cap <= ss_rule.get("market_cap_max", 6_000_000_000)
            and hiduke_position_good
            and teii_or_taishaku in ("低位", "貸借")):
        return "SS", ss_rule.get("max_r", 10)

    # S判定: 時価総額60億以下
    s_rule = rules.get("S", {})
    if (market_cap is not None
            and market_cap <= s_rule.get("market_cap_max", 6_000_000_000)):
        return "S", s_rule.get("max_r", 5)

    # A判定: それ以外すべて
    a_rule = rules.get("A", {})
    return "A", a_rule.get("max_r", 1)


# ---------- ロット計算（Rベース） ----------

def calc_lot_r(
    entry_price: float,
    stop_loss_price: float,
    max_r: int,
    r_unit: int = None,
) -> dict:
    """R数ベースのロット数を計算する。

    Args:
        entry_price: エントリー価格
        stop_loss_price: 損切り価格
        max_r: 最大R数（級による）
        r_unit: 1Rの金額（デフォルト: config の r_unit）

    Returns:
        {
            "lot": int,              # 株数（100株単位）
            "risk_amount": float,    # リスク金額（max_r × r_unit）
            "loss_per_share": float, # 1株あたり損切り額
            "position_size": float,  # ポジションサイズ（円）
            "max_r": int,
            "r_unit": int,
        }
    """
    config = load_config()
    if r_unit is None:
        r_unit = config.get("risk", {}).get("r_unit", 10000)

    risk_amount = max_r * r_unit
    loss_per_share = abs(entry_price - stop_loss_price)

    if loss_per_share == 0:
        return {
            "lot": 0,
            "risk_amount": risk_amount,
            "loss_per_share": 0,
            "position_size": 0,
            "max_r": max_r,
            "r_unit": r_unit,
        }

    raw_shares = risk_amount / loss_per_share
    lot = int(math.floor(raw_shares / 100)) * 100  # 100株単位
    position_size = lot * entry_price

    return {
        "lot": lot,
        "risk_amount": risk_amount,
        "loss_per_share": loss_per_share,
        "position_size": position_size,
        "max_r": max_r,
        "r_unit": r_unit,
    }


def calc_lot_from_percent(
    entry_price: float,
    stop_loss_percent: float = None,
    max_r: int = 1,
    r_unit: int = None,
) -> dict:
    """損切り幅を%で指定してロットを計算する"""
    config = load_config()
    risk_cfg = config.get("risk", {})

    if stop_loss_percent is None:
        stop_loss_percent = risk_cfg.get("default_stop_loss", 0.05)

    stop_loss_price = entry_price * (1 - stop_loss_percent)
    return calc_lot_r(entry_price, stop_loss_price, max_r, r_unit)


# ---------- 期待値計算 ----------

def calc_expected_value(
    win_rate: float,
    avg_win: float,
    avg_loss: float,
) -> dict:
    """期待値とプロフィットファクターを計算する。

    Args:
        win_rate: 勝率（0.0〜1.0）
        avg_win: 平均利益（円）
        avg_loss: 平均損失（円、正の値で入力）

    Returns:
        {
            "expected_value": float,     # 1トレードあたり期待値
            "profit_factor": float,      # プロフィットファクター
            "breakeven_winrate": float,  # 損益分岐勝率
        }
    """
    expected_value = (win_rate * avg_win) - ((1 - win_rate) * avg_loss)

    loss_total = (1 - win_rate) * avg_loss
    profit_factor = (win_rate * avg_win) / loss_total if loss_total > 0 else float("inf")

    breakeven = avg_loss / (avg_win + avg_loss) if (avg_win + avg_loss) > 0 else 0

    return {
        "expected_value": round(expected_value, 2),
        "profit_factor": round(profit_factor, 2),
        "breakeven_winrate": round(breakeven, 4),
    }


# ---------- 統計機能（Rベース） ----------

def calc_trade_statistics(trades: list[dict]) -> dict:
    """全トレードからRベースの統計情報を算出する。

    期待値 = (勝率 × 平均利益R) − (負率 × 平均損失R)

    Returns:
        {
            "total": int,
            "wins": int, "losses": int,
            "win_rate": float, "loss_rate": float,
            "total_pnl": float,
            "total_pnl_r": float,
            "avg_win_r": float, "avg_loss_r": float,
            "max_win_r": float, "max_loss_r": float,
            "expected_value_r": float,
            "profit_factor": float,
            "breakeven_winrate": float,
            "accuracy": str,
            "next_max_r": int,
            "next_lot_info": dict,
            "win_trades": list,
            "consecutive_wins": int,
            "consecutive_losses": int,
        }
    """
    config = load_config()
    r_unit = config.get("risk", {}).get("r_unit", 10000)

    if not trades:
        return _empty_stats()

    win_trades = [t for t in trades if t.get("result") == "win"]
    loss_trades = [t for t in trades if t.get("result") != "win"]

    total = len(trades)
    wins = len(win_trades)
    losses = len(loss_trades)
    win_rate = wins / total
    loss_rate = 1 - win_rate

    # R換算
    win_pnls_r = [abs(t.get("pnl", 0) or 0) / r_unit for t in win_trades]
    loss_pnls_r = [abs(t.get("pnl", 0) or 0) / r_unit for t in loss_trades]

    avg_win_r = sum(win_pnls_r) / len(win_pnls_r) if win_pnls_r else 0
    avg_loss_r = sum(loss_pnls_r) / len(loss_pnls_r) if loss_pnls_r else 0
    max_win_r = max(win_pnls_r) if win_pnls_r else 0
    max_loss_r = max(loss_pnls_r) if loss_pnls_r else 0

    # 期待値（Rベース）
    expected_value_r = (win_rate * avg_win_r) - (loss_rate * avg_loss_r)

    # PF
    total_win_r = sum(win_pnls_r)
    total_loss_r = sum(loss_pnls_r)
    profit_factor = total_win_r / total_loss_r if total_loss_r > 0 else float("inf")

    # 損益分岐勝率
    breakeven = avg_loss_r / (avg_win_r + avg_loss_r) if (avg_win_r + avg_loss_r) > 0 else 0

    # 連勝・連敗
    consec_w, consec_l = _calc_consecutive(trades)

    # 精度（サンプル数による信頼度）
    accuracy = _calc_accuracy(total)

    # 次回許容ロット算出
    next_max_r, next_lot_info = _calc_next_lot(expected_value_r, win_rate, total, config)

    total_pnl = sum(t.get("pnl", 0) or 0 for t in trades)

    return {
        "total": total,
        "wins": wins,
        "losses": losses,
        "win_rate": round(win_rate, 4),
        "loss_rate": round(loss_rate, 4),
        "total_pnl": round(total_pnl, 0),
        "total_pnl_r": round(total_pnl / r_unit, 2),
        "avg_win_r": round(avg_win_r, 2),
        "avg_loss_r": round(avg_loss_r, 2),
        "max_win_r": round(max_win_r, 2),
        "max_loss_r": round(max_loss_r, 2),
        "expected_value_r": round(expected_value_r, 2),
        "profit_factor": round(profit_factor, 2),
        "breakeven_winrate": round(breakeven, 4),
        "accuracy": accuracy,
        "next_max_r": next_max_r,
        "next_lot_info": next_lot_info,
        "win_trades": win_trades,
        "consecutive_wins": consec_w,
        "consecutive_losses": consec_l,
        "r_unit": r_unit,
    }


def _empty_stats() -> dict:
    return {
        "total": 0, "wins": 0, "losses": 0,
        "win_rate": 0, "loss_rate": 0,
        "total_pnl": 0, "total_pnl_r": 0,
        "avg_win_r": 0, "avg_loss_r": 0,
        "max_win_r": 0, "max_loss_r": 0,
        "expected_value_r": 0, "profit_factor": 0,
        "breakeven_winrate": 0,
        "accuracy": "データなし",
        "next_max_r": 1, "next_lot_info": {},
        "win_trades": [],
        "consecutive_wins": 0, "consecutive_losses": 0,
        "r_unit": 10000,
    }


def _calc_consecutive(trades: list[dict]) -> tuple[int, int]:
    """現在の連勝数・最大連敗数を算出"""
    max_consec_w = 0
    max_consec_l = 0
    current_w = 0
    current_l = 0

    for t in sorted(trades, key=lambda x: x.get("date", "")):
        if t.get("result") == "win":
            current_w += 1
            current_l = 0
            max_consec_w = max(max_consec_w, current_w)
        else:
            current_l += 1
            current_w = 0
            max_consec_l = max(max_consec_l, current_l)

    return max_consec_w, max_consec_l


def _calc_accuracy(total: int) -> str:
    """サンプル数から統計の信頼度を判定"""
    if total >= 100:
        return "高精度（100トレード以上）"
    elif total >= 50:
        return "中精度（50トレード以上）"
    elif total >= 20:
        return "低精度（20トレード以上）"
    elif total >= 5:
        return "参考値（5トレード以上）"
    else:
        return "データ不足（5トレード未満）"


def _calc_next_lot(ev_r: float, win_rate: float, total: int, config: dict) -> tuple[int, dict]:
    """期待値と勝率から次回許容R数を算出する。

    ルール:
      - EV > 0 かつ 精度が参考値以上 → 級の最大Rまで許容
      - EV > 0 だがデータ不足 → 最大Rの半分
      - EV <= 0 → 1R固定（最小リスク）
    """
    r_unit = config.get("risk", {}).get("r_unit", 10000)
    rules = config.get("grade_rules", {})

    ss_max = rules.get("SS", {}).get("max_r", 10)
    s_max = rules.get("S", {}).get("max_r", 5)
    a_max = rules.get("A", {}).get("max_r", 1)

    if ev_r <= 0:
        # 期待値マイナス → 1R固定
        return 1, {
            "SS": 1, "S": 1, "A": 1,
            "reason": "期待値マイナス → 全級1R制限",
        }

    if total < 5:
        # データ不足 → 半分
        return max(1, ss_max // 2), {
            "SS": max(1, ss_max // 2),
            "S": max(1, s_max // 2),
            "A": a_max,
            "reason": "データ不足 → 最大Rの半分に制限",
        }

    if total < 20:
        # 参考値 → 7割
        return max(1, int(ss_max * 0.7)), {
            "SS": max(1, int(ss_max * 0.7)),
            "S": max(1, int(s_max * 0.7)),
            "A": a_max,
            "reason": "参考値レベル → 最大Rの70%に制限",
        }

    # 十分なデータ → フル許容
    return ss_max, {
        "SS": ss_max,
        "S": s_max,
        "A": a_max,
        "reason": "期待値プラス＋十分なデータ → フルR許容",
    }


# ---------- エントリー分類別 勝率自動算出 ----------

def calc_entry_type_stats(trades: list[dict]) -> list[dict]:
    """エントリー分類ごとの勝率・期待値を算出する。

    Returns:
        [
            {
                "entry_type": str,
                "total": int,
                "wins": int,
                "losses": int,
                "win_rate": float,
                "total_pnl": float,
                "avg_pnl": float,
                "avg_win": float,
                "avg_loss": float,
                "expected_value": float,
                "profit_factor": float,
            },
            ...
        ]
    """
    config = load_config()
    entry_types = config.get("entry_types", [])

    # 分類ごとに集計
    stats_map = {}
    for et in entry_types:
        stats_map[et] = {"wins": [], "losses": []}

    for t in trades:
        et = t.get("entry_type", "")
        if et not in stats_map:
            stats_map[et] = {"wins": [], "losses": []}
        pnl = t.get("pnl", 0) or 0
        if t.get("result") == "win":
            stats_map[et]["wins"].append(pnl)
        else:
            stats_map[et]["losses"].append(abs(pnl))

    results = []
    for et in entry_types:
        data = stats_map.get(et, {"wins": [], "losses": []})
        wins = data["wins"]
        losses = data["losses"]
        total = len(wins) + len(losses)

        if total == 0:
            results.append({
                "entry_type": et,
                "total": 0, "wins": 0, "losses": 0,
                "win_rate": 0, "total_pnl": 0, "avg_pnl": 0,
                "avg_win": 0, "avg_loss": 0,
                "expected_value": 0, "profit_factor": 0,
            })
            continue

        win_rate = len(wins) / total
        avg_win = sum(wins) / len(wins) if wins else 0
        avg_loss = sum(losses) / len(losses) if losses else 0
        total_pnl = sum(wins) - sum(losses)
        avg_pnl = total_pnl / total

        ev = calc_expected_value(win_rate, avg_win, avg_loss)

        results.append({
            "entry_type": et,
            "total": total,
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": round(win_rate, 4),
            "total_pnl": round(total_pnl, 0),
            "avg_pnl": round(avg_pnl, 0),
            "avg_win": round(avg_win, 0),
            "avg_loss": round(avg_loss, 0),
            "expected_value": ev["expected_value"],
            "profit_factor": ev["profit_factor"],
        })

    return results


def calc_stop_reason_stats(trades: list[dict]) -> list[dict]:
    """出口戦略ごとの発生回数を集計する。"""
    reason_map = {
        "stop_osaedama": "抑え玉喰わない",
        "stop_itakyushu": "買い板吸収しない",
        "stop_itakieru": "買い板消える",
        "stop_fushi_noforce": "節目ブレイク後勢いなし",
        "stop_hamekomi": "買い板はめこみ",
        "stop_sashene_care": "指値ケア反応悪く下振り懸念",
        "stop_ita_yowaku": "買い板弱くなる",
        "stop_ue_kawanai": "上を買わなくなる",
        "stop_yakan_pts": "夜間PTS",
        "stop_mochikoshi": "持ち越し翌日売り",
        "stop_renkaiato": "連買後",
    }

    counts = {label: 0 for label in reason_map.values()}
    loss_trades = [t for t in trades if t.get("result") != "win"]
    total_losses = len(loss_trades)

    for t in loss_trades:
        for col, label in reason_map.items():
            if t.get(col):
                counts[label] += 1

    results = []
    for label, count in counts.items():
        results.append({
            "reason": label,
            "count": count,
            "ratio": round(count / total_losses, 4) if total_losses > 0 else 0,
        })

    return results


# ---------- 銘柄質別 勝率自動算出 ----------

def calc_quality_stats(trades: list[dict]) -> list[dict]:
    """銘柄質ごとの勝率・期待値を算出する。"""
    config = load_config()
    qualities = config.get("meigara_quality_options", [])

    stats_map = {}
    for q in qualities:
        stats_map[q] = {"wins": [], "losses": []}

    for t in trades:
        q = t.get("meigara_quality", "")
        if q not in stats_map:
            stats_map[q] = {"wins": [], "losses": []}
        pnl = t.get("pnl", 0) or 0
        if t.get("result") == "win":
            stats_map[q]["wins"].append(pnl)
        else:
            stats_map[q]["losses"].append(abs(pnl))

    results = []
    for q in qualities:
        data = stats_map.get(q, {"wins": [], "losses": []})
        wins = data["wins"]
        losses = data["losses"]
        total = len(wins) + len(losses)

        if total == 0:
            results.append({
                "quality": q,
                "total": 0, "wins": 0, "losses": 0,
                "win_rate": 0, "total_pnl": 0, "avg_pnl": 0,
                "avg_win": 0, "avg_loss": 0,
                "expected_value": 0, "profit_factor": 0,
            })
            continue

        win_rate = len(wins) / total
        avg_win = sum(wins) / len(wins) if wins else 0
        avg_loss = sum(losses) / len(losses) if losses else 0
        total_pnl = sum(wins) - sum(losses)
        avg_pnl = total_pnl / total

        ev = calc_expected_value(win_rate, avg_win, avg_loss)

        results.append({
            "quality": q,
            "total": total,
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": round(win_rate, 4),
            "total_pnl": round(total_pnl, 0),
            "avg_pnl": round(avg_pnl, 0),
            "avg_win": round(avg_win, 0),
            "avg_loss": round(avg_loss, 0),
            "expected_value": ev["expected_value"],
            "profit_factor": ev["profit_factor"],
        })

    return results
