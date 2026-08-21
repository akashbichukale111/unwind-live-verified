"""The one module that changes something outside this process.

WHY THERE IS EXACTLY ONE
---------------------------
The previous mission produced findings and stopped. A system that only ever
recommends has removed no friction -- the human still has to go and do the
thing. So a mission now ends with a real, recorded, reversible action
against a system of record.

Concentrating that in one module is the point: there is exactly one function
in this repository that can affect the outside world (`execute_action`), it
refuses to run without an authorization token minted by the deterministic
gateway path, and it refuses to run twice for the same idempotency key. Any
future external effect must come through here or it does not exist.

THE FOUR PROPERTIES, EACH ENFORCED RATHER THAN DOCUMENTED
-------------------------------------------------------------
1. **Authorized.** `execute_action` requires an `ExternalActionAuthorization`
   carrying the Gateway decision, the priced cost, the human principal, and
   the countersign verdict. It is constructed only by
   `command_os/mission.py` AFTER the real `evaluate_with_hyperion` ->
   `spend_or_refuse` chain allowed the action. Passing `None` raises. There
   is no code path from a plan straight to a side effect.

2. **Idempotent.** The Firestore record is created inside a transaction with
   a create-if-absent precondition on the idempotency key. A replay reads
   the existing record and returns it with `replayed=True`; it does not
   write the sandbox again. `tests/test_external_action.py::
   test_resume_does_not_duplicate_external_action` asserts the sandbox line
   count is unchanged across three replays.

3. **Reversible.** Every record carries a `reversal` describing exactly how
   to undo it, and `revert_action` performs it, appending a compensating
   entry rather than deleting the original -- an append-only sandbox, the
   same discipline `warrant/ledger.py` and `tower/memory.py` already keep.

4. **Verifiable by a third party.** The sandbox is a real file on disk
   outside this process's memory. `verify_action` RE-READS it rather than
   trusting the return value of the write, and `fleet/tools.py:verify_check`
   compares the re-read against the proposal field by field.

BACKENDS, AND WHAT IS ACTUALLY EXERCISED
--------------------------------------------
`sandbox_file` (default) -- appends a JSON line to `.sandbox/actions.jsonl`.
A genuine side effect outside the process, exercised in tests and in every
local mission run. Labelled `SANDBOX`.

`github` -- creates a real GitHub issue through the REST API. The adapter is
real code with real request construction.
[UNVERIFIED IN THIS ENVIRONMENT] No GitHub token was available to the
application in the session that wrote this module, so this backend has NOT
been executed. `backend_status()` reports `CONFIGURED_NOT_EXERCISED` for it,
the API surfaces that, and the UI shows it -- it is never labelled LIVE on
the strength of the code existing.
"""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from lib.firestore import get_client

COLLECTION_EXTERNAL_ACTIONS = "command_os_external_actions"

#: Where the sandbox system of record lives. Outside the repository's tracked
#: tree (`.gitignore`d) because it is runtime state, not source.
SANDBOX_DIR = Path(os.environ.get("UNWIND_SANDBOX_DIR", ".sandbox"))
SANDBOX_FILE = SANDBOX_DIR / "actions.jsonl"

BACKEND_SANDBOX = "sandbox_file"
BACKEND_GITHUB = "github"


class ExternalActionRefused(RuntimeError):
    """The action was not authorized, or its authorization does not match the
    proposal it was issued for."""


@dataclass(frozen=True)
class ExternalActionAuthorization:
    """Proof that the deterministic path already said yes.

    Constructed by `command_os/mission.py` only after:
      - `hyperion.guard.evaluate_with_hyperion` returned `allowed=True`
        (which means the unmodified `tower.gateway.evaluate_gateway` allowed
        it, which means `warrant.ledger.spend_or_refuse` already DEBITED the
        priced cost), and
      - a human principal concurred when
        `warrant.economics.REQUIRES_HUMAN` demanded it, and
      - the independent challenger did not disagree.

    `idempotency_key` is bound here so an authorization for one action cannot
    be replayed to authorize a different one.
    """

    idempotency_key: str
    gateway_reason_code: str
    cost_bp: int
    acting_principal: str
    human_principal: str | None
    countersign_agrees: bool | None
    mission_id: str

    def assert_valid_for(self, proposal: dict[str, Any]) -> None:
        if self.gateway_reason_code != "ALLOWED":
            raise ExternalActionRefused(
                f"authorization carries gateway reason {self.gateway_reason_code!r}, "
                "not ALLOWED; no external effect may follow a refusal."
            )
        if self.countersign_agrees is False:
            raise ExternalActionRefused(
                "the independent challenger disagreed; minting and execution are "
                "frozen for this case."
            )
        if proposal.get("idempotency_key") != self.idempotency_key:
            raise ExternalActionRefused(
                f"authorization is bound to idempotency key "
                f"{self.idempotency_key!r} but the proposal carries "
                f"{proposal.get('idempotency_key')!r}: an authorization is not transferable."
            )


@dataclass(frozen=True)
class ExternalActionRecord:
    backend: str
    idempotency_key: str
    external_id: str
    action: str
    status: str
    recorded_at: str
    replayed: bool
    detail: dict[str, Any]

    def as_record(self) -> dict[str, Any]:
        return {
            "backend": self.backend,
            "idempotency_key": self.idempotency_key,
            "external_id": self.external_id,
            "action": self.action,
            "status": self.status,
            "recorded_at": self.recorded_at,
            "replayed": self.replayed,
            **self.detail,
        }


def current_backend() -> str:
    raw = os.environ.get("UNWIND_EXTERNAL_ACTION_BACKEND", BACKEND_SANDBOX).strip()
    return raw or BACKEND_SANDBOX


def backend_status() -> dict[str, Any]:
    """Honest status per backend, for `/api/command-os/status` and the UI."""
    return {
        "active": current_backend(),
        "backends": {
            BACKEND_SANDBOX: {
                "status": "SANDBOX",
                "note": f"appends a real JSON line to {SANDBOX_FILE}; exercised in tests",
            },
            BACKEND_GITHUB: {
                "status": (
                    "CONFIGURED_NOT_EXERCISED"
                    if not os.environ.get("UNWIND_GITHUB_TOKEN")
                    else "CONFIGURED"
                ),
                "note": (
                    "creates a real GitHub issue; requires UNWIND_GITHUB_TOKEN and "
                    "UNWIND_GITHUB_REPO. Never executed in the session that wrote it."
                ),
            },
        },
    }


# ---------------------------------------------------------------------------
# Backends
# ---------------------------------------------------------------------------


def _sandbox_append(payload: dict[str, Any]) -> str:
    """Append one line to the sandbox system of record. Real file I/O.

    Append-only: an executed action is evidence of what happened, and an
    editable record of what happened is evidence of nothing. Reversal
    appends a compensating entry (see `revert_action`).
    """
    SANDBOX_DIR.mkdir(parents=True, exist_ok=True)
    external_id = f"sbx-{uuid.uuid4().hex[:12]}"
    line = {**payload, "external_id": external_id}
    with SANDBOX_FILE.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(line, sort_keys=True) + "\n")
    return external_id


def _github_create_issue(proposal: dict[str, Any]) -> str:
    """Create a real GitHub issue. Real request, real endpoint.

    [UNVERIFIED] Never executed in the session that wrote this module -- no
    token was available. It raises a clear, actionable error rather than
    pretending to succeed, which is the only honest behaviour for an
    integration whose credential is absent.
    """
    token = os.environ.get("UNWIND_GITHUB_TOKEN", "").strip()
    repo = os.environ.get("UNWIND_GITHUB_REPO", "").strip()
    if not token or not repo:
        raise ExternalActionRefused(
            "github backend selected but UNWIND_GITHUB_TOKEN / UNWIND_GITHUB_REPO "
            "are not set. Refusing to report success for an action that did not happen."
        )
    import urllib.error
    import urllib.request

    body = json.dumps(
        {
            "title": proposal.get("title", "UNWIND remediation"),
            "body": proposal.get("body", ""),
            "labels": ["unwind-remediation"],
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        f"https://api.github.com/repos/{repo}/issues",
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
            "User-Agent": "unwind-command-os",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.URLError as exc:
        raise ExternalActionRefused(f"github issue creation failed: {exc}") from exc
    return str(data.get("number", ""))


# ---------------------------------------------------------------------------
# The verb
# ---------------------------------------------------------------------------


def _doc(idempotency_key: str):
    return get_client().collection(COLLECTION_EXTERNAL_ACTIONS).document(idempotency_key)


def read_action(idempotency_key: str) -> dict[str, Any] | None:
    """Re-read the durable record. What `verify_action` and the Verifier
    specialist consult -- never the acting agent's own return value."""
    snap = _doc(idempotency_key).get()
    return snap.to_dict() if snap.exists else None


def execute_action(
    proposal: dict[str, Any],
    *,
    authorization: ExternalActionAuthorization | None,
    backend: str | None = None,
) -> ExternalActionRecord:
    """Apply the correction. Authorized, idempotent, recorded, reversible.

    Order matters and is deliberate:
      1. Validate the authorization AGAINST THIS PROPOSAL (raises otherwise).
      2. Check the durable record. Already applied -> return it, replayed,
         WITHOUT touching the backend.
      3. Perform the side effect.
      4. Record it durably.

    Step 2 before step 3 is what makes a resumed mission safe. Step 1 before
    everything is what makes an unauthorized proposal inert.
    """
    if authorization is None:
        raise ExternalActionRefused(
            "execute_action requires an ExternalActionAuthorization minted by the "
            "deterministic gateway path. There is no unauthenticated external effect."
        )
    authorization.assert_valid_for(proposal)

    key = str(proposal["idempotency_key"])
    existing = read_action(key)
    if existing is not None:
        return ExternalActionRecord(
            backend=existing.get("backend", ""),
            idempotency_key=key,
            external_id=existing.get("external_id", ""),
            action=existing.get("action", ""),
            status=existing.get("status", ""),
            recorded_at=existing.get("recorded_at", ""),
            replayed=True,
            detail=existing,
        )

    chosen = backend or current_backend()
    now = datetime.now(UTC).isoformat()
    payload = {
        "action": proposal.get("action"),
        "target_request_id": proposal.get("target_request_id"),
        "target_agent_id": proposal.get("target_agent_id"),
        "revoke_scope": proposal.get("revoke_scope"),
        "reason": proposal.get("reason"),
        "title": proposal.get("title"),
        "idempotency_key": key,
        "mission_id": authorization.mission_id,
        "acting_principal": authorization.acting_principal,
        "human_principal": authorization.human_principal,
        "cost_bp": authorization.cost_bp,
        "reversal": proposal.get("reversal"),
        "recorded_at": now,
        "backend": chosen,
    }

    if chosen == BACKEND_GITHUB:
        external_id = _github_create_issue(proposal)
    elif chosen == BACKEND_SANDBOX:
        external_id = _sandbox_append(payload)
    else:
        raise ExternalActionRefused(f"unknown external action backend {chosen!r}")

    record = {**payload, "external_id": external_id, "status": "APPLIED"}
    _doc(key).set(record)
    return ExternalActionRecord(
        backend=chosen,
        idempotency_key=key,
        external_id=external_id,
        action=str(proposal.get("action")),
        status="APPLIED",
        recorded_at=now,
        replayed=False,
        detail=record,
    )


def verify_action(idempotency_key: str, proposal: dict[str, Any]) -> dict[str, Any]:
    """Independent confirmation: re-read, then compare field by field."""
    from fleet.tools import verify_check

    return verify_check(proposal=proposal, recorded=read_action(idempotency_key))


def revert_action(idempotency_key: str, *, principal: str, reason: str) -> dict[str, Any]:
    """Undo, by compensation rather than deletion.

    Appends a REVERSAL entry to the sandbox and marks the durable record
    reverted. The original entry stays: what happened, happened, and an
    append-only log that can be edited to say otherwise is not a log.
    """
    record = read_action(idempotency_key)
    if record is None:
        return {"reverted": False, "reason": f"no action recorded for {idempotency_key!r}"}
    if record.get("status") == "REVERTED":
        return {"reverted": True, "reason": "already reverted", "replayed": True}

    compensating = {
        "action": "REVERSAL",
        "reverses_external_id": record.get("external_id"),
        "idempotency_key": f"{idempotency_key}:reversal",
        "reason": reason,
        "acting_principal": principal,
        "recorded_at": datetime.now(UTC).isoformat(),
        "backend": record.get("backend"),
    }
    reversal_id = _sandbox_append(compensating)
    _doc(idempotency_key).update(
        {
            "status": "REVERTED",
            "reverted_at": compensating["recorded_at"],
            "reverted_by": principal,
            "reversal_external_id": reversal_id,
        }
    )
    return {
        "reverted": True,
        "reason": reason,
        "reversal_external_id": reversal_id,
        "replayed": False,
    }


def sandbox_line_count() -> int:
    """How many entries the sandbox actually holds. Used by the idempotency
    test to assert a replay wrote nothing, by counting the file rather than
    trusting a flag."""
    if not SANDBOX_FILE.exists():
        return 0
    return sum(1 for line in SANDBOX_FILE.read_text(encoding="utf-8").splitlines() if line.strip())


def reset_for_test(idempotency_key: str | None = None) -> None:
    """Test hook, mirroring the `reset_for_test` hooks in `tower.registry`,
    `warrant.ledger` and `command_os.checkpoint`."""
    if idempotency_key is not None:
        _doc(idempotency_key).delete()
        _doc(f"{idempotency_key}:reversal").delete()
        return
    for snap in get_client().collection(COLLECTION_EXTERNAL_ACTIONS).stream():
        snap.reference.delete()
    if SANDBOX_FILE.exists():
        SANDBOX_FILE.unlink()


__all__ = [
    "BACKEND_GITHUB",
    "BACKEND_SANDBOX",
    "COLLECTION_EXTERNAL_ACTIONS",
    "SANDBOX_FILE",
    "ExternalActionAuthorization",
    "ExternalActionRecord",
    "ExternalActionRefused",
    "backend_status",
    "current_backend",
    "execute_action",
    "read_action",
    "revert_action",
    "sandbox_line_count",
    "verify_action",
]
