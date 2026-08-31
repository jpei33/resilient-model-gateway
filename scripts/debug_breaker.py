"""
Diagnostic script for the CircuitBreaker bug (Step 6 of the runbook).

Goal: prove, with print statements, that record_failure() currently never
increments failure_count -- which means the breaker can only ever open via
a failed HALF_OPEN probe, never via a run of repeated CLOSED-state failures.

Run with:  python scripts/debug_breaker.py
"""
from app.resilience import CircuitBreaker, CircuitState

breaker = CircuitBreaker(failure_threshold=3, cooldown_seconds=1.0)

# TODO: call breaker.record_failure() five times in a row. After each call,
# print something like:
#   attempt 1: state=CircuitState.CLOSED failure_count=0
# so you can see, call by call, whether failure_count is actually moving
# and whether/when state flips from CLOSED to OPEN.
#
# Expected once the bug is FIXED: failure_count climbs 1, 2, 3 and state
# flips to OPEN on the 3rd call (matches failure_threshold=3 above).
# Expected RIGHT NOW, with the bug still in place: failure_count stays at
# 0 forever and state never leaves CLOSED.

for i in range(5):
    breaker.record_failure()
    print(f"attempt {i+1}: {breaker.state} failure_count={breaker.failure_count}")


