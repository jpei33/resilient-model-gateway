1) total latency budget across primary retries + fallback, when does "try harder on primary" cost more than "just fallback sooner"

once a backend is persistently degraded, every additional retry is spending real latency for close to zero marginal gain. this is especially costly with api_provider at 97% accuracy. from the plot, p50/p95 went 1.5x cumulative when primary degraded. in this case its worth it to stop the retries. this is why the circuit breaker exists, even though in our run it never triggered, it will stop paying this retry tax when a backend is known-bad. this didnt get triggered in our run since failure_count got reset on the few successes. 

2) how would i route by request type instead of always trying primary first?

if we add a request_type into the generate call, we can occassionally traffic certain calls to get api_provider first. the more complex part is determining the request_type. the caller should determine this instead of inferring from the prompt content. in temrs of the caller determining, it can be an option in the post request, or it can be determined by some caller categorization. 