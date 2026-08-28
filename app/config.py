"""
Central place for tunables, so router.py/backends.py don't hardcode magic
numbers. Adjust values as you tune Day 2's resilience stack — this file
itself needs no TODOs, it's just a settings holder.
"""
from pydantic import BaseModel


class GatewaySettings(BaseModel):
    rate: float = 20.0             # tokens/sec, per-backend rate limiter
    capacity: float = 5.0          # burst size, per-backend rate limiter
    failure_threshold: int = 5     # consecutive failures before a circuit opens
    cooldown_seconds: float = 2.0  # how long a circuit stays OPEN before a HALF_OPEN probe
    max_attempts: int = 3          # retry attempts per backend before falling back


settings = GatewaySettings()
