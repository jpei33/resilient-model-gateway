"""
Small diagnostic script that isolated the CircuitBreaker.record_failure()
bug: `self.failure_count` alone is a no-op expression statement, so
failure_count never actually incremented, and the breaker could only ever
open via a failed HALF_OPEN probe rather than a run of repeated
CLOSED-state failures.

Confirmed the fix by calling record_failure() five times in a row against
a breaker with failure_threshold=3 and watching failure_count climb
1, 2, 3 with state flipping CLOSED -> OPEN on the third call.

Run with:  python scripts/debug_breaker.py
"""
from app.resilience import CircuitBreaker

breaker = CircuitBreaker(failure_threshold=3, cooldown_seconds=1.0)

for i in range(5):
    breaker.record_failure()
    print(f"attempt {i+1}: {breaker.state} failure_count={breaker.failure_count}")
