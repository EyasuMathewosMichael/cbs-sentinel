# Bank / CBS Integration Simulator

This Phase 20 bank simulator review contract enumerates realistic CBS scenarios for
SENTINEL integration testing and workflow review.

Scenarios:

- normal transaction
- timeout
- delayed response
- debit without credit
- lost response
- duplicate request
- duplicate posting
- reversal
- CBS unavailable
- incorrect balance response

The simulator remains non-authoritative and emits deterministic contract artifacts
without posting a second financial effect.
