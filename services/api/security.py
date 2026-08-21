"""FastAPI dependencies that put a real principal on every mutating request.

WHY A SEPARATE MODULE
------------------------
`services/api/main.py` is 1,300 lines of endpoints. Burying the
authentication decision in it is how an endpoint gets added later without
one. Everything privileged imports `require_principal` or
`require_human_principal` from here, and
`tests/test_api_auth.py::test_every_mutating_route_requires_a_principal`
walks the app's route table and fails if a POST route exists without one of
these dependencies. Adding an unauthenticated mutation is therefore a test
failure, not a review miss.

RATE LIMITING, HONESTLY SCOPED
---------------------------------
[LIMITATION] The limiter below is an in-process token bucket keyed by
principal. On a single Cloud Run instance it is a real limit. Across
several instances it limits per instance, not globally -- a real deployment
wants Cloud Armor or an API gateway in front. That is stated here and in
`docs/SECURITY.md` rather than implied away, because a rate limit that is
weaker than it looks is worse than none.
"""

from __future__ import annotations

import time
from collections import deque

from fastapi import HTTPException, Request

from lib.auth import Principal, Unauthenticated, Unauthorized, authenticate, require_human

#: [ASSUMPTION] Chosen limits: enough for a judge clicking through a demo,
#: low enough that an unattended loop is stopped.
RATE_LIMIT_REQUESTS = 30
RATE_LIMIT_WINDOW_SECONDS = 60.0

_BUCKETS: dict[str, deque[float]] = {}


def _check_rate_limit(principal: str) -> None:
    now = time.monotonic()
    bucket = _BUCKETS.setdefault(principal, deque())
    while bucket and now - bucket[0] > RATE_LIMIT_WINDOW_SECONDS:
        bucket.popleft()
    if len(bucket) >= RATE_LIMIT_REQUESTS:
        raise HTTPException(
            429,
            f"rate limit exceeded for {principal}: more than {RATE_LIMIT_REQUESTS} "
            f"requests in {RATE_LIMIT_WINDOW_SECONDS:.0f}s",
        )
    bucket.append(now)


def reset_rate_limits() -> None:
    """Test hook. Mirrors the `reset_for_test` hooks elsewhere in the repo."""
    _BUCKETS.clear()


def require_principal(request: Request) -> Principal:
    """Any authenticated caller. 401 when nothing resolves -- never a default."""
    try:
        principal = authenticate(request.headers)
    except Unauthenticated as exc:
        raise HTTPException(401, str(exc)) from exc
    _check_rate_limit(principal.principal)
    return principal


def require_human_principal(request: Request) -> Principal:
    """An authenticated HUMAN. 403 for a service identity.

    The Human Override Gate exists to put a person between an isolated agent
    and a re-minted warrant; a service token satisfying it would make the
    gate decorative. `lib.auth.require_human` is the one implementation of
    that rule.
    """
    principal = require_principal(request)
    try:
        return require_human(principal)
    except Unauthorized as exc:
        raise HTTPException(403, str(exc)) from exc


__all__ = [
    "RATE_LIMIT_REQUESTS",
    "RATE_LIMIT_WINDOW_SECONDS",
    "require_human_principal",
    "require_principal",
    "reset_rate_limits",
]
