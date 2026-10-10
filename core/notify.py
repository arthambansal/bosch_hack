"""Best-effort Discord alerts. No queue, retries, logging, or embedded secrets.

The rate limit is process-local. In-flight calls and attempts less than two
seconds apart are dropped, including when the preceding attempt failed.
"""
import os
import threading
import time

import requests

_COLORS = {
    "kill_switch": 0xE74C3C,
    "gray_failure": 0xE74C3C,
    "fix_verified": 0x2ECC71,
    "fix_rolled_back": 0xE67E22,
    "fix_rollback_failed": 0xE74C3C,
    "root_cause": 0x3498DB,
    "mystery_reveal": 0x3498DB,
    "report": 0x3498DB,
}
_LOCK = threading.Lock()
_last_attempt = None


def notify(kind: str, title: str, text: str, fields: dict | None = None) -> bool:
    """Send an allowed alert; return only verified HTTP success, never raise."""
    acquired = False
    try:
        url = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()
        if not url or kind not in _COLORS:
            return False

        def clean(value, limit):
            # Avoid accidentally including this credential in operator content.
            return str(value).replace(url, "[redacted]")[:limit]

        embed = {
            "title": clean(title, 256) or "ChaosPilot",
            "description": clean(text, 4096),
            "color": _COLORS[kind],
            "fields": [{"name": "Event kind", "value": kind, "inline": True}],
        }
        # Discord allows 25 fields and 6000 aggregate embed characters.
        budget = 6000 - len(embed["title"]) - len(embed["description"]) - len("Event kind") - len(kind)
        if fields is not None:
            if not isinstance(fields, dict):
                return False
            for name, value in fields.items():
                if len(embed["fields"]) >= 25 or budget < 2:
                    break
                name_limit = min(256, budget - 1)
                name = (clean(name, name_limit) or "Field")[:name_limit]
                budget -= len(name)
                value_limit = min(1024, budget)
                value = (clean(value, value_limit) or "Not available")[:value_limit]
                if len(value) > budget:
                    break
                embed["fields"].append({"name": name, "value": value, "inline": False})
                budget -= len(value)

        acquired = _LOCK.acquire(blocking=False)
        if not acquired:
            return False
        global _last_attempt
        now = time.monotonic()
        if _last_attempt is not None and now - _last_attempt < 2:
            return False
        _last_attempt = now
        # Do not follow redirects or retry: the webhook credential stays at the
        # configured destination. Disable mentions in all operator-supplied text.
        response = requests.post(url, json={"embeds": [embed], "allowed_mentions": {"parse": []}},
                                 timeout=3, allow_redirects=False)
        return 200 <= response.status_code < 300
    except Exception:
        # Exception text may contain the webhook; never stringify or log it.
        return False
    finally:
        if acquired:
            _LOCK.release()
