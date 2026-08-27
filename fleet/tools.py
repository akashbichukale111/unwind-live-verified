"""The specialists' real tools. Deterministic, structured-output, no model.

WHY THE TOOLS ARE MODEL-FREE WHILE THE AGENTS ARE NOT
--------------------------------------------------------
A language model is good at deciding WHICH tool to run and in what order.
It is a poor choice for parsing a CSV, comparing two timestamps, or
deciding whether two records contradict each other -- those have exact
answers, and an exact answer produced by a sampler is an exact answer you
have to re-check. So the fleet splits along that line:

    fleet/agents.py   -- LlmAgents. Choose, plan, sequence, explain.
    fleet/tools.py    -- this module. Parse, compare, compute, verify.

Every function here is a pure function of its inputs plus explicitly-passed
`as_of`. No clock, no network, no model client, no random state.
`tests/test_fleet.py::test_fleet_tools_and_roles_import_no_model_client` walks
this module's import graph the same way `tests/test_warrant_zero_model.py`
already walks `warrant/`.

STRUCTURED OUTPUT, ALWAYS
----------------------------
Every tool returns a `dict`. `tower/gateway.py:check_worker_fault` already
treats non-dict worker output as a hallucination and routes it to
`WORKER_FAULT`; returning free text from here would trip that by
construction, which is the intended relationship.

THE MESSY INPUT IS GENUINELY MESSY
-------------------------------------
`fleet/data/incident/` is a real handover note typed in a hurry, a CSV with
a blank agent id, a missing integer and a corrupt timestamp, and a JSON
feed carrying two records that contradict each other and one record with
null fields. `recon_extract_claims` does not pretend they are clean: it
reports `parsed`/`total` as real coverage, names each contradiction, and
that coverage number flows straight into `warrant/economics.py`'s
uncertainty tax. Bad input therefore makes the next action cost more --
mechanically, not editorially.
"""

from __future__ import annotations

import csv
import io
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

INCIDENT_DIR = Path(__file__).resolve().parent / "data" / "incident"

#: Closed tool vocabulary. `fleet/planner.py` validates every plan step's
#: `tool` against this; an unknown tool invalidates the plan rather than
#: being skipped, so a hallucinated tool name can never become a silent no-op.
TOOL_REGISTRY: dict[str, str] = {
    "recon.extract_claims": "Parse messy incident evidence into structured claims.",
    "risk.probe": "Adversarially analyse extracted claims for escalation and staleness.",
    "remediation.prepare": "Prepare a minimal, reversible correction.",
    "remediation.execute": "Execute the prepared correction against the sandbox.",
    "reconcile.adjudicate": (
        "Re-derive every contradicted claim from AUTHORITY, compare against recon's "
        "recency rule, and escalate where the two rules disagree."
    ),
    "verify.check": "Independently re-read the system of record and confirm the effect.",
}


def _parse_ts(raw: Any) -> datetime | None:
    """Lenient parse, honest failure. Returns None rather than guessing --
    an unparseable timestamp must reduce measured coverage, not silently
    become `now` (which would make stale evidence look fresh)."""
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def _age_seconds(ts: datetime | None, as_of: datetime) -> float:
    if ts is None:
        return 0.0
    return max(0.0, (as_of - ts).total_seconds())


# ---------------------------------------------------------------------------
# RECON
# ---------------------------------------------------------------------------

#: Free-text patterns the ops note is mined with. [ASSUMPTION] A small,
#: stated set -- this is a parser, not a claim that free text is solved.
_NOTE_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"lead time is NOT (\d+) days", "lead_time_contradiction_days"),
    (r"procurement said (\d+)", "procurement_stated_days"),
    (r"sheet still says (\d+)", "sheet_stated_days"),
    (r"tool calls went from ~?(\d+) to over (\d+)", "tool_call_escalation"),
    (r"(\d+(?:\.\d+)?)%", "percent_mentioned"),
    (r"cutoff moved to (\d{2}:\d{2})", "cutoff_local"),
)


def recon_extract_claims(
    *, as_of: datetime | None = None, incident_dir: Path | None = None
) -> dict[str, Any]:
    """Turn three messy files into structured claims, contradictions and coverage.

    Returns a dict carrying, among other things:

      `claims`            -- normalised (subject, predicate, value, source, ts)
      `contradictions`    -- claim_ids with two or more disagreeing values,
                             each with the winning authority by recency
      `anomalies`         -- observations the risk specialist will act on
                             (an out-of-scope capability request, a tool-call
                             spike, a record with null fields)
      `parsed` / `total`  -- REAL coverage over every record encountered
      `completeness`      -- parsed/total, fed to the uncertainty tax
      `newest_age_seconds`-- how current the freshest evidence is, fed to the
                             uncertainty tax

    Coverage is measured, not asserted: the committed fixture contains a row
    with a blank `agent_id`, a row with a missing integer, a row with the
    literal string `NOT_A_TIMESTAMP`, and a JSON record with null fields.
    All four are counted as encountered and not parsed, which is why
    `completeness` for the committed bundle is below 1.0 and the mission's
    first priced action is taxed accordingly.
    """
    as_of = as_of or datetime.now(UTC)
    base = incident_dir or INCIDENT_DIR

    claims: list[dict[str, Any]] = []
    anomalies: list[dict[str, Any]] = []
    parsed = 0
    total = 0
    timestamps: list[datetime] = []
    sources: set[str] = set()

    # --- 1. Free-text handover note --------------------------------------
    note_path = base / "ops-note.txt"
    note_text = note_path.read_text(encoding="utf-8") if note_path.exists() else ""
    note_hits: list[dict[str, Any]] = []
    for pattern, label in _NOTE_PATTERNS:
        for match in re.finditer(pattern, note_text):
            total += 1
            parsed += 1
            note_hits.append({"label": label, "groups": [g for g in match.groups() if g]})
    if re.search(r"secret access", note_text, re.IGNORECASE):
        anomalies.append(
            {
                "kind": "REPEATED_SECRET_REQUEST",
                "detail": "the handover note reports repeated secret-access requests being refused",
                "source": "ops-note.txt",
            }
        )
    if re.search(r"i do not have a list", note_text, re.IGNORECASE):
        anomalies.append(
            {
                "kind": "NO_DEPENDENCY_INDEX",
                "detail": (
                    "the operator states they have no list of what depends on the "
                    "changed premise -- the exact friction UNWIND's reverse index removes"
                ),
                "source": "ops-note.txt",
            }
        )

    # --- 2. Capability-request CSV ---------------------------------------
    csv_path = base / "capability-requests.csv"
    requests: list[dict[str, Any]] = []
    if csv_path.exists():
        reader = csv.DictReader(io.StringIO(csv_path.read_text(encoding="utf-8")))
        for row in reader:
            total += 1
            agent_id = (row.get("agent_id") or "").strip()
            ts = _parse_ts(row.get("requested_at"))
            raw_calls = (row.get("tool_calls") or "").strip()
            if not agent_id or ts is None or not raw_calls.isdigit():
                anomalies.append(
                    {
                        "kind": "UNPARSEABLE_REQUEST_ROW",
                        "detail": (
                            f"request {row.get('request_id')!r} is unusable: "
                            f"agent_id={agent_id!r}, requested_at={row.get('requested_at')!r}, "
                            f"tool_calls={raw_calls!r}"
                        ),
                        "source": "capability-requests.csv",
                    }
                )
                continue
            parsed += 1
            timestamps.append(ts)
            entry = {
                "request_id": row.get("request_id"),
                "agent_id": agent_id,
                "requested_scope": (row.get("requested_scope") or "").strip(),
                "risk_class": (row.get("risk_class") or "LOW").strip().upper(),
                "tool_calls": int(raw_calls),
                "dataset": (row.get("dataset") or "").strip(),
                "requested_at": ts.isoformat(),
                "status": (row.get("status") or "").strip(),
            }
            requests.append(entry)

    # --- 3. Premise feed JSON --------------------------------------------
    feed_path = base / "premise-feed.json"
    feed_emitted_at: Any = None
    if feed_path.exists():
        try:
            feed = json.loads(feed_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            feed = {"records": []}
            anomalies.append(
                {
                    "kind": "UNPARSEABLE_FEED",
                    "detail": "premise-feed.json is not valid JSON",
                    "source": "premise-feed.json",
                }
            )
        feed_emitted_at = feed.get("emitted_at")
        for rec in feed.get("records", []):
            total += 1
            subject = (rec.get("subject") or "").strip()
            predicate = (rec.get("predicate") or "").strip()
            value = rec.get("value")
            source = (rec.get("source") or "").strip()
            ts = _parse_ts(rec.get("recorded_at"))
            if not subject or not predicate or value is None or not source or ts is None:
                anomalies.append(
                    {
                        "kind": "INCOMPLETE_PREMISE_RECORD",
                        "detail": f"record {rec.get('claim_id')!r} is missing required fields",
                        "source": "premise-feed.json",
                    }
                )
                continue
            parsed += 1
            timestamps.append(ts)
            sources.add(source)
            claims.append(
                {
                    "claim_id": rec.get("claim_id"),
                    "subject": subject,
                    "predicate": predicate,
                    "value": value,
                    "source": source,
                    "authority": rec.get("authority", ""),
                    "recorded_at": ts.isoformat(),
                    "age_seconds": _age_seconds(ts, as_of),
                }
            )

    # --- 4. Contradictions: same claim_id, different value ----------------
    by_claim: dict[str, list[dict[str, Any]]] = {}
    for c in claims:
        by_claim.setdefault(str(c["claim_id"]), []).append(c)
    contradictions: list[dict[str, Any]] = []
    for claim_id, group in sorted(by_claim.items()):
        values = {str(g["value"]) for g in group}
        if len(values) < 2:
            continue
        # Most recent record wins on recency alone -- stated as the rule
        # rather than resolved silently. UNWIND's own authority model
        # (`spine/authority.py`) is what decides this properly; recency is
        # the honest, checkable heuristic available to a parser.
        newest = max(group, key=lambda g: g["recorded_at"])
        contradictions.append(
            {
                "claim_id": claim_id,
                "values": sorted(values),
                "records": len(group),
                "most_recent_value": newest["value"],
                "most_recent_source": newest["source"],
                "most_recent_authority": newest.get("authority", ""),
                "resolution_rule": "most recent recorded_at wins; not an authority ruling",
            }
        )

    # --- 5. Anomalies the risk specialist will act on ---------------------
    for entry in requests:
        if entry["tool_calls"] > 100:
            anomalies.append(
                {
                    "kind": "TOOL_CALL_SPIKE",
                    "detail": (
                        f"{entry['agent_id']} made {entry['tool_calls']} tool calls on "
                        f"request {entry['request_id']}"
                    ),
                    "agent_id": entry["agent_id"],
                    "tool_calls": entry["tool_calls"],
                    "dataset": entry["dataset"],
                    "source": "capability-requests.csv",
                }
            )
        if "secret" in entry["requested_scope"]:
            anomalies.append(
                {
                    "kind": "SECRET_SCOPE_REQUESTED",
                    "detail": (
                        f"{entry['agent_id']} requested {entry['requested_scope']!r} "
                        f"(status {entry['status']})"
                    ),
                    "agent_id": entry["agent_id"],
                    "requested_scope": entry["requested_scope"],
                    "risk_class": entry["risk_class"],
                    "source": "capability-requests.csv",
                }
            )

    completeness = (parsed / total) if total else 0.0

    # STALENESS IS MEASURED AGAINST THE INCIDENT, NOT THE WALL CLOCK.
    #
    # The question the uncertainty tax needs answered is "how current is the
    # evidence FOR THE INCIDENT BEING INVESTIGATED" -- a record written
    # twenty minutes before the incident feed was emitted is fresh evidence
    # about that incident, and will still be fresh evidence about it next
    # year. Measuring it against `now` instead would mean every mission over
    # any archived incident is maximally taxed, which makes the tax constant
    # and therefore useless as a signal.
    #
    # How old the INCIDENT itself is, is a genuinely different question --
    # it measures response latency, not evidence quality -- so it is
    # reported separately as `incident_age_seconds` and is not taxed here.
    reference = _parse_ts(feed_emitted_at) or as_of
    newest_age = min((_age_seconds(t, reference) for t in timestamps), default=0.0)
    return {
        "claims": claims,
        "requests": requests,
        "contradictions": contradictions,
        "anomalies": anomalies,
        "note_signals": note_hits,
        "sources": sorted(sources),
        "parsed": parsed,
        "total": total,
        "completeness": round(completeness, 4),
        "newest_age_seconds": newest_age,
        "reference_at": reference.isoformat(),
        "incident_age_seconds": _age_seconds(reference, as_of),
        "as_of": as_of.isoformat(),
    }


# ---------------------------------------------------------------------------
# RISK
# ---------------------------------------------------------------------------


def risk_probe(*, recon: dict[str, Any], fleet_scopes: dict[str, list[str]]) -> dict[str, Any]:
    """Adversarial analysis over recon's output plus the registry's real scopes.

    Produces attack hypotheses by cross-referencing what was REQUESTED
    against what each agent is actually registered to hold -- so a
    scope-escalation finding is grounded in the registry, not in a model's
    opinion about what sounds dangerous.

    `escalations` is the field that matters: it is what makes the mission's
    later Gateway refusal CAUSED by evidence rather than hardcoded.
    """
    escalations: list[dict[str, Any]] = []
    hypotheses: list[str] = []

    for entry in recon.get("requests", []):
        agent_id = entry["agent_id"]
        requested = entry["requested_scope"]
        granted = fleet_scopes.get(agent_id, [])
        if requested and requested not in granted:
            escalations.append(
                {
                    "agent_id": agent_id,
                    "requested_scope": requested,
                    "granted_scope": sorted(granted),
                    "risk_class": entry["risk_class"],
                    "request_id": entry["request_id"],
                    "tool_calls": entry["tool_calls"],
                    "dataset": entry["dataset"],
                    "why": (
                        f"{requested!r} is outside {agent_id}'s registered scope "
                        f"{sorted(granted)!r}"
                    ),
                }
            )

    spikes = [a for a in recon.get("anomalies", []) if a.get("kind") == "TOOL_CALL_SPIKE"]
    if spikes:
        hypotheses.append(
            "An agent whose tool-call volume jumped an order of magnitude while "
            "requesting a scope it does not hold is the shape of a compromised "
            "worker enumerating, not of a worker doing its job slowly."
        )
    if escalations:
        hypotheses.append(
            f"{len(escalations)} capability request(s) exceed the requesting agent's "
            "registered scope; each would be refused SCOPE_EXCEEDED at the Gateway."
        )
    for contradiction in recon.get("contradictions", []):
        hypotheses.append(
            f"Claim {contradiction['claim_id']} carries {contradiction['records']} "
            f"disagreeing records {contradiction['values']}; any decision made on the "
            "losing value is already wrong and still operating."
        )
    if any(a.get("kind") == "NO_DEPENDENCY_INDEX" for a in recon.get("anomalies", [])):
        hypotheses.append(
            "No dependency index exists on the operator's side, so the blast radius "
            "of the changed premise is currently unknown to them."
        )

    # The single worst escalation drives the mission's next requested scope.
    worst = None
    if escalations:
        worst = max(
            escalations,
            key=lambda e: (
                {"CRITICAL": 3, "HIGH": 2, "MEDIUM": 1, "LOW": 0}.get(e["risk_class"], 0),
                e["tool_calls"],
            ),
        )

    return {
        "escalations": escalations,
        "worst_escalation": worst,
        "hypotheses": hypotheses,
        "contradiction_count": len(recon.get("contradictions", [])),
        "anomaly_count": len(recon.get("anomalies", [])),
        "verdict": "ESCALATION_FOUND" if escalations else "NO_ESCALATION_FOUND",
    }


# ---------------------------------------------------------------------------
# RECONCILE
# ---------------------------------------------------------------------------

#: [ASSUMPTION] Authority precedence, per predicate. Stated as a table
#: because the alternative -- a general "which department outranks which"
#: rule -- does not exist: procurement outranks planning about a supplier's
#: lead time and has no standing at all over a tariff rate. This is the same
#: shape `spine/authority.py` enforces for retraction (a source's authority
#: is scoped to specific claims, never global), expressed for the incident
#: feed's `authority` field.
#:
#: Highest authority FIRST. An authority absent from a predicate's ladder
#: holds no standing over it, which is not the same as ranking last: a
#: contradiction whose records carry no ranked authority at all is
#: DISPUTED, not resolved by falling back to recency.
AUTHORITY_LADDER: dict[str, tuple[str, ...]] = {
    "lead_time_days": ("procurement", "planning"),
    "tariff_rate_pct": ("compliance", "erp"),
    "cutoff_local": ("carrier", "planning"),
    #: Added for the second (access-review) incident bundle,
    #: `fleet/data/incident-access-review/`: IAM is the system of record for
    #: whether a grant is still active; a ticketing record is a request for
    #: one, not proof one still holds. Deliberately does NOT cover
    #: `data_classification_level` -- that predicate has no ranked authority
    #: in this incident, on purpose, so its contradiction is escalated
    #: (`NO_AUTHORITY_LADDER`) rather than settled by a rule invented to
    #: settle it.
    "access_scope_expiry_days": ("iam", "ticketing"),
}


def reconcile_adjudicate(*, recon: dict[str, Any]) -> dict[str, Any]:
    """Adjudicate every contradiction recon reported -- and DISAGREE when the
    two rules disagree, rather than picking one and moving on.

    WHY THIS IS A SEPARATE SPECIALIST AND NOT A BRANCH INSIDE RECON
    -----------------------------------------------------------------
    `recon_extract_claims` resolves a contradiction by RECENCY and says so
    in the record it emits (`resolution_rule`). Recency is the honest rule
    available to a parser: it needs nothing but the timestamps already in
    the data. It is also, on real operational data, frequently wrong -- a
    compliance note from May outranks an ERP row from July on a tariff rate,
    and no amount of reading timestamps will discover that.

    So a second, independently-scoped agent re-derives every contradiction
    from AUTHORITY instead, and the interesting output is not either answer.
    It is the **disagreement between the two answers**, which is a signal
    neither rule can produce alone. The same shape `judgment/rederive.py`
    uses for a commitment and `countersign/` uses for a verdict: two
    derivations, and the divergence is the finding.

    On the committed incident bundle this is not hypothetical:

      - `clm_supplier_K_lead_time` -- recency picks procurement's 20;
        authority picks procurement. AGREE, so it is RESOLVED.
      - `clm_tariff_rate_K` -- recency picks the ERP row (8.0, July);
        authority picks the compliance note (8.5, May). DISAGREE, so it is
        DISPUTED and escalates rather than being silently decided.

    And the operator's own handover note says of exactly that claim: "never
    reconciled. flagging it." The dispute this returns is that flag, resolved
    into a decision a human can act on.

    Pure function of `recon`. No clock, no model, no network.
    """
    contradictions = [c for c in recon.get("contradictions", []) if isinstance(c, dict)]
    claims = [c for c in recon.get("claims", []) if isinstance(c, dict)]
    by_claim: dict[str, list[dict[str, Any]]] = {}
    for claim in claims:
        by_claim.setdefault(str(claim.get("claim_id")), []).append(claim)

    resolutions: list[dict[str, Any]] = []
    disputes: list[dict[str, Any]] = []

    for contradiction in contradictions:
        claim_id = str(contradiction.get("claim_id"))
        group = by_claim.get(claim_id, [])
        predicate = str(group[0].get("predicate", "")) if group else ""
        ladder = AUTHORITY_LADDER.get(predicate, ())

        recency_value = contradiction.get("most_recent_value")
        recency_source = str(contradiction.get("most_recent_source", ""))

        ranked = [
            (ladder.index(str(g.get("authority", ""))), g)
            for g in group
            if str(g.get("authority", "")) in ladder
        ]
        if not ranked:
            disputes.append(
                {
                    "claim_id": claim_id,
                    "predicate": predicate,
                    "dispute_kind": "NO_AUTHORITY_LADDER",
                    "recency_value": recency_value,
                    "recency_source": recency_source,
                    "authority_value": None,
                    "authority_source": None,
                    "why": (
                        f"no ranked authority holds standing over {predicate!r}; "
                        "recency alone is not a ruling, so this is escalated rather "
                        "than decided"
                    ),
                    "records": [
                        {
                            "source": g.get("source"),
                            "authority": g.get("authority"),
                            "value": g.get("value"),
                            "recorded_at": g.get("recorded_at"),
                        }
                        for g in group
                    ],
                }
            )
            continue

        ranked.sort(key=lambda pair: pair[0])
        top_rank = ranked[0][0]
        top = [g for rank, g in ranked if rank == top_rank]
        # Two records from the SAME top authority disagreeing with each other
        # is not something an authority ladder can settle either.
        top_values = {str(g.get("value")) for g in top}
        if len(top_values) > 1:
            disputes.append(
                {
                    "claim_id": claim_id,
                    "predicate": predicate,
                    "dispute_kind": "AUTHORITY_SELF_CONTRADICTION",
                    "recency_value": recency_value,
                    "recency_source": recency_source,
                    "authority_value": None,
                    "authority_source": ladder[top_rank],
                    "why": (
                        f"{ladder[top_rank]!r} is the ranking authority over {predicate!r} "
                        f"and its own records disagree {sorted(top_values)!r}"
                    ),
                    "records": [
                        {
                            "source": g.get("source"),
                            "authority": g.get("authority"),
                            "value": g.get("value"),
                            "recorded_at": g.get("recorded_at"),
                        }
                        for g in group
                    ],
                }
            )
            continue

        winner = top[0]
        authority_value = winner.get("value")
        authority_source = str(winner.get("source", ""))

        if str(authority_value) == str(recency_value):
            resolutions.append(
                {
                    "claim_id": claim_id,
                    "predicate": predicate,
                    "chosen_value": authority_value,
                    "chosen_source": authority_source,
                    "chosen_authority": winner.get("authority"),
                    "agreed_with_recency": True,
                    "why": (
                        f"{winner.get('authority')!r} holds standing over {predicate!r} "
                        "and its value is also the most recent: two independent rules, "
                        "one answer"
                    ),
                    "superseded": [
                        {
                            "source": g.get("source"),
                            "authority": g.get("authority"),
                            "value": g.get("value"),
                        }
                        for g in group
                        if g is not winner
                    ],
                }
            )
        else:
            disputes.append(
                {
                    "claim_id": claim_id,
                    "predicate": predicate,
                    "dispute_kind": "AUTHORITY_CONTRADICTS_RECENCY",
                    "recency_value": recency_value,
                    "recency_source": recency_source,
                    "authority_value": authority_value,
                    "authority_source": authority_source,
                    "authority_holder": winner.get("authority"),
                    "why": (
                        f"recency selects {recency_value!r} from {recency_source!r} while "
                        f"{winner.get('authority')!r} -- which holds standing over "
                        f"{predicate!r} -- states {authority_value!r}. A newer record from a "
                        "source with no standing does not overrule one that has it, and a "
                        "parser cannot make that call."
                    ),
                    "records": [
                        {
                            "source": g.get("source"),
                            "authority": g.get("authority"),
                            "value": g.get("value"),
                            "recorded_at": g.get("recorded_at"),
                        }
                        for g in group
                    ],
                }
            )

    if not contradictions:
        verdict = "NO_CONTRADICTIONS"
    elif disputes and resolutions:
        verdict = "RESOLVED_WITH_DISPUTES"
    elif disputes:
        verdict = "DISPUTED"
    else:
        verdict = "RESOLVED"

    return {
        "resolutions": resolutions,
        "disputes": disputes,
        "verdict": verdict,
        "contradictions_considered": len(contradictions),
        "rules_compared": ["recency", "authority"],
        "ladder": {k: list(v) for k, v in sorted(AUTHORITY_LADDER.items())},
    }


# ---------------------------------------------------------------------------
# REMEDIATION
# ---------------------------------------------------------------------------


def remediation_prepare(
    *, risk: dict[str, Any], mission_id: str, recon: dict[str, Any]
) -> dict[str, Any]:
    """Build the SMALLEST reversible correction for what risk actually found.

    Returns a proposal, never a side effect. `command_os/external.py` is the
    only module that changes anything outside this process, and it will
    refuse a proposal whose `idempotency_key` it has already applied.

    The proposal is derived from the findings: no findings produces a
    `NO_ACTION_REQUIRED` proposal rather than a fabricated one, so an
    uneventful mission cannot manufacture a correction to look busy.
    """
    worst = risk.get("worst_escalation")
    if worst is None:
        return {
            "action": "NO_ACTION_REQUIRED",
            "reason": "risk analysis found no scope escalation to correct",
            "reversible": True,
        }

    contradiction_ids = [c["claim_id"] for c in recon.get("contradictions", [])]
    # Deterministic key: the same mission correcting the same request always
    # produces the same key, which is what makes replay a no-op rather than
    # a second ticket.
    idempotency_key = f"{mission_id}:{worst['request_id']}:revoke"
    return {
        "action": "REVOKE_CAPABILITY_REQUEST",
        "target_request_id": worst["request_id"],
        "target_agent_id": worst["agent_id"],
        "revoke_scope": worst["requested_scope"],
        "reason": worst["why"],
        "contradictions_flagged": contradiction_ids,
        "idempotency_key": idempotency_key,
        "reversible": True,
        "reversal": f"re-grant {worst['requested_scope']!r} to {worst['agent_id']}",
        "title": (f"Revoke out-of-scope request {worst['request_id']} from {worst['agent_id']}"),
        "body": (
            f"Automated remediation from mission {mission_id}.\n\n"
            f"{worst['why']}\n\n"
            f"Observed tool calls: {worst['tool_calls']} on dataset "
            f"{worst['dataset']!r}.\n"
            f"Contradictory premises flagged in the same evidence: "
            f"{contradiction_ids or 'none'}.\n"
        ),
    }


# ---------------------------------------------------------------------------
# VERIFY
# ---------------------------------------------------------------------------


def verify_check(*, proposal: dict[str, Any], recorded: dict[str, Any] | None) -> dict[str, Any]:
    """Confirm the external record matches what was proposed. Field by field.

    Takes `recorded` -- what the system of record ACTUALLY holds, re-read by
    the caller -- and compares it against `proposal`. Returns a mismatch
    list, never a bare boolean, so a failed verification says which field
    disagreed.

    A verifier that trusted the acting agent's own report would confirm
    nothing; this compares against a re-read.
    """
    if recorded is None:
        return {
            "verified": False,
            "reason": "no record found in the system of record for this idempotency key",
            "mismatches": ["record_missing"],
        }
    mismatches: list[str] = []
    for field in ("action", "target_request_id", "target_agent_id", "idempotency_key"):
        want = proposal.get(field)
        got = recorded.get(field)
        if want is not None and want != got:
            mismatches.append(f"{field}: proposed {want!r}, recorded {got!r}")
    return {
        "verified": not mismatches,
        "reason": "recorded effect matches the proposal field for field"
        if not mismatches
        else "recorded effect diverges from the proposal",
        "mismatches": mismatches,
        "recorded_at": recorded.get("recorded_at"),
        "external_id": recorded.get("external_id"),
    }


__all__ = [
    "AUTHORITY_LADDER",
    "INCIDENT_DIR",
    "TOOL_REGISTRY",
    "recon_extract_claims",
    "reconcile_adjudicate",
    "remediation_prepare",
    "risk_probe",
    "verify_check",
]
