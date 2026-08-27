"""Lifecycle state machine and cross-field validation."""

from __future__ import annotations

from copy import deepcopy
from typing import Any
from uuid import uuid4

from .constants import GATE_STATUSES, STAGES, STAGE_STATUSES, STATE_SCHEMA
from .io_utils import is_sha256, utc_now


def _new_gate() -> dict[str, Any]:
    return {
        "status": "pending",
        "evidence": [],
        "outputDigest": None,
        "note": None,
    }


def _new_stage(status: str) -> dict[str, Any]:
    return {
        "status": status,
        "artifacts": [],
        "staleArtifacts": [],
        "blockers": [],
        "gate": _new_gate(),
        "invalidatedAt": None,
        "invalidationReason": None,
    }


def new_state(project_name: str, project_id: str | None = None) -> dict[str, Any]:
    if not project_name.strip():
        raise ValueError("project_name must not be empty")
    now = utc_now()
    state = {
        "schemaVersion": STATE_SCHEMA,
        "revision": 1,
        "project": {
            "projectId": project_id or f"project:{uuid4()}",
            "name": project_name.strip(),
            "createdAt": now,
            "updatedAt": now,
        },
        "currentStage": STAGES[0],
        "stages": {
            stage: _new_stage("in_progress" if index == 0 else "pending")
            for index, stage in enumerate(STAGES)
        },
        "history": [
            {
                "at": now,
                "event": "initialized",
                "stage": STAGES[0],
                "revision": 1,
            }
        ],
    }
    return state


def validate_state(state: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if state.get("schemaVersion") != STATE_SCHEMA:
        errors.append(f"schemaVersion must be {STATE_SCHEMA}")
    revision = state.get("revision")
    if not isinstance(revision, int) or revision < 1:
        errors.append("revision must be an integer >= 1")

    project = state.get("project")
    if not isinstance(project, dict):
        errors.append("project must be an object")
    else:
        for field in ("projectId", "name", "createdAt", "updatedAt"):
            if not isinstance(project.get(field), str) or not project[field].strip():
                errors.append(f"project.{field} must be a non-empty string")

    current = state.get("currentStage")
    if current not in STAGES:
        errors.append(f"currentStage must be one of {', '.join(STAGES)}")

    stages = state.get("stages")
    if not isinstance(stages, dict):
        errors.append("stages must be an object")
        return errors
    missing = [stage for stage in STAGES if stage not in stages]
    extra = [stage for stage in stages if stage not in STAGES]
    if missing:
        errors.append(f"missing stage records: {', '.join(missing)}")
    if extra:
        errors.append(f"unknown stage records: {', '.join(extra)}")

    for stage in STAGES:
        record = stages.get(stage)
        if not isinstance(record, dict):
            errors.append(f"stages.{stage} must be an object")
            continue
        status = record.get("status")
        if status not in STAGE_STATUSES:
            errors.append(f"stages.{stage}.status is invalid")
        for field in ("artifacts", "staleArtifacts", "blockers"):
            if not isinstance(record.get(field), list):
                errors.append(f"stages.{stage}.{field} must be an array")
        gate = record.get("gate")
        if not isinstance(gate, dict):
            errors.append(f"stages.{stage}.gate must be an object")
            continue
        gate_status = gate.get("status")
        if gate_status not in GATE_STATUSES:
            errors.append(f"stages.{stage}.gate.status is invalid")
        if not isinstance(gate.get("evidence"), list):
            errors.append(f"stages.{stage}.gate.evidence must be an array")
        if gate_status == "passed":
            if status != "completed":
                errors.append(f"stages.{stage} passed gate requires completed status")
            if not gate.get("evidence"):
                errors.append(f"stages.{stage} passed gate requires evidence")
            if not is_sha256(gate.get("outputDigest")):
                errors.append(f"stages.{stage} passed gate requires SHA-256 outputDigest")
        if status == "completed" and gate_status != "passed":
            errors.append(f"stages.{stage} completed status requires passed gate")
        if gate_status == "blocked" and not gate.get("note"):
            errors.append(f"stages.{stage} blocked gate requires note")

    if isinstance(state.get("history"), list) is False:
        errors.append("history must be an array")

    if current in STAGES:
        current_index = STAGES.index(current)
        for index, stage in enumerate(STAGES):
            record = stages.get(stage)
            if not isinstance(record, dict):
                continue
            if index < current_index and record.get("status") != "completed":
                errors.append(f"stage before currentStage is not completed: {stage}")
            if index > current_index and record.get("status") == "completed":
                errors.append(f"stage after currentStage cannot be completed: {stage}")
    return errors


def _record_event(state: dict[str, Any], event: str, stage: str, **details: Any) -> None:
    state["revision"] += 1
    now = utc_now()
    state["project"]["updatedAt"] = now
    state["history"].append(
        {
            "at": now,
            "event": event,
            "stage": stage,
            "revision": state["revision"],
            **details,
        }
    )


def mark_gate(
    state: dict[str, Any],
    stage: str,
    status: str,
    *,
    evidence: list[str],
    output_digest: str | None = None,
    note: str | None = None,
) -> dict[str, Any]:
    errors = validate_state(state)
    if errors:
        raise ValueError("invalid state: " + "; ".join(errors))
    if stage != state["currentStage"]:
        raise ValueError("gate can be recorded only for currentStage")
    if status not in {"passed", "blocked"}:
        raise ValueError("gate status must be passed or blocked")
    if status == "passed" and (not evidence or not is_sha256(output_digest)):
        raise ValueError("passed gate requires evidence and a SHA-256 output digest")
    if status == "blocked" and not note:
        raise ValueError("blocked gate requires a note")

    updated = deepcopy(state)
    record = updated["stages"][stage]
    record["gate"] = {
        "status": status,
        "evidence": list(evidence),
        "outputDigest": output_digest if status == "passed" else None,
        "note": note,
    }
    if status == "passed":
        record["status"] = "completed"
        record["blockers"] = []
    else:
        record["status"] = "in_progress"
        if note not in record["blockers"]:
            record["blockers"].append(note)
    _record_event(updated, f"gate_{status}", stage, evidence=list(evidence), note=note)
    return updated


def record_artifact(
    state: dict[str, Any],
    stage: str,
    *,
    path: str,
    sha256: str,
    artifact_type: str,
) -> dict[str, Any]:
    errors = validate_state(state)
    if errors:
        raise ValueError("invalid state: " + "; ".join(errors))
    if stage != state["currentStage"]:
        raise ValueError("artifacts can be recorded only for currentStage")
    if not path.strip() or not artifact_type.strip():
        raise ValueError("artifact path and type must not be empty")
    if not is_sha256(sha256):
        raise ValueError("artifact sha256 must be a 64-character SHA-256 digest")

    updated = deepcopy(state)
    record = {"path": path, "sha256": sha256.lower(), "type": artifact_type}
    artifacts = updated["stages"][stage]["artifacts"]
    artifacts[:] = [item for item in artifacts if item.get("path") != path]
    artifacts.append(record)
    _record_event(updated, "artifact_recorded", stage, artifact=record)
    return updated


def advance(state: dict[str, Any], target: str) -> dict[str, Any]:
    errors = validate_state(state)
    if errors:
        raise ValueError("invalid state: " + "; ".join(errors))
    current = state["currentStage"]
    current_index = STAGES.index(current)
    if current_index == len(STAGES) - 1:
        raise ValueError("already at final lifecycle stage")
    expected = STAGES[current_index + 1]
    if target != expected:
        raise ValueError(f"next stage must be {expected}")
    if state["stages"][current]["gate"]["status"] != "passed":
        raise ValueError(f"current stage gate has not passed: {current}")

    updated = deepcopy(state)
    updated["currentStage"] = target
    updated["stages"][target]["status"] = "in_progress"
    _record_event(updated, "advanced", target, fromStage=current)
    return updated


def invalidate(state: dict[str, Any], from_stage: str, reason: str) -> dict[str, Any]:
    errors = validate_state(state)
    if errors:
        raise ValueError("invalid state: " + "; ".join(errors))
    if from_stage not in STAGES:
        raise ValueError(f"unknown stage: {from_stage}")
    if not reason.strip():
        raise ValueError("invalidation reason must not be empty")

    updated = deepcopy(state)
    now = utc_now()
    start = STAGES.index(from_stage)
    for index, stage in enumerate(STAGES[start:], start=start):
        record = updated["stages"][stage]
        record["staleArtifacts"].extend(record["artifacts"])
        record["artifacts"] = []
        record["status"] = "in_progress" if index == start else "pending"
        record["gate"] = _new_gate()
        record["blockers"] = [reason] if index == start else []
        record["invalidatedAt"] = now
        record["invalidationReason"] = reason
    updated["currentStage"] = from_stage
    _record_event(updated, "invalidated", from_stage, reason=reason)
    return updated
