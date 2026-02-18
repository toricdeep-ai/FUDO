"""FUDO - Streamlit Cloud データ永続化モジュール

GitHub API を使って database.db をリポジトリに保存・復元する。
Streamlit Cloud のファイルシステムは揮発性のため、再起動時にDBが消える問題を解決する。

必要な設定（Streamlit Cloud の Settings → Secrets）:
  [github]
  token = "ghp_xxxxxxxxxxxx"   # GitHub Personal Access Token (repo権限)
  repo = "toricdeep-ai/FUDO"  # リポジトリ名
"""

from __future__ import annotations

import base64
import os
from pathlib import Path

import requests

DB_PATH = Path(__file__).parent / "database.db"
REMOTE_PATH = "_backup/database.db"


def _get_github_config() -> dict:
    """Streamlit secrets または環境変数から GitHub 設定を取得"""
    try:
        import streamlit as st
        gh = st.secrets.get("github", {})
        if gh:
            return {"token": gh.get("token", ""), "repo": gh.get("repo", "")}
    except Exception:
        pass
    return {
        "token": os.environ.get("GITHUB_TOKEN", ""),
        "repo": os.environ.get("GITHUB_REPO", ""),
    }


def _headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github.v3+json",
    }


def is_configured() -> bool:
    """GitHub 永続化が設定済みか"""
    cfg = _get_github_config()
    return bool(cfg.get("token")) and bool(cfg.get("repo"))


def backup_db() -> bool:
    """database.db を GitHub リポジトリにアップロードする"""
    cfg = _get_github_config()
    token = cfg.get("token", "")
    repo = cfg.get("repo", "")
    if not token or not repo:
        return False

    if not DB_PATH.exists():
        return False

    try:
        content = DB_PATH.read_bytes()
        encoded = base64.b64encode(content).decode("ascii")

        url = f"https://api.github.com/repos/{repo}/contents/{REMOTE_PATH}"

        # 既存ファイルの sha を取得（更新時に必要）
        sha = None
        resp = requests.get(url, headers=_headers(token), timeout=15)
        if resp.status_code == 200:
            sha = resp.json().get("sha")

        payload = {
            "message": "auto: database backup",
            "content": encoded,
        }
        if sha:
            payload["sha"] = sha

        resp = requests.put(url, headers=_headers(token), json=payload, timeout=30)
        if resp.status_code in (200, 201):
            print("[CloudStorage] backup OK")
            return True
        else:
            print(f"[CloudStorage] backup failed: {resp.status_code}")
            return False
    except Exception as e:
        print(f"[CloudStorage] backup error: {e}")
        return False


def restore_db() -> bool:
    """GitHub リポジトリから database.db をダウンロードして復元する。
    ローカルDBが空（テーブルにデータ無し）の場合のみ復元する。
    """
    cfg = _get_github_config()
    token = cfg.get("token", "")
    repo = cfg.get("repo", "")
    if not token or not repo:
        return False

    # ローカルDBにデータがある場合はスキップ
    if _local_db_has_data():
        print("[CloudStorage] local DB has data, skip restore")
        return False

    try:
        url = f"https://api.github.com/repos/{repo}/contents/{REMOTE_PATH}"
        resp = requests.get(url, headers=_headers(token), timeout=15)
        if resp.status_code != 200:
            print(f"[CloudStorage] no remote backup found: {resp.status_code}")
            return False

        data = resp.json()
        content = base64.b64decode(data["content"])

        DB_PATH.write_bytes(content)
        print("[CloudStorage] restore OK")
        return True
    except Exception as e:
        print(f"[CloudStorage] restore error: {e}")
        return False


def _local_db_has_data() -> bool:
    """ローカルDBにウォッチリストまたはトレードデータがあるか"""
    if not DB_PATH.exists():
        return False
    try:
        import sqlite3
        conn = sqlite3.connect(str(DB_PATH))
        try:
            row = conn.execute("SELECT COUNT(*) FROM watchlist").fetchone()
            if row and row[0] > 0:
                conn.close()
                return True
        except Exception:
            pass
        try:
            row = conn.execute("SELECT COUNT(*) FROM trades").fetchone()
            if row and row[0] > 0:
                conn.close()
                return True
        except Exception:
            pass
        conn.close()
        return False
    except Exception:
        return False
