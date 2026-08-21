"""Caller identity for every mutating endpoint. Fail-closed by construction.

WHY THIS MODULE EXISTS
-------------------------
Before it, `POST /api/command-os/mission/{id}/gate?decision=approve` was
reachable by anyone on the internet (the service deploys
`--allow-unauthenticated`), and `command_os/mission.py` then wrote a
decision-memory record naming the approver `"human::mission_operator"` -- a
module constant, not the caller. That record is one of the two preconditions
`warrant.ledger.mint` requires. So an anonymous HTTP request minted earned
authority and left a permanent, authentic-looking audit record naming a
human who was never present.

The fix is not a middleware that "checks a header". It is that **the
principal recorded in the ledger is the principal that authenticated**, and
there is no code path that supplies a default one.

THREE RESOLVERS, TRIED IN ORDER, ALL EXPLICIT
------------------------------------------------
1. **IAP / Cloud Run signed header** -- `X-Goog-Authenticated-User-Email`.
   Set by Google's infrastructure in front of the container; unforgeable from
   outside when IAP is enabled, which is why it is preferred over anything
   this process could check itself. Only trusted when
   `UNWIND_TRUST_IAP_HEADER=1`, because an app that trusts this header while
   NOT behind IAP trusts a header the client sets.
2. **Bearer token** -- matched against `UNWIND_OPERATOR_TOKENS`, a
   `token:principal` list. Compared with `hmac.compare_digest`, never `==`.
3. **Explicit dev principal** -- `UNWIND_DEV_PRINCIPAL`. Refused outright
   whenever `UNWIND_ENV=production`, so the convenient path cannot be the
   deployed path.

If none resolves, `authenticate` raises `Unauthenticated`. There is no
fourth branch and no default return. `tests/test_auth.py` asserts that the
function's own source contains no anonymous fallback.

WHAT THIS IS NOT
-------------------
[ASSUMPTION / LIMITATION] This is not an identity provider. It does not
issue, rotate, or expire credentials, and the bearer tokens live in an
environment variable rather than Secret Manager. It is the minimum honest
thing: a real, verifiable principal on every privileged mutation, recorded
as the actor. `docs/SECURITY.md` states the gap rather than implying
otherwise.
"""

from __future__ import annotations

import hmac
import os
import uuid
from dataclasses import dataclass, field

#: Principal-prefix convention, matching `tower/registry.py`'s `agent::`.
HUMAN_PREFIX = "human::"
SERVICE_PREFIX = "service::"

IAP_HEADER = "x-goog-authenticated-user-email"
CORRELATION_HEADER = "x-correlation-id"


class Unauthenticated(RuntimeError):
    """No credential resolved. Always a 401 -- never a fall-through to a
    default identity."""


class Unauthorized(RuntimeError):
    """A real principal that may not perform this particular action. Always a
    403 -- distinct from `Unauthenticated`, because conflating "who are you"
    with "you may not" is how audit trails become useless."""


@dataclass(frozen=True)
class Principal:
    """One authenticated caller.

    `principal` is the string written into `decision_memory` and the warrant
    ledger. It is derived from the credential, never from a request body,
    query parameter, or module constant.
    """

    principal: str
    kind: str  # "human" | "service"
    method: str  # "iap" | "bearer" | "dev"
    correlation_id: str = field(default_factory=lambda: uuid.uuid4().hex[:16])

    @property
    def is_human(self) -> bool:
        return self.kind == "human"

    def as_record(self) -> dict[str, str]:
        """The audit shape. `method` travels with the principal so a later
        reader can tell an IAP-verified approval from a dev-mode one without
        cross-referencing deployment configuration that may have changed."""
        return {
            "principal": self.principal,
            "kind": self.kind,
            "auth_method": self.method,
            "correlation_id": self.correlation_id,
        }


def _is_production() -> bool:
    return os.environ.get("UNWIND_ENV", "").strip().lower() == "production"


def _parse_operator_tokens() -> dict[str, str]:
    """`UNWIND_OPERATOR_TOKENS="tok1:alice@example.com,tok2:svc-runner"`.

    Returns {token: principal}. A malformed pair is DROPPED, not guessed at:
    a typo that silently granted access to the literal string
    `"tok1:alice"` would be worse than one that grants nothing.
    """
    raw = os.environ.get("UNWIND_OPERATOR_TOKENS", "").strip()
    if not raw:
        return {}
    out: dict[str, str] = {}
    for pair in raw.split(","):
        token, sep, subject = pair.partition(":")
        if not sep or not token.strip() or not subject.strip():
            continue
        out[token.strip()] = subject.strip()
    return out


def _match_token(presented: str, table: dict[str, str]) -> str | None:
    """Constant-time comparison against every configured token.

    Deliberately does NOT short-circuit on the first match: iterating the
    whole table keeps the work independent of which token matched, and
    `compare_digest` keeps it independent of how many leading bytes are
    right.
    """
    found: str | None = None
    for token, subject in table.items():
        if hmac.compare_digest(token, presented):
            found = subject
    return found


def _normalise(subject: str, *, kind: str) -> str:
    prefix = HUMAN_PREFIX if kind == "human" else SERVICE_PREFIX
    return subject if subject.startswith(prefix) else f"{prefix}{subject}"


def authenticate(headers: dict[str, str]) -> Principal:
    """Resolve the caller, or raise. `headers` is a case-insensitive mapping
    (FastAPI's `request.headers` satisfies this).

    Raises `Unauthenticated` when nothing resolves. There is no branch that
    returns an anonymous or default `Principal`.
    """
    get = _header_getter(headers)
    correlation_id = (get(CORRELATION_HEADER) or uuid.uuid4().hex[:16]).strip()[:64]

    # 1. IAP, only when the deployment says it is actually behind IAP.
    if os.environ.get("UNWIND_TRUST_IAP_HEADER", "").strip() == "1":
        raw = (get(IAP_HEADER) or "").strip()
        if raw:
            # Google prefixes the value, e.g. "accounts.google.com:a@b.com".
            subject = raw.rpartition(":")[2] or raw
            return Principal(
                principal=_normalise(subject, kind="human"),
                kind="human",
                method="iap",
                correlation_id=correlation_id,
            )

    # 2. Bearer token.
    authz = (get("authorization") or "").strip()
    if authz.lower().startswith("bearer "):
        presented = authz[7:].strip()
        table = _parse_operator_tokens()
        if table and presented:
            subject = _match_token(presented, table)
            if subject is None:
                raise Unauthenticated("bearer token not recognised")
            kind = "service" if subject.startswith(SERVICE_PREFIX) else "human"
            return Principal(
                principal=_normalise(subject, kind=kind),
                kind=kind,
                method="bearer",
                correlation_id=correlation_id,
            )

    # 3. Explicit dev principal. Never available in production.
    dev = os.environ.get("UNWIND_DEV_PRINCIPAL", "").strip()
    if dev:
        if _is_production():
            raise Unauthenticated(
                "UNWIND_DEV_PRINCIPAL is set but UNWIND_ENV=production; "
                "the dev identity path is refused in production by construction."
            )
        return Principal(
            principal=_normalise(dev, kind="human"),
            kind="human",
            method="dev",
            correlation_id=correlation_id,
        )

    raise Unauthenticated(
        "no credential presented. Supply `Authorization: Bearer <token>` "
        "(see UNWIND_OPERATOR_TOKENS), or run behind IAP with "
        "UNWIND_TRUST_IAP_HEADER=1, or set UNWIND_DEV_PRINCIPAL for local development."
    )


def require_human(principal: Principal) -> Principal:
    """A human decision must come from a human principal.

    The Human Override Gate exists to put a person between an isolated agent
    and a re-minted warrant. A service token satisfying it would make the
    gate a formality, so this is enforced rather than documented.
    """
    if not principal.is_human:
        raise Unauthorized(
            f"principal {principal.principal!r} is a service identity; the "
            "human concurrence gate requires a human principal."
        )
    return principal


def auth_mode() -> dict[str, object]:
    """What this process will actually accept, for `/api/command-os/status`.

    Reports configuration, never a secret: token COUNT, never a token.
    """
    return {
        "env": os.environ.get("UNWIND_ENV", "development"),
        "iap_trusted": os.environ.get("UNWIND_TRUST_IAP_HEADER", "").strip() == "1",
        "bearer_tokens_configured": len(_parse_operator_tokens()),
        "dev_principal_configured": bool(os.environ.get("UNWIND_DEV_PRINCIPAL", "").strip()),
        "dev_principal_permitted": not _is_production(),
        "anonymous_mutation_possible": False,
    }


def _header_getter(headers):
    """FastAPI headers are already case-insensitive; a plain dict is not.
    One accessor so tests can pass either."""
    try:
        headers.get("x-probe-case-insensitivity")
        lowered = {str(k).lower(): v for k, v in headers.items()}
    except Exception:  # pragma: no cover -- defensive
        lowered = {}
    return lambda name: lowered.get(name.lower())


__all__ = [
    "CORRELATION_HEADER",
    "HUMAN_PREFIX",
    "IAP_HEADER",
    "SERVICE_PREFIX",
    "Principal",
    "Unauthenticated",
    "Unauthorized",
    "auth_mode",
    "authenticate",
    "require_human",
]
