"""
Step 17 — turn scripts/load_test_output.json into the before/during/after
failover chart. Reads results (per-request outcomes, indexed 0..N-1) and
snapshots (periodic /admin/status polls, each with a real timestamp and
the cumulative trace_summary at that moment).
"""
import json
import sys

import matplotlib.pyplot as plt

DEGRADE_AT_REQUEST = 80
RESTORE_AT_REQUEST = 150

with open(sys.argv[1] if len(sys.argv) > 1 else "scripts/load_test_output.json") as f:
    data = json.load(f)

results = data["results"]
snapshots = data["snapshots"]

# ---- panel 1 data: per-request latency + rolling success rate, by request index ----
idx = [r["i"] for r in results]
lat = [r["latency_ms"] for r in results]
ok = [r["ok"] for r in results]

window = 10
roll_x, roll_sr = [], []
for i in range(window - 1, len(results)):
    chunk = ok[i - window + 1 : i + 1]
    roll_x.append(i)
    roll_sr.append(sum(chunk) / window)

# ---- panel 2 data: self_hosted cumulative stats, by elapsed wall-clock time ----
t0 = snapshots[0]["t"]
snap_t, sh_sr, sh_p50, sh_state = [], [], [], []
degrade_t = restore_t = None
prev_degraded = False
for s in snapshots:
    sh = s["status"].get("trace_summary", {}).get("self_hosted")
    degraded_now = s["status"].get("self_hosted_degraded", False)
    if degraded_now and not prev_degraded and degrade_t is None:
        degrade_t = s["t"] - t0
    if not degraded_now and prev_degraded and restore_t is None:
        restore_t = s["t"] - t0
    prev_degraded = degraded_now
    if sh:
        snap_t.append(s["t"] - t0)
        sh_sr.append(sh["success_rate"])
        sh_p50.append(sh["p50_latency_ms"])
        sh_state.append(sh["circuit_state"])

fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(11, 8.5))

# --- Panel 1: per-request latency vs request index ---
ax1.scatter(idx, lat, s=10, alpha=0.5, color="#3b6ea5", label="per-request latency")
ax1.axvspan(DEGRADE_AT_REQUEST, RESTORE_AT_REQUEST, color="orange", alpha=0.12,
            label="self_hosted degraded (requested window)")
ax1.axvline(DEGRADE_AT_REQUEST, color="#c0392b", linestyle="--", linewidth=1)
ax1.axvline(RESTORE_AT_REQUEST, color="#1e8449", linestyle="--", linewidth=1)
ax1.set_xlabel("request index (0-199, dispatch order)")
ax1.set_ylabel("latency (ms)", color="#3b6ea5")
ax1.tick_params(axis="y", labelcolor="#3b6ea5")
ax1.set_title("Per-request latency + rolling success rate (by request index)")

ax1b = ax1.twinx()
ax1b.plot(roll_x, roll_sr, color="#1e8449", linewidth=2, label=f"rolling success rate (window={window})")
ax1b.set_ylabel("rolling success rate", color="#1e8449")
ax1b.set_ylim(-0.05, 1.05)
ax1b.tick_params(axis="y", labelcolor="#1e8449")

lines1, labels1 = ax1.get_legend_handles_labels()
lines1b, labels1b = ax1b.get_legend_handles_labels()
ax1.legend(lines1 + lines1b, labels1 + labels1b, loc="lower right", fontsize=8, framealpha=0.9)

# --- Panel 2: self_hosted's own cumulative stats vs elapsed time ---
ax2.plot(snap_t, sh_sr, color="#c0392b", marker="o", markersize=3, linewidth=1.5,
          label="self_hosted cumulative success_rate")
if degrade_t is not None:
    ax2.axvline(degrade_t, color="#c0392b", linestyle="--", linewidth=1)
    ax2.text(degrade_t, 1.02, " degraded", color="#c0392b", fontsize=8, va="bottom")
if restore_t is not None:
    ax2.axvline(restore_t, color="#1e8449", linestyle="--", linewidth=1)
    ax2.text(restore_t, 1.02, " restored", color="#1e8449", fontsize=8, va="bottom")
ax2.set_ylim(-0.05, 1.15)
ax2.set_xlabel("elapsed time (s)")
ax2.set_ylabel("self_hosted success_rate", color="#c0392b")
ax2.tick_params(axis="y", labelcolor="#c0392b")
states_seen = sorted(set(sh_state))
ax2.set_title(f"self_hosted: cumulative success rate + p50 latency (circuit_state stayed {states_seen!r} the whole run)")

ax2b = ax2.twinx()
ax2b.plot(snap_t, sh_p50, color="#7d3c98", linewidth=1.5, linestyle=":",
           label="self_hosted p50 latency (ms)")
ax2b.set_ylabel("p50 latency (ms)", color="#7d3c98")
ax2b.tick_params(axis="y", labelcolor="#7d3c98")

states_seen = sorted(set(sh_state))

lines2, labels2 = ax2.get_legend_handles_labels()
lines2b, labels2b = ax2b.get_legend_handles_labels()
ax2.legend(lines2 + lines2b, labels2 + labels2b, loc="center left", fontsize=8, framealpha=0.9)

fig.suptitle("Gateway load test — graceful degradation of self_hosted, fallback to api_provider", fontsize=13)
fig.tight_layout(rect=[0, 0, 1, 0.97])
fig.savefig("failover_chart.png", dpi=150)
print("wrote failover_chart.png")
print(f"degrade detected at t={degrade_t:.2f}s, restore detected at t={restore_t:.2f}s" if degrade_t else "no degrade window detected")
print(f"circuit_state values observed for self_hosted: {states_seen}")
