"""FUDO - データベース管理モジュール"""

from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path

DB_PATH = Path(__file__).parent / "database.db"


def get_connection():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    """テーブルを初期化する（存在しなければ作成）"""
    conn = get_connection()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS watchlist (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            name TEXT NOT NULL,
            ticker TEXT NOT NULL,
            market_cap REAL,
            margin_buy_ratio REAL,
            fushi TEXT,
            pts_volume INTEGER,
            daily_disclosure_count INTEGER DEFAULT 0,
            hiduke_position_good INTEGER DEFAULT 0,
            teii_or_taishaku TEXT DEFAULT 'なし',
            meigara_quality TEXT,
            grade TEXT,
            max_r INTEGER,
            lot_strategy TEXT,
            memo TEXT,
            created_at TEXT DEFAULT (datetime('now','localtime')),
            updated_at TEXT DEFAULT (datetime('now','localtime'))
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_watchlist_date ON watchlist(date)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_watchlist_ticker ON watchlist(ticker)
    """)

    # --- トレード記録テーブル ---
    conn.execute("""
        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            name TEXT NOT NULL,
            ticker TEXT NOT NULL,
            grade TEXT,
            entry_type TEXT,
            entry_price REAL,
            exit_price REAL,
            lot INTEGER,
            pnl REAL DEFAULT 0,
            result TEXT DEFAULT 'lose',
            stop_osaedama INTEGER DEFAULT 0,
            stop_itakyushu INTEGER DEFAULT 0,
            stop_itakieru INTEGER DEFAULT 0,
            stop_fushi_noforce INTEGER DEFAULT 0,
            meigara_quality TEXT,
            memo TEXT,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_trades_date ON trades(date)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_trades_entry_type ON trades(entry_type)
    """)

    # --- 価格アラートテーブル ---
    # --- 適時開示テーブル ---
    conn.execute("""
        CREATE TABLE IF NOT EXISTS disclosures (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker TEXT NOT NULL,
            company_name TEXT,
            market TEXT,
            disclosure_type TEXT,
            title TEXT,
            url TEXT,
            disclosed_at TEXT,
            market_cap REAL,
            source TEXT,
            notified INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_disclosures_ticker ON disclosures(ticker)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_disclosures_disclosed_at ON disclosures(disclosed_at)
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS price_alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker TEXT NOT NULL,
            name TEXT NOT NULL,
            alert_type TEXT NOT NULL,
            target_price REAL,
            direction TEXT DEFAULT 'above',
            volume_ratio REAL DEFAULT 2.0,
            active INTEGER DEFAULT 1,
            triggered INTEGER DEFAULT 0,
            memo TEXT,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        )
    """)

    conn.commit()
    conn.close()


def add_stock(data: dict) -> int:
    """銘柄をウォッチリストに追加する"""
    conn = get_connection()
    cur = conn.execute("""
        INSERT INTO watchlist
            (date, name, ticker, market_cap, margin_buy_ratio, fushi,
             pts_volume, daily_disclosure_count, hiduke_position_good, teii_or_taishaku,
             meigara_quality, grade, max_r, lot_strategy, memo)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        data.get("date", str(date.today())),
        data["name"],
        data["ticker"],
        data.get("market_cap"),
        data.get("margin_buy_ratio"),
        data.get("fushi"),
        data.get("pts_volume"),
        data.get("daily_disclosure_count", 0),
        data.get("hiduke_position_good", 0),
        data.get("teii_or_taishaku", "なし"),
        data.get("meigara_quality"),
        data.get("grade"),
        data.get("max_r"),
        data.get("lot_strategy"),
        data.get("memo"),
    ))
    conn.commit()
    stock_id = cur.lastrowid
    conn.close()
    return stock_id


def update_stock(stock_id: int, data: dict):
    """銘柄情報を更新する"""
    fields = []
    values = []
    for key, val in data.items():
        if key in ("id", "created_at"):
            continue
        fields.append(f"{key} = ?")
        values.append(val)
    fields.append("updated_at = datetime('now','localtime')")
    values.append(stock_id)

    conn = get_connection()
    conn.execute(
        f"UPDATE watchlist SET {', '.join(fields)} WHERE id = ?",
        values,
    )
    conn.commit()
    conn.close()


def delete_stock(stock_id: int):
    """銘柄を削除する"""
    conn = get_connection()
    conn.execute("DELETE FROM watchlist WHERE id = ?", (stock_id,))
    conn.commit()
    conn.close()


def get_stocks(target_date: str = None) -> list[dict]:
    """銘柄一覧を取得する"""
    conn = get_connection()
    if target_date:
        rows = conn.execute(
            "SELECT * FROM watchlist WHERE date = ? ORDER BY id DESC", (target_date,)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM watchlist ORDER BY date DESC, id DESC"
        ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_stock_by_id(stock_id: int) -> dict | None:
    """IDで銘柄を取得する"""
    conn = get_connection()
    row = conn.execute("SELECT * FROM watchlist WHERE id = ?", (stock_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def get_stocks_by_ticker(ticker: str) -> list[dict]:
    """証券コードで銘柄履歴を取得する"""
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM watchlist WHERE ticker = ? ORDER BY date DESC", (ticker,)
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


# ========== トレード記録 ==========

def add_trade(data: dict) -> int:
    """トレード記録を追加する"""
    conn = get_connection()
    cur = conn.execute("""
        INSERT INTO trades
            (date, name, ticker, grade, entry_type, entry_price, exit_price,
             lot, pnl, result,
             stop_osaedama, stop_itakyushu, stop_itakieru, stop_fushi_noforce,
             meigara_quality, memo)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        data.get("date", str(date.today())),
        data["name"],
        data["ticker"],
        data.get("grade"),
        data.get("entry_type"),
        data.get("entry_price"),
        data.get("exit_price"),
        data.get("lot"),
        data.get("pnl", 0),
        data.get("result", "lose"),
        data.get("stop_osaedama", 0),
        data.get("stop_itakyushu", 0),
        data.get("stop_itakieru", 0),
        data.get("stop_fushi_noforce", 0),
        data.get("meigara_quality"),
        data.get("memo"),
    ))
    conn.commit()
    trade_id = cur.lastrowid
    conn.close()
    return trade_id


def get_trades(target_date: str = None) -> list[dict]:
    """トレード記録一覧を取得する"""
    conn = get_connection()
    if target_date:
        rows = conn.execute(
            "SELECT * FROM trades WHERE date = ? ORDER BY id DESC", (target_date,)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM trades ORDER BY date DESC, id DESC"
        ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_trades_by_entry_type(entry_type: str) -> list[dict]:
    """エントリー分類別にトレードを取得する"""
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM trades WHERE entry_type = ? ORDER BY date DESC", (entry_type,)
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def delete_trade(trade_id: int):
    """トレード記録を削除する"""
    conn = get_connection()
    conn.execute("DELETE FROM trades WHERE id = ?", (trade_id,))
    conn.commit()
    conn.close()


# ========== 価格アラート ==========

def add_price_alert(data: dict) -> int:
    """価格アラートを追加する"""
    conn = get_connection()
    cur = conn.execute("""
        INSERT INTO price_alerts
            (ticker, name, alert_type, target_price, direction, volume_ratio, memo)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        data["ticker"],
        data["name"],
        data.get("alert_type", "price"),
        data.get("target_price"),
        data.get("direction", "above"),
        data.get("volume_ratio", 2.0),
        data.get("memo"),
    ))
    conn.commit()
    alert_id = cur.lastrowid
    conn.close()
    return alert_id


def get_active_alerts() -> list[dict]:
    """有効なアラート一覧を取得する"""
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM price_alerts WHERE active = 1 ORDER BY id DESC"
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_all_alerts() -> list[dict]:
    """全アラートを取得する"""
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM price_alerts ORDER BY active DESC, id DESC"
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def trigger_alert(alert_id: int):
    """アラートを発火済みにする"""
    conn = get_connection()
    conn.execute(
        "UPDATE price_alerts SET triggered = 1, active = 0 WHERE id = ?", (alert_id,)
    )
    conn.commit()
    conn.close()


def delete_alert(alert_id: int):
    """アラートを削除する"""
    conn = get_connection()
    conn.execute("DELETE FROM price_alerts WHERE id = ?", (alert_id,))
    conn.commit()
    conn.close()


def deactivate_alert(alert_id: int):
    """アラートを無効化する"""
    conn = get_connection()
    conn.execute("UPDATE price_alerts SET active = 0 WHERE id = ?", (alert_id,))
    conn.commit()
    conn.close()


# ========== 適時開示 ==========

def add_disclosure(data: dict) -> int | None:
    """適時開示を追加する（重複チェック: ticker + title + disclosed_at）"""
    conn = get_connection()
    existing = conn.execute(
        "SELECT id FROM disclosures WHERE ticker = ? AND title = ? AND disclosed_at = ?",
        (data["ticker"], data.get("title", ""), data.get("disclosed_at", "")),
    ).fetchone()
    if existing:
        conn.close()
        return None

    cur = conn.execute("""
        INSERT INTO disclosures
            (ticker, company_name, market, disclosure_type, title, url,
             disclosed_at, market_cap, source, notified)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        data["ticker"],
        data.get("company_name", ""),
        data.get("market", ""),
        data.get("disclosure_type", ""),
        data.get("title", ""),
        data.get("url", ""),
        data.get("disclosed_at", ""),
        data.get("market_cap"),
        data.get("source", ""),
        0,
    ))
    conn.commit()
    disclosure_id = cur.lastrowid
    conn.close()
    return disclosure_id


def get_disclosures(source: str = None, target_date: str = None) -> list[dict]:
    """適時開示一覧を取得する"""
    conn = get_connection()
    query = "SELECT * FROM disclosures WHERE 1=1"
    params = []
    if source:
        query += " AND source = ?"
        params.append(source)
    if target_date:
        query += " AND disclosed_at LIKE ?"
        params.append(f"{target_date}%")
    query += " ORDER BY disclosed_at DESC, id DESC"
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_unnotified_disclosures() -> list[dict]:
    """未通知の適時開示を取得する"""
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM disclosures WHERE notified = 0 ORDER BY disclosed_at DESC"
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def mark_disclosure_notified(disclosure_id: int):
    """適時開示を通知済みにする"""
    conn = get_connection()
    conn.execute("UPDATE disclosures SET notified = 1 WHERE id = ?", (disclosure_id,))
    conn.commit()
    conn.close()


# 起動時にDB初期化
init_db()
