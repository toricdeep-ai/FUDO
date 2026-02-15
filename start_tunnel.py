"""Cloudflare Tunnel to start and send URL to LINE."""

import re
import subprocess
import sys
import threading

from notifier import send_line


def watch_output(proc):
    """Read cloudflared stderr and send tunnel URL to LINE."""
    url_pattern = re.compile(r"https://[a-zA-Z0-9\-]+\.trycloudflare\.com")
    sent = False

    for line in proc.stderr:
        text = line.strip()
        if text:
            print(text)
        if not sent:
            match = url_pattern.search(text)
            if match:
                url = match.group(0)
                print(f"\n=== Tunnel URL: {url} ===")
                msg = f"FUDO\n{url}"
                if send_line(msg):
                    print("=== LINE sent ===")
                else:
                    print("=== LINE send failed ===")
                sent = True


def main():
    proc = subprocess.Popen(
        ["cloudflared", "tunnel", "--url", "http://localhost:8501"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    t = threading.Thread(target=watch_output, args=(proc,), daemon=True)
    t.start()

    try:
        proc.wait()
    except KeyboardInterrupt:
        proc.terminate()
        print("\nTunnel stopped.")


if __name__ == "__main__":
    main()
