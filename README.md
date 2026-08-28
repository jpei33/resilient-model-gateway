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

<!-- TODO: request-flow diagram here once the gateway is working end to end -->

Two mock backends behind a FastAPI service, each independently rate-limited
and circuit-broken. The gateway tries the primary first; on a retried-out
failure or an open circuit, it falls back to the secondary. Every attempt
is traced (which backend, how many retries, circuit state at request time,
latency, cost) so failure and recovery are visible after the fact, not just
inferred.

## Status

Early — see [PLAN.md](PLAN.md) for the build plan and current progress.

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
```

## License

MIT
