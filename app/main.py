"""
FastAPI app wiring — the public entrypoint.

Run with:  uvicorn app.main:app --reload

Endpoints:
  POST /gateway/generate      -> the resilient gateway (app/router.py)
  POST /admin/degrade/{name}  -> flip a backend into "always fail" mode,
                                  for exercising failover and load tests
  POST /admin/restore/{name}  -> restore a backend to normal behavior
  GET  /admin/status          -> current backend degradation state, plus
                                  a per-backend trace summary (success
                                  rate, latency, circuit state, cost)
"""
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from app.backends import APIProviderBackend, MockBackend, SelfHostedBackend
from app.router import ModelGateway
from app.tracing import TraceStore

app = FastAPI(title="Resilient Model Gateway")

self_hosted = SelfHostedBackend()
api_provider = APIProviderBackend()
trace_store = TraceStore()
gateway = ModelGateway(
    primary=self_hosted,
    fallback=api_provider,
    trace_store=trace_store,
)

_BACKENDS: dict[str, MockBackend] = {
    "self_hosted": self_hosted,
    "api_provider": api_provider,
}


class GenerateRequest(BaseModel):
    prompt: str


@app.post("/gateway/generate")
async def generate(req: GenerateRequest):
    try:
        return await gateway.generate(req.prompt)
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


@app.post("/admin/degrade/{backend_name}")
async def degrade(backend_name: str):
    _backend_by_name(backend_name).degraded = True
    return {"backend": backend_name, "degraded": True}


@app.post("/admin/restore/{backend_name}")
async def restore(backend_name: str):
    _backend_by_name(backend_name).degraded = False
    return {"backend": backend_name, "degraded": False}


@app.get("/admin/status")
async def status():
    return {
        "self_hosted_degraded": self_hosted.degraded,
        "api_provider_degraded": api_provider.degraded,
        "trace_summary": trace_store.summary_stats(),
    }


def _backend_by_name(name: str) -> MockBackend:
    backend = _BACKENDS.get(name)
    if backend is None:
        raise HTTPException(status_code=404, detail=f"unknown backend '{name}'")
    return backend
