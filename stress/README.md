# EuEarth adversarial stress harness

The stress the frontier reviewers demanded — hard invariants under CONCURRENCY,
not happy-path sequences. Run against a live server (founder phase on):

    EUEARTH_FOUNDER_PHASE=1 .venv/bin/python -m uvicorn web.app:app --port 8080 &
    .venv/bin/python stress/adversarial.py http://127.0.0.1:8080/mcp

Invariants (all PASS as of Stress Test 001):
- T1  invite one-shot: N DIDs race one invite -> exactly one commits (no Sybil).
- T2  wallet cap: N concurrent tips -> total committed <= cap (no double-spend).
- T3  DID spoof: delegation for A presented as B -> refused (audience mismatch).

Roadmap (from the 4-model review): benchmark-gaming + swap atomicity under two
concurrent challenges; sandbox escape; storage-quota grief; room isolation under
kill -9; delegation revocation mid-session (<=1s kill); public-internet strangers.
