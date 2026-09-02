"""
Observability layer for the gateway: a GatewaySpan per backend attempt,
and a TraceStore that collects them and rolls them up into per-backend
summary stats.

GatewaySpan captures what matters for a two-backend router specifically:
which backend served the request, how many retries fired before
success/failure, the circuit breaker's state AT THE TIME of the request
(captured before the call, not read live afterward — that's what makes a
mid-run circuit trip visible in a chart rather than washed out by the time
the response comes back), latency, success/failure, and a per-call cost
estimate.
"""
from dataclasses import dataclass
from typing import Any, Dict, List
from collections import defaultdict


@dataclass
class GatewaySpan:
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
        self.spans.append(span)

    def summary_stats(self) -> Dict[str, Any]:
        """
        Per-backend rollup: success rate, p50/p95 latency, total cost, and
        request count. `circuit_state` here is the state recorded on the
        most recent span for that backend — a snapshot as of the last
        request, not a live read of the breaker.
        """
        by_backend: Dict[str, List[GatewaySpan]] = defaultdict(list)
        for span in self.spans:
            by_backend[span.backend].append(span)

        stats: Dict[str, Any] = {}

        for backend, spans in by_backend.items():
            latencies = sorted(s.latency_ms for s in spans)
            n = len(latencies)
            stats[backend] = {
                "success_rate": sum(s.success for s in spans)/n,
                "p50_latency_ms": latencies[n//2],
                "p95_latency_ms": latencies[n*95//100],
                "circuit_state": spans[-1].circuit_state,
                "total_cost_usd": sum(s.cost_usd for s in spans),
                "request_count": n

            }
        return stats
