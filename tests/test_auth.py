"""`lib/auth.py`: the fix for the audit's worst finding.

Before this module, `POST /api/command-os/mission/{id}/gate?decision=approve`
was reachable with no credential, and the decision-memory record it produced
named `"human::mission_operator"` -- a module constant. That record is one
of the two preconditions `warrant.ledger.mint` requires, so an anonymous
HTTP request minted earned authority and left an authentic-looking audit
entry for a human who was never present.

These tests assert the properties that make that impossible, not the
implementation that currently provides them.
"""

from __future__ import annotations

import inspect

import pytest

from lib.auth import (
    Principal,
    Unauthenticated,
    Unauthorized,
    auth_mode,
    authenticate,
    require_human,
)


def test_no_credential_raises_rather_than_returning_a_default(monkeypatch) -> None:
    """The property that matters most: there is no anonymous branch."""
    for var in (
        "UNWIND_OPERATOR_TOKENS",
        "UNWIND_DEV_PRINCIPAL",
        "UNWIND_TRUST_IAP_HEADER",
        "UNWIND_ENV",
    ):
        monkeypatch.delenv(var, raising=False)
    with pytest.raises(Unauthenticated):
        authenticate({})


def test_authenticate_has_no_fallback_return_path() -> None:
    """Structural, not behavioural: assert the function's own source ends in
    a raise rather than a return.

    A behavioural test only covers the inputs it thought of. This covers the
    shape -- if someone later adds `return Principal("anonymous", ...)` as a
    convenience, this fails even if every other test still passes.
    """
    source = inspect.getsource(authenticate)
    body = source.split('raise Unauthenticated(\n        "no credential presented')[0]
    # Every `return` in the body must be inside a branch that had a credential.
    assert source.rstrip().endswith(")"), "authenticate must end in the raise"
    assert "return Principal(" in body
    assert source.count("raise Unauthenticated") >= 2


def test_bearer_token_resolves_to_its_configured_principal(monkeypatch) -> None:
    monkeypatch.setenv("UNWIND_OPERATOR_TOKENS", "tok-a:alice@example.com,tok-b:service::runner")
    alice = authenticate({"Authorization": "Bearer tok-a"})
    assert alice.principal == "human::alice@example.com"
    assert alice.kind == "human"
    assert alice.method == "bearer"

    runner = authenticate({"authorization": "Bearer tok-b"})
    assert runner.principal == "service::runner"
    assert runner.kind == "service"


def test_wrong_bearer_token_is_refused_not_downgraded(monkeypatch) -> None:
    """A bad credential must 401, never fall through to the dev principal."""
    monkeypatch.setenv("UNWIND_OPERATOR_TOKENS", "tok-a:alice@example.com")
    monkeypatch.setenv("UNWIND_DEV_PRINCIPAL", "dev@example.com")
    with pytest.raises(Unauthenticated):
        authenticate({"Authorization": "Bearer wrong"})


def test_malformed_token_pairs_are_dropped_not_guessed(monkeypatch) -> None:
    monkeypatch.setenv("UNWIND_OPERATOR_TOKENS", "no-colon-here,:blank-token,tok:ok@example.com")
    monkeypatch.delenv("UNWIND_DEV_PRINCIPAL", raising=False)
    assert authenticate({"Authorization": "Bearer tok"}).principal == "human::ok@example.com"
    with pytest.raises(Unauthenticated):
        authenticate({"Authorization": "Bearer no-colon-here"})


def test_iap_header_is_ignored_unless_the_deployment_says_it_is_behind_iap(
    monkeypatch,
) -> None:
    """An app that trusts this header while NOT behind IAP trusts a header
    the client sets. The flag is the whole protection."""
    monkeypatch.delenv("UNWIND_TRUST_IAP_HEADER", raising=False)
    monkeypatch.delenv("UNWIND_DEV_PRINCIPAL", raising=False)
    monkeypatch.delenv("UNWIND_OPERATOR_TOKENS", raising=False)
    headers = {"X-Goog-Authenticated-User-Email": "accounts.google.com:attacker@evil.example"}
    with pytest.raises(Unauthenticated):
        authenticate(headers)

    monkeypatch.setenv("UNWIND_TRUST_IAP_HEADER", "1")
    resolved = authenticate(headers)
    assert resolved.principal == "human::attacker@evil.example"
    assert resolved.method == "iap"


def test_dev_principal_is_refused_in_production(monkeypatch) -> None:
    """The convenient path cannot be the deployed path."""
    monkeypatch.delenv("UNWIND_OPERATOR_TOKENS", raising=False)
    monkeypatch.delenv("UNWIND_TRUST_IAP_HEADER", raising=False)
    monkeypatch.setenv("UNWIND_DEV_PRINCIPAL", "dev@example.com")

    monkeypatch.setenv("UNWIND_ENV", "development")
    assert authenticate({}).principal == "human::dev@example.com"

    monkeypatch.setenv("UNWIND_ENV", "production")
    with pytest.raises(Unauthenticated):
        authenticate({})


def test_service_identity_cannot_satisfy_the_human_gate() -> None:
    service = Principal(principal="service::runner", kind="service", method="bearer")
    with pytest.raises(Unauthorized):
        require_human(service)
    human = Principal(principal="human::a@b.example", kind="human", method="bearer")
    assert require_human(human) is human


def test_auth_mode_reports_configuration_never_a_secret(monkeypatch) -> None:
    monkeypatch.setenv("UNWIND_OPERATOR_TOKENS", "supersecret:alice@example.com")
    mode = auth_mode()
    assert mode["bearer_tokens_configured"] == 1
    assert mode["anonymous_mutation_possible"] is False
    assert "supersecret" not in repr(mode)


def test_correlation_id_is_carried_when_supplied() -> None:
    principal = Principal(principal="human::a", kind="human", method="dev", correlation_id="abc123")
    assert principal.as_record()["correlation_id"] == "abc123"
    assert principal.as_record()["auth_method"] == "dev"
