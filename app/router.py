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
from ast import parse
import time
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
from app.tracing import TraceStore
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

        # Per-backend, not shared — Day 21 qa_check.md Q5.
        self.primary_bucket = AsyncTokenBucket(rate=rate, capacity=capacity)
        self.fallback_bucket = AsyncTokenBucket(rate=rate, capacity=capacity)
        self.primary_breaker = CircuitBreaker(failure_threshold=failure_threshold, cooldown_seconds=cooldown_seconds)
        self.fallback_breaker = CircuitBreaker(failure_threshold=failure_threshold, cooldown_seconds=cooldown_seconds)

    async def generate(self, prompt: str) -> Dict[str, Any]:
        """
        TASK (Step 9 / Day 2) -- see the module docstring's TASK list above
        for the full spec. This orchestrates two attempts (primary, then
        fallback) via `_attempt_backend()` below, instead of duplicating
        the rate-limit -> circuit-check -> retry -> parse sequence twice
        inline. That sequence is exactly Day 21's ResilientLLMClient
        pattern for ONE backend -- you already built and proved it works;
        this router just reuses it twice with a fallback chain between the
        two calls. Writing it once and calling it twice also means a fix
        you make to the sequence can't accidentally apply to only one
        backend.

        Tracing (recording a GatewaySpan per attempt) is deliberately NOT
        part of this step -- that's Phase 4 / Step 12 of the runbook, once
        TraceStore.record() actually exists. Leave self.trace_store alone
        for now.
        """
        t0 = time.perf_counter()

        primary_exc = None

        try:
          result = await self._attempt_backend(
            self.primary, self.primary_bucket, self.primary_breaker, prompt
          )
          result["_served_by"] = self.primary.name
          result["_latency_ms"] = (time.perf_counter() - t0)*1000
          return result
        except Exception as e:
          primary_exc = e
        
        try:
          result = await self._attempt_backend(
            self.fallback, self.fallback_bucket, self.fallback_breaker, prompt
          )
          result["_served_by"] = self.fallback.name
          result["_latency_ms"] = (time.perf_counter() - t0)*1000
          return result
        except Exception as fallback_exc:
          raise RuntimeError(
            f"both backends failed: primary={primary_exc}, fallback={fallback_exc}"
          )


        # TODO 1 -- try the primary via self._attempt_backend(...).
        #   - On success: tag the returned dict with which backend served
        #     it (`_served_by`), total elapsed latency (`_latency_ms`,
        #     using t0 above), and how many retries fired. Return it.
        #   - On failure: catch whatever _attempt_backend raises. Do NOT
        #     re-raise yet -- fall through to TODO 2 instead.

        # TODO 2 -- try the fallback the same way.
        #   - On success: same tagging as above, but _served_by should
        #     read self.fallback.name instead.
        #   - On failure: nothing left to fall back to. Let it propagate
        #     up to main.py's `except Exception` handler.

        # raise NotImplementedError("TODO (Step 9): see comments above")

    async def _attempt_backend(
        self,
        backend: MockBackend,
        bucket: AsyncTokenBucket,
        breaker: CircuitBreaker,
        prompt: str,
    ) -> Dict[str, Any]:
        """
        One resilient attempt against ONE backend: rate-limit ->
        circuit-check -> retry -> parse. Called from generate() once for
        primary, once for fallback -- this is the "write it once" piece
        the docstring above is talking about.

        TODO, in the order the module docstring's TASK list gives (1 then
        2) -- but before you write it, decide for yourself whether that
        order is actually right. Rate-limiting *before* checking whether
        the circuit is even open means you might wait on / consume a
        token for a backend you're about to skip anyway. Is that fine, or
        would checking the circuit first (free, no waiting) and only then
        touching the rate limiter be better? Pick one, and be ready to
        explain why -- this is exactly the kind of ordering question that
        gets asked as a follow-up.

          1. `await bucket.acquire()` to respect the rate limit.
          2. Circuit check: if `breaker.allow_request()` is False, raise
             immediately -- the circuit is OPEN and hasn't hit its
             cooldown, so don't even attempt this backend. What should you
             raise here so the caller (generate()) can tell "circuit was
             open" apart from "retries were exhausted"? Your call -- a
             plain RuntimeError with a clear message is fine, or your own
             small exception class if you want generate() to branch on it.
          3. Call `retry_with_backoff(lambda: backend.call(prompt), ...)`
             wrapped in a try/except:
               - on success: `breaker.record_success()`, then
                 `parse_llm_json()` the raw string and return the parsed
                 dict.
               - on failure (retries exhausted -- RetryableAPIError or
                 ParseFailure bubbling out of retry_with_backoff):
                 `breaker.record_failure()`, then re-raise so generate()
                 knows this backend is done.

        One thing retry_with_backoff does NOT do: tell you how many
        attempts it took. If generate() needs a retry count for the
        response (see TODO 1/2 above), you'll need to track that
        yourself -- e.g. a small counter in a closure around the lambda
        you pass to retry_with_backoff, incremented every time it's
        actually called, then read after retry_with_backoff returns (or
        raises).
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
        except (NonRetryableAPIError, RetryableAPIError, ParseFailure):
          breaker.record_failure()
          raise

        return AttemptResult(
          output=output,
          retries=attempts-1,
          circuit_state=circuit_state_at_attempt,
          latency_ms=(time.perf_counter() - t0) *1000,
          cost_usd=backend.cost_per_call_usd
        )






