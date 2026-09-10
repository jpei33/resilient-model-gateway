# Resilient Model Gateway

A gateway that fronts two model backends — a fast/cheap "self-hosted" one
and a slower/pricier/more-reliable "API provider" one — with a full
production resilience stack (per-backend circuit breakers, retry with
full-jitter backoff, client-side rate limiting, fallback routing) and
observability to match. Load-tested to show it degrades gracefully — and
recovers — when the primary backend goes down.

Built to work through the reliability patterns that matter for serving LLM
traffic in production: what happens when a backend gets flaky, how you
detect it without paging a human, and how you prove — with a chart, not a
claim — that failover actually works.

## Architecture

See [`docs/architecture.md`](docs/architecture.md) for the full request-flow
diagram (Mermaid, with a text fallback) and the design notes behind it —
including why the rate limiter/circuit breaker/retry stack is duplicated
per backend rather than shared, and a couple of tracing gaps worth knowing
about going in. Prefer a rendered picture over reading Mermaid source?
[`docs/architecture.html`](docs/architecture.html) has the same diagram
pre-rendered as an image, alongside the same design notes.

Two mock backends behind a FastAPI service, each independently rate-limited
and circuit-broken. The gateway tries the primary first; on a retried-out
failure or an open circuit, it falls back to the secondary. Every attempt
is traced (which backend, how many retries, circuit state at request time,
latency, cost) so failure and recovery are visible after the fact, not just
inferred.

## Status

Built and load-tested end to end: naive baseline confirmed, the full
per-backend resilience stack (rate limiting, circuit breaker, retry with
backoff, fallback routing) implemented and exercised via `/admin/degrade` +
`/admin/restore`, tracing wired into every attempt and surfaced through
`/admin/status`, and a load test with mid-run failure injection producing
the before/during/after chart at
[`docs/failover_chart.png`](docs/failover_chart.png). See
[PLAN.md](PLAN.md) for the day-by-day build log.

## Setup

```
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Once running:

```
curl -X POST http://127.0.0.1:8000/gateway/generate \
  -H "Content-Type: application/json" \
  -d '{"prompt": "hello"}'

# simulate the primary backend going down:
curl -X POST http://127.0.0.1:8000/admin/degrade/self_hosted
curl -X POST http://127.0.0.1:8000/admin/restore/self_hosted
```

## Load test

```
python scripts/load_test.py
python scripts/inspect_snapshots.py   # print self_hosted's circuit_state/latency trajectory
python scripts/plot_load_test.py      # regenerate docs/failover_chart.png (needs matplotlib)
```

`load_test.py` fires 200 concurrent requests (bounded by a semaphore),
degrades `self_hosted` partway through the run, restores it later, and
polls `/admin/status` throughout — writing everything to
`scripts/load_test_output.json` for the two scripts above to read.

## What broke, what I'd add with more time

**Real friction hit building this:**

- The ported `CircuitBreaker.record_failure()` bug (`self.failure_count`
  alone is a no-op expression — it never increments) meant the breaker
  could only ever open via a failed HALF_OPEN probe, never from a run of
  repeated failures. Caught it with a small throwaway script
  (`scripts/debug_breaker.py`) that called `record_failure()` five times in
  a row and watched `failure_count` stay at 0 the whole time.
- After building the tracing layer, `generate()` started crashing on
  *every* request with `TypeError: 'AttemptResult' object does not support
  item assignment` — `_attempt_backend` returns a dataclass, but the
  caller was still indexing it like the dict it used to return before that
  refactor. `main.py`'s broad `except Exception -> 503` silently swallowed
  this, so it looked like "the backends are just failing" until traced
  back to the actual line.
- Even after fixing that, `/admin/status` kept reporting an empty
  `trace_summary`. `TraceStore.record()` itself was correct — nothing in
  `router.py` was ever calling it. A component can be fully correct in
  isolation and still contribute nothing if it's never actually wired in.
- Then a second, subtler bug in that wiring: the success-path `GatewaySpan`
  referenced `error=e` from outside the one `except` block that actually
  bound `e`, throwing `UnboundLocalError` on every *successful* attempt —
  silently swallowed again, this time by a test script's own
  `except Exception: pass`. A broad except in your own test harness can
  hide the exact bug you're trying to surface.
- Once the load test was running end to end, I initially assumed (and wrote
  down) that the breaker never tripped, on the reasoning that
  `retry_with_backoff` gives every attempt up to 5 raw tries before it
  counts as one failure — so roughly 22% of individual requests still
  succeed via retries even while "95% broken," resetting `failure_count`
  back to 0 before a streak of 5 could accumulate. **That reasoning only
  holds for one request at a time.** Re-running the same load test and
  instrumenting the breaker's actual state transitions directly (not just
  reading `/admin/status`, which is exactly the stale signal described
  above) showed the breaker tripping every run — 1 to 5 times per
  200-request run across 10 runs, never zero. At concurrency 10, several
  requests hit a 95%-degraded backend close enough together in time that
  their retry-exhaustion failures land back-to-back regardless of any one
  request's own retry-recovery odds; the 22% figure describes a single
  sequential request, not what 10 of them do at once.
- That same direct instrumentation caught something the retries-mask-it
  story would never have surfaced: in most runs, `record_success()`
  transitioned the breaker straight from OPEN to CLOSED, skipping
  HALF_OPEN entirely — the true sequence, on inspection, was a request
  admitted while CLOSED that finished late (after its own retries) and
  reported success *after* a different concurrent request had already
  tripped the breaker to OPEN. `record_success()`/`record_failure()` had
  no concept of "this signal might be stale relative to the breaker's
  current state" — they just overwrote it. Separately,
  `CircuitBreaker.allow_request()` also didn't gate `HALF_OPEN` to a
  single probe — every concurrent caller was let through once the
  cooldown elapsed, not just one. **Fixed both** in `app/resilience.py`
  (`CircuitBreaker.allow_request`/`record_success`/`record_failure`,
  lines 94-127): `record_success`/`record_failure` now no-op if the
  breaker is already OPEN (a stale signal from before the trip can't
  override it), and `allow_request` only returns `True` from `HALF_OPEN`
  on the single call that makes the `OPEN -> HALF_OPEN` transition —
  every other concurrent caller is rejected until that probe resolves.
  Verified: reran the same load test 5 times post-fix — every OPEN cycle
  now goes cleanly through cooldown -> one HALF_OPEN probe -> resolve,
  zero stale-state bypasses, vs. the race showing up in most pre-fix
  runs. `docs/failover_chart.png` is from a post-fix run.

**What I'd add with more time:**

- **Per-request-type routing** — every request currently tries primary
  first, no matter what. Recovery-critical calls would be better served by
  routing straight to the slower-but-steadier `api_provider` instead of
  paying primary's full retry budget first.
- **Real backends instead of mocks** — the resilience logic has only ever
  been proven against `MockBackend`'s scripted random failures. Real
  backends would surface failure modes these mocks can't: timeouts vs.
  explicit errors, partial responses, rate-limit headers that should feed
  back into the token bucket instead of a fixed static rate.
- **Persistent trace storage** — `TraceStore` is a plain in-memory list;
  every span is lost on restart. A real deployment would want this
  somewhere durable (even just SQLite) so `/admin/status` reflects history
  across restarts, not just since the process last started.

## License

MIT
