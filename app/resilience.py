"""
Resilience primitives — ported from
startup_prep/week4_sola/day21_resilient_llm_engineering/ex01_resilient_client.py.

AsyncTokenBucket, retry_with_backoff, and parse_llm_json are copied as-is —
you already built and validated these in Day 21, no need to redo that work.

CircuitBreaker is copied too, WITH THE SAME BUG your Day 21 version has:
record_failure() never increments failure_count (see the FIXME below). Fix
it here before you build on top of it — the whole point of Day 4's load
test is watching the breaker trip on cue, and it can't do that with this
bug in place.
"""
import asyncio
import json
import random
import re
import time
from enum import Enum
from typing import Optional


class RetryableAPIError(Exception):
    def __init__(self, message: str, retry_after: Optional[float] = None):
        super().__init__(message)
        self.retry_after = retry_after


class NonRetryableAPIError(Exception):
    pass


class AsyncTokenBucket:
    def __init__(self, rate: float, capacity: float):
        self.rate = rate
        self.capacity = capacity
        self.tokens = capacity
        self.last_refill = time.monotonic()
        self._lock = asyncio.Lock()

    def _refill(self):
        now = time.monotonic()
        elapsed = now - self.last_refill
        self.tokens = min(self.capacity, self.tokens + elapsed * self.rate)
        self.last_refill = now

    async def acquire(self, n: float = 1.0):
        while True:
            async with self._lock:
                self._refill()
                if self.tokens >= n:
                    self.tokens -= n
                    return
                deficit = n - self.tokens
                wait_time = deficit / self.rate
            await asyncio.sleep(wait_time)


async def retry_with_backoff(
    fn,
    max_attempts: int = 5,
    base_delay: float = 0.05,
    max_delay: float = 2.0,
):
    last_exception = None
    for attempt in range(max_attempts):
        try:
            return await fn()
        except NonRetryableAPIError:
            raise
        except RetryableAPIError as e:
            last_exception = e
            if attempt == max_attempts - 1:
                break
            if e.retry_after is not None:
                delay = e.retry_after
            else:
                delay = random.uniform(0, min(max_delay, base_delay * (2 ** attempt)))
            await asyncio.sleep(delay)
    raise last_exception


class CircuitState(Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreaker:
    def __init__(self, failure_threshold: int = 5, cooldown_seconds: float = 1.0):
        self.failure_threshold = failure_threshold
        self.cooldown_seconds = cooldown_seconds
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.opened_at: Optional[float] = None

    def allow_request(self) -> bool:
        if self.state == CircuitState.CLOSED:
            return True
        if self.state == CircuitState.OPEN:
            if time.monotonic() - self.opened_at >= self.cooldown_seconds:
                self.state = CircuitState.HALF_OPEN
                return True
            return False
        return True  # HALF_OPEN: allow the probe through

    def record_success(self):
        self.failure_count = 0
        self.state = CircuitState.CLOSED

    def record_failure(self):
        # FIXME (ported bug from Day 21 — fix this before Day 2):
        # `self.failure_count` alone is a no-op expression statement, it
        # doesn't increment anything. As written, failure_count stays 0
        # forever, so the CLOSED -> OPEN transition below can never fire
        # from a run of repeated failures — the breaker can currently only
        # open via a failed HALF_OPEN probe. It should read:
        #     self.failure_count += 1
        self.failure_count
        if self.state == CircuitState.HALF_OPEN:
            self.state = CircuitState.OPEN
            self.opened_at = time.monotonic()
        elif self.failure_count >= self.failure_threshold:
            self.state = CircuitState.OPEN
            self.opened_at = time.monotonic()


class ParseFailure(Exception):
    def __init__(self, raw_response: str, attempts_tried: list):
        self.raw_response = raw_response
        self.attempts_tried = attempts_tried
        super().__init__(f"Failed to parse after: {attempts_tried}")


def parse_llm_json(raw: str) -> dict:
    attempts = []

    attempts.append("direct")
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    attempts.append("strip_fences")
    fenced = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip())
    try:
        return json.loads(fenced)
    except json.JSONDecodeError:
        pass

    attempts.append("strip_trailing_commas")
    repaired = re.sub(r",(\s*[}\]])", r"\1", fenced)
    try:
        return json.loads(repaired)
    except json.JSONDecodeError:
        pass

    raise ParseFailure(raw, attempts)
