"""
ModelGateway — the naive version below is Day 1 of PLAN.md; layering in
resilience and tracing is Day 2/3, and IS THE PART YOU BUILD.

Mirrors Day 21's ResilientLLMClient, but wraps TWO backends instead of
one, with a fallback chain between them — this is cram-sheet code shape
1.2 (cost/latency-aware router), the most Sola-shaped thing you can be
asked to sketch cold, so write the upgrade from scratch rather than
adapting existing code wholesale.

__init__ is done (it's just wiring: one AsyncTokenBucket and one
CircuitBreaker PER BACKEND, not shared — see Day 21's qa_check.md Q5 for
why a shared/global breaker would defeat the point of having a fallback at
all).

generate() currently does the Day 1 "naive gateway": call the primary,
parse the JSON, return it — no rate limiting, no circuit check, no retry,
no fallback, no tracing. Confirm this works end to end (boot the app, hit
POST /gateway/generate a few times) before starting Day 2.

TASK (Day 2) — layer resilience into generate():
    1. Rate-limit against the primary's bucket before calling it.
    2. Check the primary's circuit breaker; if open, skip straight to the
       fallback (don't even attempt primary).
    3. Call `retry_with_backoff(lambda: self.primary.call(prompt))`.
       - on success: self.primary_breaker.record_success(), parse the
         JSON, return the result tagged with which backend served it
       - on failure (after retries exhausted): self.primary_breaker
         .record_failure(), fall through to the fallback — do NOT
         re-raise yet
    4. Try the fallback the same way (rate-limit -> circuit check ->
       retry -> parse), but if THIS also fails, raise — there's nowhere
       left to fall back to.
    5. The returned dict should include which backend served it and how
       many retries fired, not just the raw model output — that's the
       signal Day 3's dashboard reads.

TASK (Day 3) — record a GatewaySpan (app/tracing.py) for every attempt,
    success or failure, on both primary and fallback paths.

Follow-up questions to be ready for (from the cram sheet):
  - What's your total latency budget across primary retries + fallback
    retries? At what point does "try harder on primary" cost more than
    "just fall back sooner"?
  - How would you decide primary vs. fallback per REQUEST TYPE instead of
    always trying primary first (e.g. route planning/recovery-type calls
    straight to the more reliable backend)? You don't have to implement
    this, but you should be able to talk through it.
"""
import time
from typing import Any, Dict

from app.backends import MockBackend
from app.resilience import AsyncTokenBucket, CircuitBreaker, parse_llm_json  # noqa: F401 (bucket/breaker unused until Day 2)
from app.tracing import TraceStore


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

        # Per-backend, not shared — Day 21 qa_check.md Q5.
        self.primary_bucket = AsyncTokenBucket(rate=rate, capacity=capacity)
        self.fallback_bucket = AsyncTokenBucket(rate=rate, capacity=capacity)
        self.primary_breaker = CircuitBreaker(failure_threshold=failure_threshold, cooldown_seconds=cooldown_seconds)
        self.fallback_breaker = CircuitBreaker(failure_threshold=failure_threshold, cooldown_seconds=cooldown_seconds)

    async def generate(self, prompt: str) -> Dict[str, Any]:
        # --- Day 1 naive version — replace with the Day 2/3 shape from the
        #     module docstring once this baseline is confirmed working. ---
        t0 = time.perf_counter()
        raw = await self.primary.call(prompt)
        result = parse_llm_json(raw)
        result["_served_by"] = self.primary.name
        result["_latency_ms"] = (time.perf_counter() - t0) * 1000
        return result
