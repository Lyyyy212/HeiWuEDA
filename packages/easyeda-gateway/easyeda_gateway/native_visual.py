"""Validate official native EasyEDA PNG files and multi-page PNG bundles."""

from __future__ import annotations

import json
from pathlib import Path, PurePosixPath
from typing import Any, Mapping
import zipfile

from .artifact_io import (
    atomic_write_json,
    create_evidence_directory,
    identity_subset,
    sha256_file,
    utc_now,
)
from .errors import BridgeError, ContractError


PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
NATIVE_PNG_BUNDLE_CONTAINER = "easyeda.official-native-png-bundle.v1"
NATIVE_PNG_BUNDLE_EXECUTION_SCHEMA = "easyeda.gateway.native-png-bundle-normalization.v1"
NATIVE_PNG_BUNDLE_EVIDENCE_SCHEMA = "easyeda.gateway.native-png-bundle-evidence.v1"
MAX_BUNDLE_ENTRIES = 100
MAX_ENTRY_BYTES = 50 * 1024 * 1024
MAX_TOTAL_BYTES = 250 * 1024 * 1024


def inspect_png_bytes(data: bytes, label: str = "PNG") -> dict[str, Any]:
    if len(data) < 24 or data[:8] != PNG_SIGNATURE or data[12:16] != b"IHDR":
        raise BridgeError(f"{label} has an invalid PNG signature or IHDR")
    if int.from_bytes(data[8:12], "big") != 13:
        raise BridgeError(f"{label} has an invalid IHDR length")
    width = int.from_bytes(data[16:20], "big")
    height = int.from_bytes(data[20:24], "big")
    if width <= 0 or height <= 0:
        raise BridgeError(f"{label} has invalid dimensions")
    return {"mediaType": "image/png", "width": width, "height": height}


def inspect_native_png_artifact(path: Path, *, extract_dir: Path) -> dict[str, Any]:
    data = path.read_bytes()
    if data.startswith(PNG_SIGNATURE):
        return inspect_png_bytes(data, "Schematic PNG export")
    if not zipfile.is_zipfile(path):
        raise BridgeError("Schematic PNG export is neither a PNG nor an official PNG bundle")
    return _extract_png_bundle(path, extract_dir)


def _extract_png_bundle(source: Path, extract_dir: Path) -> dict[str, Any]:
    if extract_dir.exists():
        raise ContractError(f"Native PNG extraction directory already exists: {extract_dir}")
    pages: list[dict[str, Any]] = []
    seen_names: set[str] = set()
    total_bytes = 0
    with zipfile.ZipFile(source, "r") as archive:
        entries = [item for item in archive.infolist() if not item.is_dir()]
        if not entries or len(entries) > MAX_BUNDLE_ENTRIES:
            raise BridgeError("Official PNG bundle has an invalid page count")
        extract_dir.mkdir(parents=True, exist_ok=False)
        for index, entry in enumerate(entries, start=1):
            normalized = entry.filename.replace("\\", "/")
            pure = PurePosixPath(normalized)
            if pure.is_absolute() or ".." in pure.parts or len(pure.parts) != 1:
                raise BridgeError(f"Official PNG bundle contains an unsafe entry: {entry.filename}")
            key = normalized.casefold()
            if key in seen_names:
                raise BridgeError(f"Official PNG bundle contains a duplicate entry: {entry.filename}")
            seen_names.add(key)
            if pure.suffix.lower() != ".png":
                raise BridgeError(f"Official PNG bundle contains a non-PNG entry: {entry.filename}")
            if entry.flag_bits & 0x1:
                raise BridgeError(f"Official PNG bundle contains an encrypted entry: {entry.filename}")
            if entry.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}:
                raise BridgeError(f"Official PNG bundle uses an unsupported compression method: {entry.filename}")
            unix_type = (entry.external_attr >> 16) & 0o170000
            if unix_type == 0o120000:
                raise BridgeError(f"Official PNG bundle contains a symbolic link: {entry.filename}")
            if entry.file_size <= 0 or entry.file_size > MAX_ENTRY_BYTES:
                raise BridgeError(f"Official PNG bundle entry has an invalid size: {entry.filename}")
            total_bytes += entry.file_size
            if total_bytes > MAX_TOTAL_BYTES:
                raise BridgeError("Official PNG bundle exceeds the total uncompressed size limit")
            data = archive.read(entry)
            if len(data) != entry.file_size:
                raise BridgeError(f"Official PNG bundle entry size changed while reading: {entry.filename}")
            inspection = inspect_png_bytes(data, f"Official PNG bundle entry {entry.filename}")
            target = extract_dir / f"{index:03d}-official-native.png"
            with target.open("xb") as handle:
                handle.write(data)
            pages.append({
                "index": index,
                "entryName": entry.filename,
                "path": str(target),
                "sha256": sha256_file(target),
                "bytes": len(data),
                **inspection,
            })
    return {
        "mediaType": "application/zip",
        "containerFormat": NATIVE_PNG_BUNDLE_CONTAINER,
        "pageCount": len(pages),
        "totalUncompressedBytes": total_bytes,
        "pages": pages,
    }


def normalize_existing_official_png_bundle(
    *,
    source: Path,
    source_envelope_path: Path,
    identity_before: Mapping[str, Any],
    identity_after: Mapping[str, Any],
    evidence_root: Path,
    output_path: Path,
) -> dict[str, Any]:
    """Qualify an already-issued official multi-page PNG artifact without another API call."""
    source = source.resolve()
    source_envelope_path = source_envelope_path.resolve()
    output_path = output_path.resolve()
    if output_path.exists():
        raise ContractError(f"Native PNG normalization output already exists: {output_path}")
    source_envelope = json.loads(source_envelope_path.read_text(encoding="utf-8"))
    if source_envelope.get("schemaVersion") != "easyeda.gateway.schematic-export-evidence.v1":
        raise ContractError("Source export evidence schema is invalid")
    if source_envelope.get("status") != "FAIL":
        raise ContractError("Existing-artifact normalization requires the preserved validation failure")
    error = source_envelope.get("error")
    if not isinstance(error, Mapping) or error.get("message") != "Schematic PNG export has an invalid PNG signature or IHDR":
        raise ContractError("Source failure is not the admitted legacy PNG-signature misclassification")
    spec = source_envelope.get("spec")
    if not isinstance(spec, Mapping) or spec.get("fileType") != "PNG" or spec.get("scope") != "current-schematic":
        raise ContractError("Source export was not an official current-schematic PNG request")
    expected = identity_subset(source_envelope.get("expectedIdentity"))
    before = identity_subset(identity_before)
    after = identity_subset(identity_after)
    if before != after or before.get("documentType") != 1:
        raise ContractError("EasyEDA identity changed or is not a schematic page")
    for key in ("projectUuid", "documentUuid"):
        if expected.get(key) != before.get(key):
            raise ContractError(f"Source export identity differs from the guarded {key}")
    if not source.is_file() or source.parent != source_envelope_path.parent:
        raise ContractError("Source artifact is not inside its immutable evidence directory")
    source_sha256 = sha256_file(source)
    files = source_envelope.get("files")
    if not isinstance(files, Mapping) or files.get(source.name) != source_sha256:
        raise ContractError("Source artifact digest is not sealed by the failure evidence")

    evidence_directory = create_evidence_directory(evidence_root, "native-png-bundle-normalization")
    inspection = inspect_native_png_artifact(
        source,
        extract_dir=evidence_directory / "native-pages",
    )
    if inspection.get("containerFormat") != NATIVE_PNG_BUNDLE_CONTAINER:
        raise ContractError("Existing-artifact normalization requires an official multi-page PNG bundle")
    pages = inspection["pages"]
    evidence = {
        "schemaVersion": NATIVE_PNG_BUNDLE_EVIDENCE_SCHEMA,
        "status": "PASS",
        "risk": "LOCAL_ONLY_NO_EASYEDA_CALLS",
        "createdAt": utc_now(),
        "identity": before,
        "sourceOfficialCallEvidencePath": str(source_envelope_path),
        "sourceOfficialCallStatus": "ARTIFACT_WRITTEN_VALIDATION_FAILED",
        "sourceArtifact": {
            "path": str(source),
            "sha256": source_sha256,
            "bytes": source.stat().st_size,
            "mediaType": "application/zip",
            "containerFormat": NATIVE_PNG_BUNDLE_CONTAINER,
        },
        "spec": dict(spec),
        "safety": {
            "capabilityId": "visual.current-schematic.png",
            "automaticRetry": False,
            "officialCallRepeated": False,
        },
        "easyedaApiCallCount": 0,
        "pageCount": len(pages),
        "pages": pages,
        "files": {Path(item["path"]).relative_to(evidence_directory).as_posix(): item["sha256"] for item in pages},
    }
    evidence_path = evidence_directory / "envelope.json"
    atomic_write_json(evidence_path, evidence)
    execution = {
        "success": True,
        "schemaVersion": NATIVE_PNG_BUNDLE_EXECUTION_SCHEMA,
        "identity": before,
        "spec": dict(spec),
        "sourceArtifact": evidence["sourceArtifact"],
        "pageCount": len(pages),
        "pages": pages,
        "evidencePath": str(evidence_path),
        "easyedaApiCallCount": 0,
        "automaticRetry": False,
    }
    atomic_write_json(output_path, execution)
    return execution
