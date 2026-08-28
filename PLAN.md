# Build Plan

4-day scope, one deliverable focus per day. Don't gold-plate any single day
at the expense of finishing all four — a working end-to-end gateway with a
visible failover chart beats a beautifully engineered router that never
gets load-tested.

## Day 1 — Two backends + naive gateway

- [x] Scaffolding (this repo)
- [ ] `app/backends.py` — sanity-check the two mock backend profiles feel
      right (self-hosted flakier/faster, API provider steadier/slower)
- [ ] Naive version: gateway always calls `self_hosted`, no fallback yet —
      confirm the happy path works end to end before adding resilience

## Day 2 — Full resilience stack

- [ ] Fix the `CircuitBreaker.record_failure()` bug in `app/resilience.py`
      (flagged inline)
- [ ] Implement `app/router.py`'s `ModelGateway`: per-backend rate limiter +
      circuit breaker, retry primary, fall back to secondary on
      exhausted-retry or open-circuit
- [ ] Manually verify: force-fail the primary (temporarily crank its
      `error_rate` way up) and confirm requests still succeed via fallback

## Day 3 — Observability

- [ ] Design and implement `app/tracing.py`'s `GatewaySpan` fields
- [ ] Implement `TraceStore.record()` and `summary_stats()`
- [ ] Wire `summary_stats()` into `GET /admin/status`
- [ ] Confirm the summary shows per-backend success rate, p50/p95 latency,
      circuit state, and cost after a handful of manual requests

## Day 4 — Load test + graceful degradation + writeup

- [ ] Tune `scripts/load_test.py`'s concurrency/volume for something that
      actually stresses the rate limiter and circuit breaker
- [ ] Add the failure-injection timing (degrade primary partway through,
      restore it later)
- [ ] Turn the results into a chart: latency/success-rate over time, with
      the failover event visible
- [ ] Update the README's architecture section with a real diagram
- [ ] Write the "what broke, what I'd add with more time" section
