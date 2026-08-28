# Architecture

TODO — draw the request-flow diagram here once the gateway is fully wired
(Day 4 of PLAN.md). At minimum it should show: client -> gateway ->
[rate limiter -> circuit breaker -> retry -> primary backend] -> (on
failure) -> [rate limiter -> circuit breaker -> retry -> fallback backend]
-> response, plus where tracing hooks in.
