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
- Once the load test was running end to end, the most interesting finding
  wasn't a bug at all: with `self_hosted` degraded to a 95% raw error rate,
  its circuit breaker never tripped during the whole run. `retry_with_backoff`
  gives every attempt up to 5 raw tries before it counts as one failure
  against `failure_threshold=5` — so roughly 22% of individual requests
  still succeed via retries even while "95% broken," and each such success
  resets `failure_count` back to 0. Retries and circuit breakers can work
  against each other: the retry layer's whole job is exactly what kept the
  breaker blind here.

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
