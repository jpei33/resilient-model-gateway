import json

with open("scripts/load_test_output.json") as f:
    data = json.load(f)

snapshots = data["snapshots"]
t0 = snapshots[0]["t"] if snapshots else 0

print(f"{'t+s':>7}  {'circuit':>10}  {'success_rate':>13}  {'p50_ms':>8}  {'p95_ms':>8}  {'count':>5}")
for snap in snapshots:
    sh = snap["status"].get("trace_summary", {}).get("self_hosted")
    if not sh:
        continue
    t_rel = snap["t"] - t0
    flag = "  <-- breaker not closed" if sh["circuit_state"] != "closed" else ""
    print(f"{t_rel:7.2f}  {sh['circuit_state']:>10}  {sh['success_rate']:13.2f}  "
          f"{sh['p50_latency_ms']:8.1f}  {sh['p95_latency_ms']:8.1f}  {sh['request_count']:5d}{flag}")
