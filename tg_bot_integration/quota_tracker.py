"""
quota_tracker.py — Tracks usage per AI platform, enables adaptive routing.

DROP THIS FILE into your claude-tg-bot/ directory.

Knows each platform's rate limits. When one is exhausted, the dispatcher
automatically routes to the next available platform. When the cooldown
expires, it comes back online.

State persists to disk — survives bot restarts.
Self-adjusts: if you hit a rate limit sooner than expected, it lowers
the estimate for next time.
"""

import json
import time
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# ─── Default Platform Quotas ────────────────────────────────────────────────
# Adjust these based on your actual subscription tiers.
# The tracker will auto-adjust down if you hit limits sooner.

PLATFORM_QUOTAS = {
    "claude_web": {
        "max_per_window": 100,       # ~100 Sonnet messages
        "window_hours": 5,           # per 5 hours
        "priority": 8,               # Higher = preferred
    },
    "claude_code": {
        "max_per_window": 50,
        "window_hours": 5,
        "priority": 10,
    },
    "gpt": {
        "max_per_window": 80,        # GPT-4o Plus
        "window_hours": 3,
        "priority": 5,
    },
    "grok": {
        "max_per_window": 30,        # Grok free tier
        "window_hours": 2,
        "priority": 3,
    },
    # Claude CLI (Bridge mode) — track this too
    "claude_cli": {
        "max_per_window": 200,       # Plan token generous limit
        "window_hours": 5,
        "priority": 9,
    },
}

STATE_FILE = Path(__file__).parent / ".harness_quota.json"


class QuotaTracker:
    """Tracks usage and manages adaptive routing across platforms."""

    def __init__(self):
        self.quotas = {k: dict(v) for k, v in PLATFORM_QUOTAS.items()}
        self.usage: dict[str, list[float]] = {p: [] for p in self.quotas}
        self.cooldown_until: dict[str, float] = {p: 0 for p in self.quotas}
        self._load()

    # ── Record & Query ────────────────────────────────────────────────────

    def record(self, platform: str, rate_limited: bool = False):
        """Record that we used a platform. Call after every interaction."""
        if platform not in self.quotas:
            return

        self.usage.setdefault(platform, []).append(time.time())

        if rate_limited:
            self._handle_rate_limit(platform)

        self._cleanup()
        self._save()

    def is_available(self, platform: str) -> bool:
        """Is this platform available right now?"""
        if platform not in self.quotas:
            return False
        if time.time() < self.cooldown_until.get(platform, 0):
            return False
        return self.remaining(platform) > 0

    def remaining(self, platform: str) -> int:
        """Messages remaining in current window."""
        if platform not in self.quotas:
            return 0
        q = self.quotas[platform]
        window_start = time.time() - (q["window_hours"] * 3600)
        used = len([t for t in self.usage.get(platform, []) if t >= window_start])
        return max(0, q["max_per_window"] - used)

    def time_until_available(self, platform: str) -> float:
        """Seconds until platform becomes available. 0 if available now."""
        cd = self.cooldown_until.get(platform, 0) - time.time()
        if cd > 0:
            return cd

        if self.remaining(platform) <= 0:
            q = self.quotas[platform]
            window_start = time.time() - (q["window_hours"] * 3600)
            timestamps = sorted([t for t in self.usage.get(platform, []) if t >= window_start])
            if timestamps:
                return timestamps[0] + (q["window_hours"] * 3600) - time.time()

        return 0

    def next_available_in(self) -> float:
        """Seconds until ANY platform becomes available."""
        times = [self.time_until_available(p) for p in self.quotas]
        return min(t for t in times if t > 0) if any(t > 0 for t in times) else 0

    # ── Adaptive Routing ──────────────────────────────────────────────────

    def get_best_available(self) -> str | None:
        """Get highest-priority available platform."""
        available = [
            (p, self.quotas[p]["priority"])
            for p in self.quotas
            if self.is_available(p)
        ]
        if not available:
            return None
        return max(available, key=lambda x: x[1])[0]

    def get_all_available(self) -> list[str]:
        """All available platforms sorted by priority."""
        available = [p for p in self.quotas if self.is_available(p)]
        return sorted(available, key=lambda p: -self.quotas[p]["priority"])

    def get_all_exhausted(self) -> list[str]:
        """All exhausted platforms."""
        return [p for p in self.quotas if not self.is_available(p)]

    # ── Status Report ─────────────────────────────────────────────────────

    def status_report(self) -> str:
        """Human-readable quota status for Telegram."""
        lines = ["📊 平台用量"]
        lines.append("─" * 30)

        for name in sorted(self.quotas, key=lambda p: -self.quotas[p]["priority"]):
            q = self.quotas[name]
            rem = self.remaining(name)
            total = q["max_per_window"]
            pct = (total - rem) / total if total > 0 else 0

            # Visual bar
            filled = int(pct * 10)
            bar = "█" * filled + "░" * (10 - filled)

            status = "✅" if self.is_available(name) else "⏳"
            line = f"{status} {name:12s} [{bar}] {rem}/{total}"

            cd = self.time_until_available(name)
            if cd > 0:
                line += f"  ({int(cd/60)}m)"

            lines.append(line)

        return "\n".join(lines)

    # ── Internal ──────────────────────────────────────────────────────────

    def _handle_rate_limit(self, platform: str):
        """Enter cooldown when rate limited."""
        q = self.quotas[platform]
        cooldown = q["window_hours"] * 3600
        self.cooldown_until[platform] = time.time() + cooldown
        logger.warning(f"[{platform}] Rate limited → cooldown {q['window_hours']}h")

        # Adaptive: lower estimate if hit sooner than expected
        window_start = time.time() - (q["window_hours"] * 3600)
        actual_used = len([t for t in self.usage.get(platform, []) if t >= window_start])
        if actual_used < q["max_per_window"]:
            old = q["max_per_window"]
            q["max_per_window"] = max(1, actual_used - 1)
            logger.info(f"[{platform}] Adjusted: {old} → {q['max_per_window']}")

    def _cleanup(self):
        """Remove old records."""
        max_window = max(q["window_hours"] for q in self.quotas.values()) * 3600
        cutoff = time.time() - (max_window * 2)
        for p in self.usage:
            self.usage[p] = [t for t in self.usage[p] if t >= cutoff]

    def _save(self):
        try:
            data = {
                "usage": self.usage,
                "cooldown_until": self.cooldown_until,
                "adjusted": {k: v["max_per_window"] for k, v in self.quotas.items()},
                "saved_at": time.time(),
            }
            STATE_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception as e:
            logger.warning(f"Failed to save quota state: {e}")

    def _load(self):
        if not STATE_FILE.exists():
            return
        try:
            data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
            self.usage = {k: v for k, v in data.get("usage", {}).items() if k in self.quotas}
            self.cooldown_until = {k: v for k, v in data.get("cooldown_until", {}).items() if k in self.quotas}
            for k, v in data.get("adjusted", {}).items():
                if k in self.quotas:
                    self.quotas[k]["max_per_window"] = v
            self._cleanup()
            logger.info("Quota state loaded from disk")
        except Exception as e:
            logger.warning(f"Failed to load quota state: {e}")
