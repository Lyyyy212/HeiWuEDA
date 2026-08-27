"""Project-level orchestration built on state, artifacts, and stage modules."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .artifact_store import ArtifactStore
from .io_utils import load_json, write_json_atomic
from .stage_modules import GateResult, get_stage_module
from .state import mark_gate, validate_state


class LifecycleOrchestrator:
    def __init__(self, project_root: str | Path):
        self.project_root = Path(project_root).resolve()
        self.state_path = self.project_root / ".hardware-lifecycle" / "project-state.json"
        self.store = ArtifactStore(self.project_root)

    def load_state(self) -> dict[str, Any]:
        state = load_json(self.state_path)
        errors = validate_state(state)
        if errors:
            raise ValueError("invalid lifecycle state: " + "; ".join(errors))
        return state

    def evaluate(self, stage: str | None = None, *, record: bool = False) -> GateResult:
        state = self.load_state()
        selected = stage or state["currentStage"]
        if selected != state["currentStage"]:
            raise ValueError("only the current lifecycle stage can be evaluated")
        records = state["stages"][selected]["artifacts"]
        verification_errors: list[str] = []
        artifacts: dict[str, list[dict[str, Any]]] = {}
        evidence: list[str] = []
        for artifact in records:
            verification_errors.extend(self.store.verify_record(artifact))
            path = artifact.get("path")
            if isinstance(path, str) and (self.project_root / path).is_file():
                payload = load_json(self.project_root / path)
                artifacts.setdefault(str(artifact.get("type")), []).append(payload)
                evidence.append(path)

        result = get_stage_module(selected).validate(artifacts, evidence)
        if verification_errors:
            result = GateResult(
                stage=result.stage,
                status="blocked",
                blockers=tuple(verification_errors) + result.blockers,
                warnings=result.warnings,
                evidence=result.evidence,
                output_digest=result.output_digest,
            )
        if record:
            if result.passed:
                updated = mark_gate(
                    state,
                    selected,
                    "passed",
                    evidence=list(result.evidence),
                    output_digest=result.output_digest,
                )
            else:
                updated = mark_gate(
                    state,
                    selected,
                    "blocked",
                    evidence=list(result.evidence),
                    note="; ".join(result.blockers),
                )
            write_json_atomic(self.state_path, updated)
        return result

