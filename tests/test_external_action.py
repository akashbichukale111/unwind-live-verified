"""`command_os/external.py`: the one module that can change the outside world.

Every test here is about a property an auditor would want proven rather
than asserted: that an unauthorized proposal is inert, that a replay writes
nothing, that a reversal compensates rather than deletes, and that
verification re-reads instead of trusting the writer.
"""

from __future__ import annotations

import json
import os
import socket

import pytest

from command_os.external import (
    ExternalActionAuthorization,
    ExternalActionRefused,
    backend_status,
    execute_action,
    read_action,
    reset_for_test,
    revert_action,
    sandbox_line_count,
    verify_action,
)


def _emulator_up() -> bool:
    host = os.environ.get("FIRESTORE_EMULATOR_HOST", "localhost:8080")
    hostname, _, port = host.partition(":")
    try:
        with socket.create_connection((hostname, int(port or 8080)), timeout=1.0):
            return True
    except OSError:
        return False


requires_emulator = pytest.mark.skipif(
    not _emulator_up(), reason="Firestore emulator not running; start it with `make emulator`"
)

KEY = "test-mission:req-8802:revoke"

PROPOSAL = {
    "action": "REVOKE_CAPABILITY_REQUEST",
    "target_request_id": "req-8802",
    "target_agent_id": "fleet_recon",
    "revoke_scope": "finance.secret_read",
    "reason": "outside registered scope",
    "idempotency_key": KEY,
    "reversible": True,
    "reversal": "re-grant finance.secret_read to fleet_recon",
    "title": "Revoke out-of-scope request req-8802",
    "body": "test",
}


def _auth(**overrides) -> ExternalActionAuthorization:
    base = {
        "idempotency_key": KEY,
        "gateway_reason_code": "ALLOWED",
        "cost_bp": 73,
        "acting_principal": "agent::fleet_remediation",
        "human_principal": "human::kim@ops.example",
        "countersign_agrees": True,
        "mission_id": "test-mission",
    }
    base.update(overrides)
    return ExternalActionAuthorization(**base)


@pytest.fixture(autouse=True)
def _clean():
    if _emulator_up():
        reset_for_test()
    yield
    if _emulator_up():
        reset_for_test()


# ===========================================================================
# Authorization
# ===========================================================================


@requires_emulator
def test_no_authorization_means_no_side_effect() -> None:
    """There is no code path from a proposal straight to an external effect."""
    before = sandbox_line_count()
    with pytest.raises(ExternalActionRefused, match="requires an ExternalActionAuthorization"):
        execute_action(PROPOSAL, authorization=None)
    assert sandbox_line_count() == before


@requires_emulator
def test_a_refused_gateway_decision_cannot_authorize_anything() -> None:
    before = sandbox_line_count()
    with pytest.raises(ExternalActionRefused, match="not ALLOWED"):
        execute_action(PROPOSAL, authorization=_auth(gateway_reason_code="SCOPE_EXCEEDED"))
    assert sandbox_line_count() == before


@requires_emulator
def test_a_challenger_disagreement_freezes_execution() -> None:
    before = sandbox_line_count()
    with pytest.raises(ExternalActionRefused, match="challenger disagreed"):
        execute_action(PROPOSAL, authorization=_auth(countersign_agrees=False))
    assert sandbox_line_count() == before


@requires_emulator
def test_an_authorization_is_not_transferable_to_another_action() -> None:
    """An authorization minted for one action must not be replayed to
    authorize a different one -- otherwise the gateway check is a formality
    attached to whichever proposal arrives next."""
    other = {**PROPOSAL, "idempotency_key": "some-other-key", "action": "DELETE_EVERYTHING"}
    with pytest.raises(ExternalActionRefused, match="not transferable"):
        execute_action(other, authorization=_auth())


# ===========================================================================
# Idempotency
# ===========================================================================


@requires_emulator
def test_resume_does_not_duplicate_external_action() -> None:
    """Counted on the FILE, not on a flag. A replay that returned
    `replayed=True` while still appending a line would pass a flag-based
    test and fail this one."""
    first = execute_action(PROPOSAL, authorization=_auth())
    assert first.replayed is False
    after_first = sandbox_line_count()
    assert after_first >= 1

    for _ in range(3):
        again = execute_action(PROPOSAL, authorization=_auth())
        assert again.replayed is True
        assert again.external_id == first.external_id

    assert sandbox_line_count() == after_first, (
        "a replay wrote to the sandbox; the idempotency key did not hold"
    )


@requires_emulator
def test_the_durable_record_is_created_once_and_read_back_identically() -> None:
    record = execute_action(PROPOSAL, authorization=_auth())
    stored = read_action(KEY)
    assert stored is not None
    assert stored["external_id"] == record.external_id
    assert stored["status"] == "APPLIED"
    assert stored["human_principal"] == "human::kim@ops.example"
    assert stored["mission_id"] == "test-mission"


# ===========================================================================
# Verification
# ===========================================================================


@requires_emulator
def test_verification_reads_the_record_rather_than_trusting_the_writer() -> None:
    execute_action(PROPOSAL, authorization=_auth())
    result = verify_action(KEY, PROPOSAL)
    assert result["verified"] is True
    assert result["mismatches"] == []


@requires_emulator
def test_verification_fails_when_nothing_was_recorded() -> None:
    result = verify_action("never-executed", PROPOSAL)
    assert result["verified"] is False
    assert "record_missing" in result["mismatches"]


@requires_emulator
def test_verification_names_the_field_that_diverged() -> None:
    """A bare boolean would tell an operator nothing about what went wrong."""
    execute_action(PROPOSAL, authorization=_auth())
    tampered = {**PROPOSAL, "target_agent_id": "fleet_remediation"}
    result = verify_action(KEY, tampered)
    assert result["verified"] is False
    assert any("target_agent_id" in m for m in result["mismatches"])


# ===========================================================================
# Reversal
# ===========================================================================


@requires_emulator
def test_reversal_compensates_and_never_deletes() -> None:
    """An append-only system of record: what happened, happened."""
    original = execute_action(PROPOSAL, authorization=_auth())
    lines_before = sandbox_line_count()

    result = revert_action(KEY, principal="human::kim@ops.example", reason="false positive")
    assert result["reverted"] is True
    assert sandbox_line_count() == lines_before + 1, "reversal must APPEND, not remove"

    stored = read_action(KEY)
    assert stored["status"] == "REVERTED"
    assert stored["reverted_by"] == "human::kim@ops.example"

    from command_os.external import SANDBOX_FILE

    entries = [json.loads(line) for line in SANDBOX_FILE.read_text().splitlines() if line.strip()]
    assert any(e.get("action") == "REVERSAL" for e in entries)
    assert any(e.get("external_id") == original.external_id for e in entries), (
        "the original entry was removed; the sandbox is not append-only"
    )


@requires_emulator
def test_reverting_twice_is_a_no_op() -> None:
    execute_action(PROPOSAL, authorization=_auth())
    revert_action(KEY, principal="human::kim@ops.example", reason="first")
    lines = sandbox_line_count()
    second = revert_action(KEY, principal="human::kim@ops.example", reason="second")
    assert second["reverted"] is True
    assert second.get("replayed") is True
    assert sandbox_line_count() == lines


@requires_emulator
def test_reverting_something_that_never_happened_says_so() -> None:
    result = revert_action("never", principal="human::x", reason="y")
    assert result["reverted"] is False


# ===========================================================================
# Honest backend status
# ===========================================================================


def test_github_backend_is_never_labelled_live_without_a_token(monkeypatch) -> None:
    """The integration exists; it has not been exercised. The status must say
    so rather than implying otherwise."""
    monkeypatch.delenv("UNWIND_GITHUB_TOKEN", raising=False)
    status = backend_status()
    assert status["backends"]["github"]["status"] == "CONFIGURED_NOT_EXERCISED"
    assert status["backends"]["sandbox_file"]["status"] == "SANDBOX"


def test_github_backend_refuses_rather_than_faking_success(monkeypatch) -> None:
    monkeypatch.setenv("UNWIND_EXTERNAL_ACTION_BACKEND", "github")
    monkeypatch.delenv("UNWIND_GITHUB_TOKEN", raising=False)
    from command_os.external import _github_create_issue

    with pytest.raises(ExternalActionRefused, match="Refusing to report success"):
        _github_create_issue(PROPOSAL)


@requires_emulator
def test_an_unknown_backend_is_refused_not_silently_skipped(monkeypatch) -> None:
    monkeypatch.setenv("UNWIND_EXTERNAL_ACTION_BACKEND", "carrier_pigeon")
    with pytest.raises(ExternalActionRefused, match="unknown external action backend"):
        execute_action(PROPOSAL, authorization=_auth())
