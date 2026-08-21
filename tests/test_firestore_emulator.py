"""Integration: the corpus loads into Firestore and the reverse index is walkable.

Skipped unless a Firestore emulator is answering. Run it with:

    make emulator            # in one terminal
    make test                # in another

This is the only test that touches a database, and it exists to prove the one
query T0 depends on: given a claim, read its dependents ordered by depth then
weight. Everything else in Task 1 is in-process.
"""

from __future__ import annotations

import json
import os
import socket
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
DATA = REPO / "corpus" / "data"
HUB_CLAIM_ID = "clm_000000"


def _emulator_up() -> bool:
    host = os.environ.get("FIRESTORE_EMULATOR_HOST", "localhost:8080")
    hostname, _, port = host.partition(":")
    try:
        with socket.create_connection((hostname, int(port or 8080)), timeout=1.0):
            return True
    except OSError:
        return False


pytestmark = pytest.mark.skipif(
    not _emulator_up(),
    reason="Firestore emulator not running; start it with `make emulator`",
)


@pytest.fixture(scope="module")
def loaded():
    """Load a slice of the corpus into the emulator under a scratch project."""
    os.environ.setdefault("FIRESTORE_EMULATOR_HOST", "localhost:8080")
    os.environ["UNWIND_PROJECT_ID"] = "unwind-emulator-test"

    from lib import firestore as fs
    from lib.config import reset_config_cache
    from lib.schema import Claim, Conclusion, ReverseEdge, Source

    reset_config_cache()
    fs.reset_client()

    def rows(name: str) -> list[dict]:
        return [
            json.loads(line)
            for line in (DATA / name).read_text(encoding="utf-8").splitlines()
            if line
        ]

    sources = [Source(**r) for r in rows("sources.jsonl")]
    all_claims = rows("claims.jsonl")
    all_edges = rows("reverse_index.jsonl")

    hub_edges = [e for e in all_edges if e["claim_id"] == HUB_CLAIM_ID]
    dependent_ids = {e["conclusion_id"] for e in hub_edges}
    conclusions = [
        Conclusion(**c) for c in rows("conclusions.jsonl") if c["conclusion_id"] in dependent_ids
    ]
    claims = [Claim(**c) for c in all_claims if c["claim_id"] == HUB_CLAIM_ID]

    fs.put_sources(sources)
    fs.put_claims(claims)
    fs.put_conclusions(conclusions)
    fs.put_reverse_edges(ReverseEdge(**e) for e in hub_edges)

    yield {"hub_edges": hub_edges, "conclusions": conclusions}

    fs.reset_client()
    reset_config_cache()


def test_claim_round_trips_with_its_temporal_truth_fields(loaded) -> None:
    from lib import firestore as fs

    claim = fs.get_claim(HUB_CLAIM_ID)
    assert claim is not None
    assert claim.canonical == "supplier_K.lead_time_days"
    assert claim.value == 11
    assert claim.valid_from is not None
    assert claim.invalidated_at is None
    assert claim.invalidation_reason is None
    # Narrowed in Task 3: the master supply agreement governs the CLAUSES, not
    # how long the supplier actually takes to ship. That distinction is what
    # makes the partial-authority attack refusable.
    assert claim.authority_scope == ["src_supplier_K"]


def test_reverse_index_traversal_returns_every_dependent(loaded) -> None:
    """The T0 query. No model, no arithmetic -- just the walk."""
    from lib import firestore as fs

    found = list(fs.iter_dependents(HUB_CLAIM_ID))
    assert len(found) == len(loaded["hub_edges"])
    assert {e.conclusion_id for e in found} == {e["conclusion_id"] for e in loaded["hub_edges"]}
    # Ordered shallowest first, then heaviest -- the order the UI fills in.
    depths = [e.depth for e in found]
    assert depths == sorted(depths)


def test_source_authority_round_trips(loaded) -> None:
    from lib import firestore as fs

    broker = fs.get_source("src_broker_Z")
    assert broker is not None
    assert broker.authority == ["freight_broker_Z."]
    # The structural reason the forged retraction must be refused.
    assert not any("supplier_K".startswith(p) for p in broker.authority)
