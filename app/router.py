"""
ModelGateway — routes each request to a primary backend, falling back to
a secondary backend on failure.

Wraps two independent backends, each behind its own rate limiter and
circuit breaker (see __init__): a request first tries `primary`, and only
reaches `fallback` if the primary attempt raises after exhausting its
retry budget or its circuit is open. Every attempt — success or failure,
on either backend — is recorded as a GatewaySpan (app/tracing.py) so the
whole routing/retry/failover history is visible after the fact.
"""
import time
import uuid
from typing import Any, Dict

from app.backends import MockBackend
from app.resilience import (
    AsyncTokenBucket,
    CircuitBreaker,
    NonRetryableAPIError,
    ParseFailure,
    RetryableAPIError,
    parse_llm_json,
    retry_with_backoff,
)
from app.tracing import TraceStore, GatewaySpan
from dataclasses import dataclass

@dataclass
class AttemptResult:
  output: Dict[str, Any]
  retries: int
  circuit_state: str
  latency_ms: float
  cost_usd: float


class ModelGateway:
    def __init__(
        self,
        primary: MockBackend,
        fallback: MockBackend,
        trace_store: TraceStore,
        rate: float = 20.0,
        capacity: float = 5.0,
        failure_threshold: int = 5,
        cooldown_seconds: float = 2.0,
    ):
        self.primary = primary
        self.fallback = fallback
        self.trace_store = trace_store

        # Per-backend, not shared: a shared breaker would mean one
        # backend's failures could trip the circuit for the other,
        # defeating the point of having a fallback at all.
        self.primary_bucket = AsyncTokenBucket(rate=rate, capacity=capacity)
        self.fallback_bucket = AsyncTokenBucket(rate=rate, capacity=capacity)
        self.primary_breaker = CircuitBreaker(failure_threshold=failure_threshold, cooldown_seconds=cooldown_seconds)
        self.fallback_breaker = CircuitBreaker(failure_threshold=failure_threshold, cooldown_seconds=cooldown_seconds)

    async def generate(self, prompt: str) -> Dict[str, Any]:
        """
        Try the primary backend via `_attempt_backend()`; on any failure,
        fall back to the secondary the same way. Both attempts share one
        `trace_id` so a span from primary and a span from its fallback (if
        any) can be tied back to the same logical request.

        Writing the rate-limit -> circuit-check -> retry -> parse sequence
        once in `_attempt_backend()` and calling it twice (rather than
        duplicating it inline for primary and fallback) means a fix to
        that sequence can't accidentally apply to only one backend.
        """
        t0 = time.perf_counter()
        trace_id = str(uuid.uuid4())

        primary_exc = None

        try:
          attempt = await self._attempt_backend(
            self.primary, self.primary_bucket, self.primary_breaker, prompt, trace_id
          )
          result = attempt.output
          result["_served_by"] = self.primary.name
          result["_retries"] = attempt.retries
          result["_latency_ms"] = (time.perf_counter() - t0)*1000
          return result
        except Exception as e:
          primary_exc = e

        try:
          attempt = await self._attempt_backend(
            self.fallback, self.fallback_bucket, self.fallback_breaker, prompt, trace_id
          )
          result = attempt.output
          result["_served_by"] = self.fallback.name
          result["_retries"] = attempt.retries
          result["_latency_ms"] = (time.perf_counter() - t0)*1000
          return result
        except Exception as fallback_exc:
          raise RuntimeError(
            f"both backends failed: primary={primary_exc}, fallback={fallback_exc}"
          )

    async def _attempt_backend(
        self,
        backend: MockBackend,
        bucket: AsyncTokenBucket,
        breaker: CircuitBreaker,
        prompt: str,
        trace_id: str
    ) -> AttemptResult:
        """
        One resilient attempt against a single backend: rate-limit ->
        circuit-check -> retry -> parse. Called from generate() once for
        the primary, once for the fallback.

        Rate-limiting runs before the circuit check, ahead of knowing
        whether the circuit is even open. The alternative — circuit check
        first, rate limiter only if that passes — avoids consuming a token
        for a backend that's about to be skipped anyway; this ordering
        instead keeps the two checks independent of each other, at the
        cost of occasionally waiting on a token for a backend that turns
        out to be circuit-open. Either is defensible.

        `retry_with_backoff` doesn't report how many attempts it took, so
        `call_and_count()` wraps the backend call in a closure counter
        that's read after `retry_with_backoff` returns (or raises) to
        populate `retries` on both the success span and the failure span.
        """

        t0 = time.perf_counter()

        await bucket.acquire()

        if not breaker.allow_request():
          raise RuntimeError("circuit open")

        circuit_state_at_attempt = breaker.state.value

        attempts = 0

        async def call_and_count():
          nonlocal attempts
          attempts += 1
          return await backend.call(prompt)

        try:
          raw = await retry_with_backoff(call_and_count)
          output = parse_llm_json(raw)
          breaker.record_success()
        except (NonRetryableAPIError, RetryableAPIError, ParseFailure) as e:
          breaker.record_failure()
          self.trace_store.record(GatewaySpan(
            trace_id=trace_id,
            backend=backend.name,
            success=False,
            latency_ms=(time.perf_counter()-t0)*1000,
            retries=attempts-1,
            circuit_state=circuit_state_at_attempt,
            timestamp=time.time(),
            cost_usd=backend.cost_per_call_usd,
            error=str(e)

          ))

          raise

        span = GatewaySpan(
            trace_id=trace_id,
            backend=backend.name,
            success=True,
            latency_ms=(time.perf_counter()-t0)*1000,
            retries=attempts-1,
            circuit_state=circuit_state_at_attempt,
            timestamp=time.time(),
            cost_usd=backend.cost_per_call_usd
        )

        self.trace_store.record(span)

        return AttemptResult(
          output=output,
          retries=attempts-1,
          circuit_state=circuit_state_at_attempt,
          latency_ms=(time.perf_counter() - t0) *1000,
          cost_usd=backend.cost_per_call_usd
        )
