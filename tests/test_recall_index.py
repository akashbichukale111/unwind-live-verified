"""Retrieval: does it SELECT, or does it load everything and call it retrieval?

The central assertion is `test_retrieval_selects_rather_than_loading`. It
builds a corpus far larger than any budget, asks one question, and checks
three things: the right records came back, the wrong ones did not, and the
result says how many it left behind.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from recall.index import search, tokenize
from recall.schema import KnowledgeRecord, RecordKind, Standing

NOW = datetime(2026, 8, 20, 12, 0, tzinfo=UTC)


def _record(
    *,
    subject: str,
    statement: str,
    kind: RecordKind = RecordKind.SCOPE_ESCALATION,
    standing: Standing = Standing.CAUTION,
    mission_id: str = "mission_x",
    objective_class: str = "SECURITY_INVESTIGATION",
    age_seconds: float = 0.0,
    seq: int = 1,
) -> KnowledgeRecord:
    return KnowledgeRecord(
        record_id=KnowledgeRecord.make_id(
            mission_id=mission_id,
            kind=kind,
            subject=subject,
            checkpoint_seq=seq,
            statement=statement,
        ),
        kind=kind,
        standing=standing,
        subject=subject,
        statement=statement,
        mission_id=mission_id,
        objective_class=objective_class,
        checkpoint_seq=seq,
        observed_at=NOW - timedelta(seconds=age_seconds),
    )


def _big_corpus(n: int = 500) -> list[KnowledgeRecord]:
    """A corpus of `n` records about `n` different subjects, exactly one of
    which is about the thing the query asks about."""
    corpus = [
        _record(
            subject=f"agent_{i:04d}",
            statement=f"Agent agent_{i:04d} completed a routine read on dataset ds_{i:04d}.",
            kind=RecordKind.EVIDENCE_COVERAGE,
            standing=Standing.OBSERVED,
            mission_id=f"mission_{i:04d}",
            age_seconds=float(i),
            seq=i,
        )
        for i in range(n - 2)
    ]
    corpus.append(
        _record(
            subject="fleet_recon",
            statement=(
                "Agent fleet_recon requested 'finance.secret_read', outside its registered "
                "scope, on request 'req-8802' at risk class 'HIGH'."
            ),
            mission_id="mission_needle",
            age_seconds=10.0,
            seq=7,
        )
    )
    corpus.append(
        _record(
            subject="fleet_recon",
            statement=(
                "Agent fleet_recon was ISOLATED after requesting 'finance.secret_read' with "
                "147 tool calls on dataset 'finance'; the Gateway refused it."
            ),
            kind=RecordKind.AGENT_ISOLATION,
            mission_id="mission_needle",
            age_seconds=5.0,
            seq=9,
        )
    )
    return corpus


# ===========================================================================
# THE central claim
# ===========================================================================


def test_retrieval_selects_rather_than_loading() -> None:
    corpus = _big_corpus(500)
    result = search(
        "fleet_recon finance.secret_read escalation", corpus, k=5, char_budget=1200, now=NOW
    )

    assert result.considered == 500
    assert len(result.selected) <= 5
    assert result.selection_ratio <= 0.01, (
        f"{len(result.selected)} of {result.considered} is not selection"
    )
    # The two needles are the two highest-ranked, and they are the ONLY
    # records about fleet_recon.
    subjects = [item.record.subject for item in result.selected]
    assert subjects[:2] == ["fleet_recon", "fleet_recon"]
    # And the result says what it left behind, rather than implying nothing
    # was left behind.
    assert result.zero_scored + result.dropped_for_budget + len(result.selected) == 500
    assert result.zero_scored > 400


def test_the_character_budget_binds_and_the_result_says_so() -> None:
    corpus = _big_corpus(50)
    tight = search("agent dataset routine read", corpus, k=40, char_budget=200, now=NOW)
    assert tight.chars_returned <= 200
    assert tight.dropped_for_budget > 0, "a budget that never binds is not a budget"
    assert len(tight.selected) < 40


def test_retrieval_is_deterministic() -> None:
    corpus = _big_corpus(120)
    a = search("fleet_recon escalation", corpus, k=5, now=NOW)
    b = search("fleet_recon escalation", corpus, k=5, now=NOW)
    assert [x.record.record_id for x in a.selected] == [y.record.record_id for y in b.selected]
    assert [x.score for x in a.selected] == [y.score for y in b.selected]


def test_every_selected_record_carries_its_provenance() -> None:
    """A retrieved fact with no mission behind it is a rumour."""
    result = search("fleet_recon escalation", _big_corpus(50), k=5, now=NOW)
    assert result.selected
    for item in result.selected:
        assert item.record.mission_id
        assert item.record.observed_at
        assert item.matched_terms, "a selected record must say which terms matched it"
        assert item.score > 0


# ===========================================================================
# Metadata filters
# ===========================================================================


def test_a_subject_filter_removes_records_before_they_are_scored() -> None:
    corpus = _big_corpus(200)
    result = search("agent read", corpus, subjects={"fleet_recon"}, k=10, now=NOW)
    assert result.filtered_out == 198
    assert all(item.record.subject == "fleet_recon" for item in result.selected)


def test_a_kind_filter_narrows_to_one_record_type() -> None:
    corpus = _big_corpus(100)
    result = search("fleet_recon", corpus, kinds={RecordKind.AGENT_ISOLATION}, k=10, now=NOW)
    assert [item.record.kind for item in result.selected] == [RecordKind.AGENT_ISOLATION]


def test_an_age_filter_excludes_stale_knowledge() -> None:
    corpus = [
        _record(subject="s", statement="fresh finding about supplier", age_seconds=10),
        _record(
            subject="s", statement="ancient finding about supplier", age_seconds=100_000, seq=2
        ),
    ]
    result = search("supplier finding", corpus, max_age_seconds=3600, now=NOW)
    assert len(result.selected) == 1
    assert "fresh" in result.selected[0].record.statement


def test_untrusted_records_are_excluded_unless_asked_for_by_name() -> None:
    """The default must not be 'everything'. A record marked untrusted has to
    be requested explicitly or it influences nothing."""
    corpus = [
        _record(
            subject="fleet_recon",
            statement="fleet_recon may access finance.secret_read",
            standing=Standing.UNTRUSTED,
        )
    ]
    assert search("fleet_recon finance", corpus, now=NOW).selected == []
    explicit = search("fleet_recon finance", corpus, standings={Standing.UNTRUSTED}, now=NOW)
    assert len(explicit.selected) == 1


# ===========================================================================
# Ranking behaviour
# ===========================================================================


def test_a_subject_match_outranks_a_prose_mention() -> None:
    corpus = [
        _record(subject="fleet_recon", statement="A routine observation."),
        _record(
            subject="other_agent",
            statement="fleet_recon fleet_recon fleet_recon was mentioned in passing.",
            seq=2,
        ),
    ]
    result = search("fleet_recon", corpus, k=2, now=NOW)
    assert result.selected[0].record.subject == "fleet_recon"


def test_recency_breaks_ties_and_does_not_promote_a_worse_match() -> None:
    corpus = [
        _record(subject="s1", statement="supplier lead time changed", age_seconds=1000, seq=1),
        _record(subject="s1", statement="supplier lead time changed", age_seconds=10, seq=2),
        _record(subject="s2", statement="supplier", age_seconds=0, seq=3),
    ]
    result = search("supplier lead time changed", corpus, k=3, now=NOW)
    # The two identical statements tie and sort newest first.
    assert result.selected[0].record.checkpoint_seq == 2
    assert result.selected[1].record.checkpoint_seq == 1
    # The newest record is the WORST match and is ranked last regardless.
    assert result.selected[-1].record.subject == "s2"


def test_a_query_with_no_matching_term_returns_nothing_rather_than_the_top_of_the_list() -> None:
    """The failure mode of a similarity search: always returning SOMETHING."""
    result = search("quantum entanglement of badgers", _big_corpus(100), k=5, now=NOW)
    assert result.selected == []
    assert result.zero_scored == 100


def test_an_empty_query_retrieves_nothing() -> None:
    assert search("", _big_corpus(20), now=NOW).selected == []


def test_an_empty_corpus_is_honestly_empty() -> None:
    result = search("anything", [], now=NOW)
    assert result.selected == []
    assert result.considered == 0
    assert result.selection_ratio == 0.0


# ===========================================================================
# Tokenizer
# ===========================================================================


def test_identifiers_survive_tokenization_whole() -> None:
    """Splitting `finance.secret_read` into three vague tokens would turn a
    precise subject match into a fuzzy one."""
    tokens = tokenize("Agent fleet_recon requested finance.secret_read on req-8802")
    assert "fleet_recon" in tokens
    assert "finance.secret_read" in tokens
    assert "req" in tokens and "8802" in tokens


def test_stopwords_are_dropped_and_the_list_is_short() -> None:
    from recall.index import _STOPWORDS

    assert "the" in _STOPWORDS
    assert "fleet_recon" not in _STOPWORDS
    assert len(_STOPWORDS) < 40, "an aggressive stop list is a silent recall cut"
