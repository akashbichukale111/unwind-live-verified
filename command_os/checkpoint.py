"""Mission Checkpoint Engine: the append-only persistence layer behind
Continuous Mission State.

Same discipline `hyperion/immune_memory.py` and `singularity/mesh_memory.py`
already establish one card over: APPEND-ONLY (no `update_checkpoint`
anywhere in this module's public surface -- `update_mission_status` only
ever touches the small parent record's status/timestamp, never a
checkpoint), and every read is a real fold over real, already-written
documents.

WHY A SUBCOLLECTION, NOT A COLLECTION-GROUP QUERY
------------------------------------------------------
`command_os_missions/{mission_id}/checkpoints/{seq}` mirrors
`cascades/{cascade_id}/nodes/{conclusion_id}` in `lib/firestore.py` exactly:
a cascade is a runtime record with its own lifetime, and so is a mission.
Every read here is scoped to one mission_id and ordered by a single field
(`seq`, or `created_at` for the mission index) -- deliberately never a
`.where()` filter combined with an `.order_by()` on a different field,
which is what forced `decision_memory`'s composite index (see
`docs/DEPLOY.md`'s account of the 2026-08-17 gap). This module therefore
needs no new entry in `infra/indexes.json` to work against real Firestore,
not just the emulator.
"""

from __future__ import annotations

from datetime import UTC, datetime

from command_os.schema import MissionCheckpoint, MissionRecord, MissionStage
from lib.firestore import get_client

COLLECTION_MISSIONS = "command_os_missions"
SUBCOLLECTION_CHECKPOINTS = "checkpoints"


def _missions():
    return get_client().collection(COLLECTION_MISSIONS)


def start_mission_record(mission_id: str, objective: str) -> MissionRecord:
    now = datetime.now(UTC)
    record = MissionRecord(
        mission_id=mission_id,
        objective=objective,
        status="RUNNING",
        created_at=now,
        updated_at=now,
    )
    _missions().document(mission_id).set(record.model_dump(mode="json"))
    return record


def update_mission_status(mission_id: str, status: str) -> None:
    _missions().document(mission_id).update(
        {"status": status, "updated_at": datetime.now(UTC).isoformat()}
    )


def get_mission_record(mission_id: str) -> MissionRecord | None:
    snap = _missions().document(mission_id).get()
    return MissionRecord(**snap.to_dict()) if snap.exists else None


def list_missions(limit: int = 25) -> list[MissionRecord]:
    """Most recently created missions first -- the Mission Time Machine's
    index. Single-field order, no filter: see the module docstring."""
    query = _missions().order_by("created_at", direction="DESCENDING").limit(limit)
    return [MissionRecord(**snap.to_dict()) for snap in query.stream()]


def write_checkpoint(
    *, mission_id: str, seq: int, stage: MissionStage, ctx: dict, status: str
) -> MissionCheckpoint:
    checkpoint = MissionCheckpoint(
        mission_id=mission_id,
        seq=seq,
        stage=stage,
        ctx=ctx,
        status=status,
        created_at=datetime.now(UTC),
    )
    (
        _missions()
        .document(mission_id)
        .collection(SUBCOLLECTION_CHECKPOINTS)
        .document(str(seq))
        .set(checkpoint.model_dump(mode="json"))
    )
    return checkpoint


def list_checkpoints(mission_id: str) -> list[MissionCheckpoint]:
    """Every checkpoint for one mission, earliest first."""
    query = _missions().document(mission_id).collection(SUBCOLLECTION_CHECKPOINTS).order_by("seq")
    return [MissionCheckpoint(**snap.to_dict()) for snap in query.stream()]


def latest_checkpoint(mission_id: str) -> MissionCheckpoint | None:
    query = (
        _missions()
        .document(mission_id)
        .collection(SUBCOLLECTION_CHECKPOINTS)
        .order_by("seq", direction="DESCENDING")
        .limit(1)
    )
    docs = list(query.stream())
    return MissionCheckpoint(**docs[0].to_dict()) if docs else None


def reset_for_test(mission_id: str) -> None:
    """Test hook: delete one mission's checkpoints and its parent record.
    Mirrors the `reset_for_test` hooks already present in `tower.registry`,
    `warrant.ledger`, `hyperion.immune_memory`, and `singularity.mesh_memory`.
    """
    doc_ref = _missions().document(mission_id)
    for snap in doc_ref.collection(SUBCOLLECTION_CHECKPOINTS).stream():
        snap.reference.delete()
    doc_ref.delete()
