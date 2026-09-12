"""
agent-hub/rate_limit.py
-----------------------
RailSense AI — Per-Agent Rate Limiter & Flood Protection.

Purpose:
Protects the Central Agent Communication Hub and downstream destination agents
from high-frequency request bursts and flood loops sent by any single authenticated agent.

Architectural Boundary:
- This is strictly TRANSPORT LAYER flood protection.
- It returns HTTP 429 Too Many Requests when limits are exceeded.
- It does NOT perform fraud detection or ML-based anomaly detection
  (which is the dedicated responsibility of the Security & Fraud Agent).

Distributed Deployment Note:
This implementation utilizes an in-memory thread-safe sliding window suitable
for single-process prototypes. For distributed multi-replica deployments,
a shared backing store such as Redis (using sliding window sorted sets or token buckets)
would be required.
"""

from __future__ import annotations

import os
import threading
import time
from collections import deque
from typing import Any


class AgentRateLimiter:
    """
    Thread-safe sliding-window rate limiter keyed by authenticated sender_agent.

    Enforces dual sliding windows:
    1. Per-second burst limit (default: 5 requests / second)
    2. Per-minute aggregate limit (default: 30 requests / minute)
    """

    def __init__(
        self,
        rate_limit_per_second: int | None = None,
        rate_limit_per_minute: int | None = None,
    ) -> None:
        self._default_per_second = rate_limit_per_second
        self._default_per_minute = rate_limit_per_minute
        self._lock = threading.Lock()
        self._history: dict[str, deque[float]] = {}

    @property
    def limit_per_second(self) -> int:
        if self._default_per_second is not None:
            return self._default_per_second
        try:
            return int(os.getenv("RATE_LIMIT_PER_SECOND", "5"))
        except ValueError:
            return 5

    @limit_per_second.setter
    def limit_per_second(self, value: int) -> None:
        self._default_per_second = value

    @property
    def limit_per_minute(self) -> int:
        if self._default_per_minute is not None:
            return self._default_per_minute
        try:
            return int(os.getenv("RATE_LIMIT_PER_MINUTE", "30"))
        except ValueError:
            return 30

    @limit_per_minute.setter
    def limit_per_minute(self, value: int) -> None:
        self._default_per_minute = value

    def is_allowed(
        self,
        sender_agent: str,
        current_time: float | None = None,
    ) -> bool:
        """
        Check whether an incoming request from sender_agent is allowed.

        Returns True if within rate limits (and records the request timestamp).
        Returns False if either the per-second or per-minute limit has been reached.
        """
        if not sender_agent:
            return False

        now = current_time if current_time is not None else time.monotonic()
        per_sec_limit = self.limit_per_second
        per_min_limit = self.limit_per_minute

        with self._lock:
            if sender_agent not in self._history:
                self._history[sender_agent] = deque()

            timestamps = self._history[sender_agent]

            # 1. Purge entries older than the 60-second window
            min_cutoff = now - 60.0
            while timestamps and timestamps[0] <= min_cutoff:
                timestamps.popleft()

            # 2. Count entries in the 1-second window
            sec_cutoff = now - 1.0
            sec_count = 0
            for ts in reversed(timestamps):
                if ts > sec_cutoff:
                    sec_count += 1
                else:
                    break

            # 3. Check boundaries
            if sec_count >= per_sec_limit:
                return False

            if len(timestamps) >= per_min_limit:
                return False

            # 4. Record request timestamp
            timestamps.append(now)
            return True

    def reset(self) -> None:
        """Reset all rate limit tracking state (useful for tests)."""
        with self._lock:
            self._history.clear()

    def get_stats(self, sender_agent: str) -> dict[str, Any]:
        """Return diagnostic counters for a given agent."""
        now = time.monotonic()
        with self._lock:
            timestamps = self._history.get(sender_agent, deque())
            sec_cutoff = now - 1.0
            sec_count = sum(1 for ts in timestamps if ts > sec_cutoff)
            return {
                "sender_agent": sender_agent,
                "current_second_count": sec_count,
                "limit_per_second": self.limit_per_second,
                "current_minute_count": len(timestamps),
                "limit_per_minute": self.limit_per_minute,
            }


# Global singleton instance for application use
rate_limiter = AgentRateLimiter()
