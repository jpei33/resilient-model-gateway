"""
Smoke test for the tracing layer: runs ModelGateway.generate() 20 times
directly (no HTTP layer involved) and prints how many spans TraceStore
collected plus the resulting summary_stats(), to confirm tracing is wired
in end to end.

Run with:  python scripts/test_trace.py
"""
import asyncio
from app.backends import SelfHostedBackend, APIProviderBackend
from app.tracing import TraceStore
from app.router import ModelGateway

async def main():
    gw = ModelGateway(primary=SelfHostedBackend(), fallback=APIProviderBackend(), trace_store=TraceStore())
    for _ in range(20):
        try:
            await gw.generate("ping")
        except Exception:
            pass
    print(len(gw.trace_store.spans), "spans recorded")
    print(gw.trace_store.summary_stats())

asyncio.run(main())
