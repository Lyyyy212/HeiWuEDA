"""Content-addressed lifecycle artifact storage and verification."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any
from uuid import uuid4

from .io_utils import load_json, sha256_file, utc_now, write_json_atomic


ARTIFACT_ENVELOPE_SCHEMA = "easyeda.hardware-lifecycle.artifact-envelope.v1"


def _serialized_json_digest(value: Any) -> str:
    rendered = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    return hashlib.sha256(rendered.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class StoredArtifact:
    """References for one canonical payload and its immutable envelope."""

    artifact_id: str
    artifact_type: str
    payload_path: str
    envelope_path: str
    sha256: str

    def state_record(self) -> dict[str, str]:
        return {
            "path": self.payload_path,
            "sha256": self.sha256,
            "type": self.artifact_type,
            "envelope": self.envelope_path,
        }


class ArtifactStore:
    """Write canonical JSON while retaining a content-addressed immutable copy."""

    def __init__(self, project_root: str | Path):
        self.root = Path(project_root).resolve()
        self.store_root = self.root / ".hardware-lifecycle" / "artifacts"

    def _project_path(self, relative_path: str | Path) -> Path:
        candidate = Path(relative_path)
        if candidate.is_absolute():
            raise ValueError("artifact path must be project-relative")
        resolved = (self.root / candidate).resolve()
        try:
            resolved.relative_to(self.root)
        except ValueError as exc:
            raise ValueError("artifact path escapes the project root") from exc
        if ".git" in resolved.relative_to(self.root).parts:
            raise ValueError("artifact path cannot target .git")
        return resolved

    def put_json(
        self,
        *,
        project_id: str,
        artifact_type: str,
        relative_path: str | Path,
        payload: dict[str, Any],
        producer_module: str,
        producer_version: str = "1.0.0",
        artifact_version: str = "1.0.0",
        source_identity: dict[str, Any] | None = None,
        upstream: list[dict[str, str]] | None = None,
        evidence: list[dict[str, Any]] | None = None,
        assumptions: list[str] | None = None,
        unknowns: list[str] | None = None,
        safety_notes: list[str] | None = None,
        replace: bool = False,
    ) -> StoredArtifact:
        if not project_id.strip() or not artifact_type.strip():
            raise ValueError("project_id and artifact_type must not be empty")
        target = self._project_path(relative_path)
        digest = _serialized_json_digest(payload)
        if target.exists():
            current = sha256_file(target)
            if current != digest and not replace:
                raise FileExistsError(
                    f"Refusing to replace changed canonical artifact without replace=True: {target}"
                )

        artifact_id = f"artifact:{uuid4()}"
        immutable_dir = self.store_root / digest
        immutable_payload = immutable_dir / "payload.json"
        if immutable_payload.exists() and sha256_file(immutable_payload) != digest:
            raise ValueError(f"content-addressed artifact is corrupt: {immutable_payload}")
        if not immutable_payload.exists():
            write_json_atomic(immutable_payload, payload, overwrite=False)
        write_json_atomic(target, payload)

        identity = {
            "projectUuid": None,
            "documentUuid": None,
            "documentType": None,
            "capturedAt": None,
        }
        if source_identity:
            identity.update(source_identity)
        envelope = {
            "schemaVersion": ARTIFACT_ENVELOPE_SCHEMA,
            "artifactId": artifact_id,
            "artifactType": artifact_type,
            "artifactVersion": artifact_version,
            "createdAt": utc_now(),
            "producer": {"module": producer_module, "version": producer_version},
            "project": {"projectId": project_id},
            "sourceIdentity": identity,
            "upstream": upstream or [],
            "payload": {
                "path": target.relative_to(self.root).as_posix(),
                "sha256": digest,
                "immutablePath": immutable_payload.relative_to(self.root).as_posix(),
            },
            "evidence": evidence or [],
            "assumptions": assumptions or [],
            "unknowns": unknowns or [],
            "safetyNotes": safety_notes or [],
        }
        envelope_path = immutable_dir / f"{artifact_id.split(':', 1)[1]}.envelope.json"
        write_json_atomic(envelope_path, envelope, overwrite=False)
        return StoredArtifact(
            artifact_id=artifact_id,
            artifact_type=artifact_type,
            payload_path=target.relative_to(self.root).as_posix(),
            envelope_path=envelope_path.relative_to(self.root).as_posix(),
            sha256=digest,
        )

    def verify_record(self, record: dict[str, Any]) -> list[str]:
        errors: list[str] = []
        path = record.get("path")
        digest = record.get("sha256")
        if not isinstance(path, str) or not path:
            return ["artifact record path is missing"]
        try:
            payload_path = self._project_path(path)
        except ValueError as exc:
            return [str(exc)]
        if not payload_path.is_file():
            errors.append(f"artifact payload is missing: {path}")
        elif not isinstance(digest, str) or sha256_file(payload_path) != digest.lower():
            errors.append(f"artifact payload digest mismatch: {path}")

        envelope_ref = record.get("envelope")
        if envelope_ref is not None:
            if not isinstance(envelope_ref, str):
                errors.append(f"artifact envelope path is invalid: {path}")
            else:
                try:
                    envelope_path = self._project_path(envelope_ref)
                    envelope = load_json(envelope_path)
                    if envelope.get("schemaVersion") != ARTIFACT_ENVELOPE_SCHEMA:
                        errors.append(f"artifact envelope schema mismatch: {envelope_ref}")
                    if (envelope.get("payload") or {}).get("sha256") != digest:
                        errors.append(f"artifact envelope digest mismatch: {envelope_ref}")
                    immutable = (envelope.get("payload") or {}).get("immutablePath")
                    if not isinstance(immutable, str) or sha256_file(self._project_path(immutable)) != digest:
                        errors.append(f"immutable artifact digest mismatch: {envelope_ref}")
                except (OSError, ValueError) as exc:
                    errors.append(f"cannot verify artifact envelope {envelope_ref}: {exc}")
        return errors
