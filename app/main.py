"""
FastAPI app wiring — the public entrypoint.

Run with:  uvicorn app.main:app --reload

Endpoints:
  POST /gateway/generate      -> the resilient gateway (app/router.py) — the part you build
  POST /admin/degrade/{name}  -> flip a backend into "always fail" mode, for the Day 4 load test
  POST /admin/restore/{name}  -> restore a backend to normal behavior
  GET  /admin/status          -> current backend degradation state (+ trace summary once Day 3 is done)

This file is boilerplate wiring, not TODO'd — the interesting work lives in
resilience.py (done, minus one bug you're fixing), router.py (TODO), and
tracing.py (TODO).
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
    status_payload = {
        "self_hosted_degraded": self_hosted.degraded,
        "api_provider_degraded": api_provider.degraded,
    }
    # TODO (Day 3): once tracing.py's TraceStore.summary_stats() is
    # implemented, merge it in here too — this is your "tiny dashboard."
    try:
        status_payload["trace_summary"] = trace_store.summary_stats()
    except NotImplementedError:
        pass
    return status_payload


def _backend_by_name(name: str) -> MockBackend:
    backend = _BACKENDS.get(name)
    if backend is None:
        raise HTTPException(status_code=404, detail=f"unknown backend '{name}'")
    return backend
