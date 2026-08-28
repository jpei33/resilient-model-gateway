"""
Mock model backends. You shouldn't need to modify the failure-simulation
mechanics, but feel free to tune the knobs (error_rate, latency) once your
gateway works and you want to stress-test different failure profiles.

Two backends, deliberately different profiles, mirroring Day 21's
FlakyModel:
  SelfHostedBackend  — fast, cheap, occasionally overloaded (higher error rate)
  APIProviderBackend — slower, pricier, more reliable (lower error rate)

Both expose the same interface your resilience layer already knows how to
wrap: `async def call(self, prompt: str) -> str` that either returns a raw
JSON string or raises RetryableAPIError, exactly like Day 21's FlakyModel.

`degraded`: an admin-togglable flag (see app/main.py's /admin/degrade
route) that forces near-100% failure — this is how Day 4's load test
simulates "the self-hosted backend goes down mid-run" without actually
killing a process.
"""
import asyncio
import json
import random

from app.resilience import RetryableAPIError


class MockBackend:
    name: str = "base"
    base_latency_s: float = 0.05
    error_rate: float = 0.1
    cost_per_call_usd: float = 0.001

    def __init__(self, seed: int = 7):
        self._rng = random.Random(seed)
        self.degraded = False
        self.call_count = 0

    async def call(self, prompt: str) -> str:
        self.call_count += 1
        await asyncio.sleep(self.base_latency_s * (1 + self._rng.random()))

        effective_error_rate = 0.95 if self.degraded else self.error_rate
        roll = self._rng.random()
        if roll < effective_error_rate:
            raise RetryableAPIError(f"{self.name} transient failure", retry_after=None)

        return json.dumps({
            "answer": f"[{self.name}] ok for: {prompt[:30]}",
            "confidence": round(0.7 + self._rng.random() * 0.3, 2),
        })


class SelfHostedBackend(MockBackend):
    """Fast + cheap + flakier — the 'self-hosted vLLM' simulation."""
    name = "self_hosted"
    base_latency_s = 0.03
    error_rate = 0.15
    cost_per_call_usd = 0.0002


class APIProviderBackend(MockBackend):
    """Slower + pricier + more reliable — the 'API provider' simulation."""
    name = "api_provider"
    base_latency_s = 0.12
    error_rate = 0.03
    cost_per_call_usd = 0.004
