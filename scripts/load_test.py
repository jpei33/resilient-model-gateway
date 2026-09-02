"""
Load test with mid-run failure injection: fires TOTAL_REQUESTS concurrent
requests at the gateway (bounded by a semaphore), degrades `self_hosted`
partway through the run, restores it later, and polls /admin/status
throughout to capture the before/during/after picture of the failover.

Concurrency and timing use a semaphore to cap in-flight requests plus
gather() with a per-call try/except, so one failed request can't take
down the batch.

Run with:  python scripts/load_test.py
(requires the gateway running: uvicorn app.main:app)

Writes scripts/load_test_output.json (per-request results + status
snapshots) for scripts/inspect_snapshots.py and scripts/plot_load_test.py
to read.
"""
import asyncio
import json
import time

import httpx

GATEWAY_URL = "http://127.0.0.1:8000"
CONCURRENCY = 10          # in-flight request cap
TOTAL_REQUESTS = 200
DEGRADE_AT_REQUEST = 80   # inject failure once this many requests have completed
RESTORE_AT_REQUEST = 150  # recover self_hosted once this many have completed
STATUS_POLL_INTERVAL_S = 0.25   # snapshot interval

class Progress:
    def __init__(self):
        self.completed = 0

async def inject_failures(client: httpx.AsyncClient, progress: "Progress", done: asyncio.Event) -> None:
    degraded = False
    restored = False

    while not done.is_set():
        if not degraded and progress.completed >= DEGRADE_AT_REQUEST:
            await client.post(f"{GATEWAY_URL}/admin/degrade/self_hosted")
            degraded = True
            print(f"[inject] degraded self_hosted at completed={progress.completed}")
        if degraded and not restored and progress.completed >= RESTORE_AT_REQUEST:
            await client.post(f"{GATEWAY_URL}/admin/restore/self_hosted")
            restored = True
            print(f"[inject] restored self_hosted at completed={progress.completed}")
        await asyncio.sleep(0.05)
    if degraded and not restored:
         await client.post(f"{GATEWAY_URL}/admin/restore/self_hosted")

async def poll_status(client: httpx.AsyncClient, done: asyncio.Event, snapshots: list):
    while not done.is_set():
        try:
            resp = await client.get(f"{GATEWAY_URL}/admin/status")
            snapshots.append({"t": time.time(), "status": resp.json()})
        except Exception:
            pass
        await asyncio.sleep(STATUS_POLL_INTERVAL_S)

async def fire_one(client: httpx.AsyncClient, sem: asyncio.Semaphore, i: int, progress: "Progress") -> dict:
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
        progress.completed += 1
        return {"i": i, "ok": ok, "latency_ms": latency_ms}


async def main():
    sem = asyncio.Semaphore(CONCURRENCY)
    progress = Progress()
    done = asyncio.Event()
    snapshots: list = []

    async with httpx.AsyncClient() as client:
        tasks = [fire_one(client, sem, i, progress) for i in range(TOTAL_REQUESTS)]
        controller = asyncio.create_task(inject_failures(client, progress, done))
        poller = asyncio.create_task(poll_status(client, done, snapshots))

        results = await asyncio.gather(*tasks)
        done.set()
        await controller
        await poller

    successes = sum(1 for r in results if r["ok"])
    print(f"{successes}/{TOTAL_REQUESTS} succeeded")
    print(f"{len(snapshots)} status snapshots collected")

    with open("scripts/load_test_output.json", "w") as f:
        json.dump({"results": results, "snapshots": snapshots}, f, indent=2)
    print("wrote scripts/load_test_output.json")


if __name__ == "__main__":
    asyncio.run(main())
