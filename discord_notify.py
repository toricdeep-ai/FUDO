"""FUDO - Discord Webhook notification module."""

import json
import requests
from analytics import load_config


def _get_discord_config() -> dict:
    config = load_config()
    return config.get("discord", {})


def send_discord(message: str) -> bool:
    """Send a message via Discord Webhook.

    Returns:
        True: success / False: failure
    """
    cfg = _get_discord_config()
    url = cfg.get("webhook_url", "")

    if not url:
        print("[Discord] webhook_url not set.")
        return False

    payload = {"content": message}

    try:
        resp = requests.post(
            url, json=payload, timeout=10,
        )
        if resp.status_code in (200, 204):
            print("[Discord] sent")
            return True
        else:
            print(f"[Discord] failed: {resp.status_code} {resp.text}")
            return False
    except requests.RequestException as e:
        print(f"[Discord] error: {e}")
        return False


def send_discord_embed(title: str, description: str, color: int = 0x00BFFF) -> bool:
    """Send a rich embed message via Discord Webhook."""
    cfg = _get_discord_config()
    url = cfg.get("webhook_url", "")

    if not url:
        print("[Discord] webhook_url not set.")
        return False

    payload = {
        "embeds": [{
            "title": title,
            "description": description,
            "color": color,
        }]
    }

    try:
        resp = requests.post(
            url, json=payload, timeout=10,
        )
        if resp.status_code in (200, 204):
            print("[Discord] embed sent")
            return True
        else:
            print(f"[Discord] embed failed: {resp.status_code} {resp.text}")
            return False
    except requests.RequestException as e:
        print(f"[Discord] error: {e}")
        return False
