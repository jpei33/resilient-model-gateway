"""
Observability layer — Day 3 of PLAN.md.

Adapt (don't just copy) the LLMSpan/Trace/TraceStore pattern from
startup_prep/week4_sola/day16_agentic_evals/observability_tools_reading.py
— that reading is generic (arbitrary agent traces); this gateway is
specifically a two-backend router, so the fields that matter are
different. Deciding what belongs on a span for THIS system is the task,
not just porting the dataclass.

TASK — GatewaySpan:
    A starting field set is sketched below. At minimum you want: which
    backend served the request, how many retries fired before
    success/failure, the circuit breaker's state AT THE TIME of the
    request (not after — that's what makes "the breaker tripped mid-run"
    visible in a chart later), latency, success/failure, and a cost
    estimate (MockBackend.cost_per_call_usd, times retries+1 if you want
    retries to show up in the cost signal too). Add/remove fields as you
    see fit.

TASK — TraceStore.record(span):
    Append a span to self.spans.

TASK — TraceStore.summary_stats() -> dict:
    This is Day 3's "tiny dashboard" — a rolling summary, not a UI. At
    minimum, return per-backend: success rate, p50/p95 latency, current
    circuit state, and total cost. This is what Day 4's load test will
    call periodically (or at the end) to produce the before/during/after
    picture of the failover event — design it with that chart in mind.
"""
from dataclasses import dataclass
from typing import Any, Dict, List


@dataclass
class GatewaySpan:
    # Starting point — adjust freely, see the docstring above.
    trace_id: str
    backend: str
    success: bool
    latency_ms: float
    retries: int
    circuit_state: str
    timestamp: float
    cost_usd: float = 0.0
    error: str = ""


class TraceStore:
    def __init__(self):
        self.spans: List[GatewaySpan] = []

    def record(self, span: GatewaySpan) -> None:
        raise NotImplementedError("TODO: Day 3 task — see module docstring")

    def summary_stats(self) -> Dict[str, Any]:
        raise NotImplementedError("TODO: Day 3 task — see module docstring for the minimum shape")
