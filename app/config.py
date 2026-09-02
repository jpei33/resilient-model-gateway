"""
Tunable defaults for the resilience stack (rate limit, circuit breaker,
retry budget), collected in one place.

Currently unused: router.py defines its own copies of these same defaults
as ModelGateway constructor arguments rather than importing from here.
Wiring them together (passing `settings` into ModelGateway at startup) is
a natural follow-up if these values ever need to be tuned from one place
instead of two.
"""
from pydantic import BaseModel


class GatewaySettings(BaseModel):
    rate: float = 20.0             # tokens/sec, per-backend rate limiter
    capacity: float = 5.0          # burst size, per-backend rate limiter
    failure_threshold: int = 5     # consecutive failures before a circuit opens
    cooldown_seconds: float = 2.0  # how long a circuit stays OPEN before a HALF_OPEN probe
    max_attempts: int = 3          # retry attempts per backend before falling back


settings = GatewaySettings()
