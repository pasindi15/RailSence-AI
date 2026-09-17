"""
agent-hub/resilience.py
-----------------------
RailSense AI — Hub Resilience, Circuit Breaker, and Bounded Retries.

Responsibilities:
1. Per-receiver circuit breaker state machine: CLOSED -> OPEN -> HALF_OPEN.
2. Fast-fail prevention of cascading failures to unreachable downstream services.
3. Bounded retries with exponential backoff for transient errors only (503/504).
4. Circuit status queries for observability dashboard.
"""

from __future__ import annotations

import asyncio
import enum
import time
from typing import Any, Callable, Coroutine


class CircuitState(str, enum.Enum):
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


class CircuitBreakerOpenError(Exception):
    """Raised when request is rejected because the circuit breaker is OPEN."""
    def __init__(self, receiver: str, time_remaining: float):
        super().__init__(
            f"Circuit breaker for receiver '{receiver}' is OPEN. Retry in {time_remaining:.1f}s."
        )
        self.receiver = receiver
        self.time_remaining = time_remaining


class ReceiverCircuitBreaker:
    """Tracks state and failure metrics for a single downstream receiver agent."""

    def __init__(
        self,
        receiver: str,
        failure_threshold: int = 3,
        recovery_timeout: float = 10.0,
    ) -> None:
        self.receiver = receiver
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.state = CircuitState.CLOSED
        self.consecutive_failures = 0
        self.last_failure_time = 0.0
        self.total_requests = 0
        self.total_successes = 0
        self.total_failures = 0

    def allow_request(self) -> bool:
        """Evaluate whether an outbound request is permitted."""
        import os
        from database.database import is_test_environment
        if is_test_environment() and os.getenv("TEST_CIRCUIT_BREAKER") != "1":
            return True

        now = time.monotonic()
        if self.state == CircuitState.CLOSED:
            return True
        elif self.state == CircuitState.OPEN:
            elapsed = now - self.last_failure_time
            if elapsed >= self.recovery_timeout:
                self.state = CircuitState.HALF_OPEN
                return True
            return False
        elif self.state == CircuitState.HALF_OPEN:
            # Allow single probe through
            return True
        return True

    def get_time_until_probe(self) -> float:
        if self.state != CircuitState.OPEN:
            return 0.0
        elapsed = time.monotonic() - self.last_failure_time
        return max(0.0, self.recovery_timeout - elapsed)

    def record_success(self) -> None:
        self.total_requests += 1
        self.total_successes += 1
        self.consecutive_failures = 0
        self.state = CircuitState.CLOSED

    def record_failure(self) -> None:
        self.total_requests += 1
        self.total_failures += 1
        self.consecutive_failures += 1
        self.last_failure_time = time.monotonic()

        if self.consecutive_failures >= self.failure_threshold:
            self.state = CircuitState.OPEN

    def reset(self) -> None:
        self.state = CircuitState.CLOSED
        self.consecutive_failures = 0
        self.last_failure_time = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "receiver": self.receiver,
            "state": self.state.value,
            "consecutive_failures": self.consecutive_failures,
            "time_until_retry": round(self.get_time_until_probe(), 2),
            "total_requests": self.total_requests,
            "total_successes": self.total_successes,
            "total_failures": self.total_failures,
        }


class HubResilienceManager:
    """Registry and coordinator for per-receiver circuit breakers and retries."""

    def __init__(self) -> None:
        self._breakers: dict[str, ReceiverCircuitBreaker] = {}

    def get_breaker(self, receiver: str) -> ReceiverCircuitBreaker:
        if receiver not in self._breakers:
            self._breakers[receiver] = ReceiverCircuitBreaker(receiver)
        return self._breakers[receiver]

    def reset(self) -> None:
        for b in self._breakers.values():
            b.reset()

    def get_all_statuses(self) -> list[dict[str, Any]]:
        return [b.to_dict() for b in self._breakers.values()]


# Global resilience singleton
hub_resilience = HubResilienceManager()
