"""The committed corpus matches its manifest, and its asserted properties hold.

The corpus is a deliverable. If it drifts from what corpus/README.md claims, the
claims in the README become false, which is the one failure this project cannot
afford.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
DATA = REPO / "corpus" / "data"


@pytest.fixture(scope="module")
def stats() -> dict:
    return json.loads((DATA / "stats.json").read_text(encoding="utf-8"))


def _jsonl(name: str) -> list[dict]:
    return [
        json.loads(line) for line in (DATA / name).read_text(encoding="utf-8").splitlines() if line
    ]


def test_corpus_is_committed_and_complete() -> None:
    for name in (
        "claims.jsonl",
        "conclusions.jsonl",
        "reverse_index.jsonl",
        "radius_truth.jsonl",
        "sources.jsonl",
        "stats.json",
        "MANIFEST.sha256",
    ):
        assert (DATA / name).is_file(), f"missing committed corpus file: {name}"


def test_manifest_matches_the_committed_bytes() -> None:
    manifest: dict[str, str] = {}
    for line in (DATA / "MANIFEST.sha256").read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        digest, name = line.split("  ", 1)
        manifest[name] = digest

    for name, expected in manifest.items():
        actual = hashlib.sha256((DATA / name).read_bytes()).hexdigest()
        assert actual == expected, f"{name} does not match MANIFEST.sha256"

    on_disk = {
        p.relative_to(DATA).as_posix()
        for p in DATA.rglob("*")
        if p.is_file() and p.name != "MANIFEST.sha256"
    }
    assert on_disk == set(manifest), "corpus files and manifest entries diverge"


def test_generator_is_deterministic() -> None:
    """Two builds from the same seed produce identical bytes."""
    from corpus.generate import SEED, build

    first = build(seed=SEED)
    second = build(seed=SEED)
    for key in ("claims", "conclusions", "reverse_index", "radius_truth", "sources"):
        a = json.dumps(first[key], sort_keys=True)
        b = json.dumps(second[key], sort_keys=True)
        assert a == b, f"{key} differs between two builds from seed {SEED}"


def test_counts_match_the_stats_file(stats: dict) -> None:
    assert len(_jsonl("claims.jsonl")) == stats["counts"]["claims"]
    assert len(_jsonl("conclusions.jsonl")) == stats["counts"]["conclusions"]
    assert len(_jsonl("reverse_index.jsonl")) == stats["counts"]["reverse_index_edges"]


def test_die_back_is_computed_from_the_committed_rows(stats: dict) -> None:
    """Recompute the die-back off radius_truth.jsonl rather than trusting stats."""
    truth = _jsonl("radius_truth.jsonl")
    scoreable = [r for r in truth if not r["unresolvable"]]
    material = [r for r in scoreable if r["material"]]
    die_back = 100.0 * (len(scoreable) - len(material)) / len(scoreable)

    assert len(truth) == stats["die_back"]["radius"]
    assert len(material) == stats["die_back"]["material_by_arithmetic"]
    assert round(die_back, 3) == stats["die_back"]["die_back_pct"]

    # The materiality rule itself: material <=> shock exceeds slack.
    shock = stats["hub_claim"]["shock_days"]
    for row in scoreable:
        assert row["material"] == (shock > row["slack_days"]), row["conclusion_id"]


def test_hub_radius_is_genuinely_transitive(stats: dict) -> None:
    depth = stats["depth"]["max_premise_chain_depth"]
    assert depth >= 3, f"max premise-chain depth is only {depth}"
    truth = _jsonl("radius_truth.jsonl")
    assert max(r["depth"] for r in truth) == depth
    assert stats["hub_claim"]["transitive_dependents"] > stats["hub_claim"]["direct_dependents"]


def test_reverse_index_holds_direct_edges_only() -> None:
    """The closure is eval ground truth, not a runtime shortcut."""
    assert all(row["depth"] == 1 for row in _jsonl("reverse_index.jsonl"))


def test_every_claim_has_a_non_empty_authority_scope() -> None:
    for claim in _jsonl("claims.jsonl"):
        assert claim["authority_scope"], f"{claim['claim_id']} has empty authority_scope"


def test_every_claim_carries_the_temporal_truth_fields() -> None:
    for claim in _jsonl("claims.jsonl"):
        for field in ("valid_from", "invalidated_at", "invalidation_reason"):
            assert field in claim, f"{claim['claim_id']} missing {field}"


def test_at_least_three_conclusions_are_unresolved(stats: dict) -> None:
    unresolved = [c for c in _jsonl("conclusions.jsonl") if c["status"] == "unresolved"]
    assert len(unresolved) >= 3
    assert len(unresolved) == stats["unresolved"]["count"]
    for conclusion in unresolved:
        assert conclusion["committed_lead_days"] is None


def test_one_of_each_reversibility_class_exists_with_money(stats: dict) -> None:
    by_id = {c["conclusion_id"]: c for c in _jsonl("conclusions.jsonl")}
    demonstrative = stats["demonstrative_reversibility"]
    assert set(demonstrative) == {"idempotent", "compensable", "irreversible", "mixed"}

    for reversibility, conclusion_id in demonstrative.items():
        if reversibility == "mixed":
            continue  # asserted separately below; its two effects disagree by design
        effect = by_id[conclusion_id]["external_effects"][0]
        assert effect["reversibility"] == reversibility

    for reversibility in ("compensable", "irreversible"):
        effect = by_id[demonstrative[reversibility]]["external_effects"][0]
        assert effect["amount_minor"] and effect["amount_minor"] > 0
        assert effect["currency"] == "USD"


def test_adversarial_artifact_is_stored_and_not_processed() -> None:
    artifact = json.loads(
        (DATA / "adversarial" / "forged_retraction.json").read_text(encoding="utf-8")
    )
    assert artifact["processed"] is False
    assert artifact["expected_verdict"] == "REFUSE"

    # It must not have leaked into the processed corpus.
    raw = (DATA / "claims.jsonl").read_text(encoding="utf-8")
    raw += (DATA / "conclusions.jsonl").read_text(encoding="utf-8")
    raw += (DATA / "reverse_index.jsonl").read_text(encoding="utf-8")
    assert artifact["artifact_id"] not in raw
    assert "zenith-freight" not in raw

    # And the reason it must be refused has to be structurally true: the source
    # holds no authority prefix matching the claim it targets.
    sources = {s["source_id"]: s for s in _jsonl("sources.jsonl")}
    claims = {c["claim_id"]: c for c in _jsonl("claims.jsonl")}
    forger = sources[artifact["purported_source_id"]]
    target = claims[artifact["targets_claim_id"]]
    assert artifact["purported_source_id"] not in target["authority_scope"]
    assert not any(target["canonical"].startswith(p) for p in forger["authority"])


def test_decisions_are_visibly_old(stats: dict) -> None:
    median_gap = stats["timing"]["median_decision_to_retraction_days"]
    assert median_gap > 60, f"median decision age is only {median_gap} days"


def test_the_mixed_case_carries_two_effects_of_opposite_fate() -> None:
    """One commitment, one recoverable effect, one that is simply gone.

    Every other conclusion in the corpus escaped exactly once, which makes each
    obligation wholly recoverable or wholly not. Without this case the product's
    central output could never show the distinction it exists to draw: something
    to re-issue printed beside something nobody can take back.
    """
    stats = json.loads((DATA / "stats.json").read_text(encoding="utf-8"))
    by_id = {c["conclusion_id"]: c for c in _jsonl("conclusions.jsonl")}
    mixed = by_id[stats["demonstrative_reversibility"]["mixed"]]

    effects = mixed["external_effects"]
    assert len(effects) == 2, "the mixed case does not have two effects"
    kinds = {e["reversibility"] for e in effects}
    assert kinds == {"idempotent", "irreversible"}, f"fates do not disagree: {kinds}"

    irreversible = next(e for e in effects if e["reversibility"] == "irreversible")
    assert irreversible["amount_minor"] > 0
    assert irreversible["currency"] == "USD"
