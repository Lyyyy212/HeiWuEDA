"""Immutable evidence recording for normalized read-only snapshots."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import uuid4

from .api_registry import registry_identity
from .io_utils import sha256_file, utc_now, write_json_atomic


def record_active_schematic_capture(
    evidence_root: str | Path,
    capture: dict[str, Any],
    manifest: dict[str, Any],
) -> dict[str, Any]:
    timestamp = utc_now()
    compact_time = timestamp.replace("-", "").replace(":", "").replace(".", "")
    snapshot_id = f"snapshot-{compact_time}-{uuid4().hex[:8]}"
    directory = Path(evidence_root) / snapshot_id
    directory.mkdir(parents=True, exist_ok=False)

    snapshot_path = directory / "snapshot.json"
    plan_path = directory / "api-plan.json"
    write_json_atomic(snapshot_path, capture["snapshot"], overwrite=False)
    write_json_atomic(plan_path, capture["plan"], overwrite=False)
    snapshot_digest = sha256_file(snapshot_path)
    plan_digest = sha256_file(plan_path)

    envelope = {
        "schemaVersion": "easyeda.hardware-lifecycle.artifact-envelope.v1",
        "artifactId": f"artifact:{uuid4()}",
        "artifactType": "active-schematic-snapshot",
        "artifactVersion": "1.0.0",
        "createdAt": timestamp,
        "producer": {"module": "easyeda-read-adapter", "version": "1.0.0"},
        "sourceIdentity": capture["identity"],
        "registry": registry_identity(manifest),
        "upstream": [],
        "payload": {"path": "snapshot.json", "sha256": snapshot_digest},
        "evidence": [
            {"type": "validated-api-plan", "path": "api-plan.json", "sha256": plan_digest}
        ],
        "assumptions": [],
        "unknowns": [
            "This first read adapter captures active-page components and pins, not net topology, formal BOM/netlist/PDF, DRC, PCB layout, or physical measurements."
        ],
        "safetyNotes": [
            "Read-only snapshot; no EasyEDA content was modified or saved."
        ],
    }
    envelope_path = directory / "envelope.json"
    write_json_atomic(envelope_path, envelope, overwrite=False)
    return {
        "snapshotId": snapshot_id,
        "directory": str(directory.resolve()),
        "snapshot": str(snapshot_path.resolve()),
        "snapshotSha256": snapshot_digest,
        "apiPlan": str(plan_path.resolve()),
        "apiPlanSha256": plan_digest,
        "envelope": str(envelope_path.resolve()),
        "envelopeSha256": sha256_file(envelope_path),
    }
