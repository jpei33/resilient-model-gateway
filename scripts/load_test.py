"""
Load test + graceful-degradation demo — Day 4 of PLAN.md.

The concurrency/timing HARNESS below is done for you — it's the same
bounded-concurrency + per-call isolation pattern from
startup_prep/asyncio_examples.py's demo_combined() (a semaphore to cap
concurrency, gather() with per-call try/except so one failure doesn't
kill the batch, wall-clock timing).

What's NOT done, and is the actual point of Day 4:
  1. WHEN to call POST /admin/degrade/self_hosted mid-run (the failure
     injection) and when to call /admin/restore/self_hosted (recovery).
  2. Pulling GET /admin/status (once tracing.py's summary_stats() exists)
     at intervals to build the before/during/after picture.
  3. Turning the collected numbers into the chart PLAN.md's Day 4 asks
     for: latency/success-rate over time, with the failover event visible.
  4. Deciding on realistic load parameters (concurrency, request count,
     ramp shape) for your machine and your configured rate limits — the
     constants below are placeholders, not tuned numbers.

Run with:  python scripts/load_test.py
(requires the gateway running: uvicorn app.main:app)
"""
import asyncio
import time

import httpx

GATEWAY_URL = "http://127.0.0.1:8000"
CONCURRENCY = 10          # TODO: tune
TOTAL_REQUESTS = 200      # TODO: tune
DEGRADE_AT_REQUEST = 80   # TODO: decide when to inject the failure
RESTORE_AT_REQUEST = 150  # TODO: decide when (or whether) to recover it


async def fire_one(client: httpx.AsyncClient, sem: asyncio.Semaphore, i: int) -> dict:
    async with sem:
        t0 = time.perf_counter()
        try:
            resp = await client.post(
                f"{GATEWAY_URL}/gateway/generate",
                json={"prompt": f"load-test prompt {i}"},
                timeout=10.0,
            )
            ok = resp.status_code == 200
        except Exception:
            ok = False
        latency_ms = (time.perf_counter() - t0) * 1000
        return {"i": i, "ok": ok, "latency_ms": latency_ms}


async def main():
    sem = asyncio.Semaphore(CONCURRENCY)

    async with httpx.AsyncClient() as client:
        # TODO: replace this single gather with a version that injects
        # /admin/degrade partway through and /admin/restore later — as
        # written, this just fires everything at once with no failure
        # injection, which won't show you anything interesting yet.
        tasks = [fire_one(client, sem, i) for i in range(TOTAL_REQUESTS)]
        results = await asyncio.gather(*tasks)

    successes = sum(1 for r in results if r["ok"])
    print(f"{successes}/{TOTAL_REQUESTS} succeeded")

    # TODO: turn `results` (each has i, ok, latency_ms) into the
    # before/during/after chart PLAN.md's Day 4 deliverable wants.


if __name__ == "__main__":
    asyncio.run(main())
