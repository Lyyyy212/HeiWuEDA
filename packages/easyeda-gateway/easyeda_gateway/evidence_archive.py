"""Create a no-overwrite, self-verifying archive of local evidence files."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
from typing import Any
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from .artifact_io import sha256_file
from .errors import ContractError


EVIDENCE_ARCHIVE_SCHEMA = "easyeda.gateway.evidence-archive.v1"
_FIXED_ZIP_TIME = (1980, 1, 1, 0, 0, 0)


def _is_reparse_point(path: Path) -> bool:
    details = path.lstat()
    attributes = getattr(details, "st_file_attributes", 0)
    return path.is_symlink() or bool(attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0))


def _collect_files(source: Path) -> list[Path]:
    if _is_reparse_point(source):
        raise ContractError(f"Evidence source cannot be a link or reparse point: {source}")
    files: list[Path] = []
    for current, directories, names in os.walk(source, followlinks=False):
        current_path = Path(current)
        for name in sorted(directories):
            directory = current_path / name
            if _is_reparse_point(directory):
                raise ContractError(f"Evidence directory contains a link or reparse point: {directory}")
        for name in sorted(names):
            item = current_path / name
            if _is_reparse_point(item):
                raise ContractError(f"Evidence directory contains a link or reparse point: {item}")
            if not item.is_file():
                raise ContractError(f"Evidence entry is not a regular file: {item}")
            files.append(item)
    return sorted(files, key=lambda item: item.relative_to(source).as_posix())


def _zip_info(name: str) -> ZipInfo:
    info = ZipInfo(name, date_time=_FIXED_ZIP_TIME)
    info.compress_type = ZIP_DEFLATED
    info.create_system = 3
    info.external_attr = 0o100644 << 16
    return info


def create_evidence_archive(source_dir: str | Path, output_path: str | Path) -> dict[str, Any]:
    """Archive a directory with fixed metadata and an internal hash manifest."""

    source = Path(source_dir).resolve()
    output = Path(output_path).resolve()
    if not source.is_dir():
        raise ContractError(f"Evidence source directory does not exist: {source}")
    if output.exists():
        raise ContractError(f"Evidence archive already exists: {output}")
    if output == source or output.is_relative_to(source):
        raise ContractError("Evidence archive output must be outside the archived source directory")

    files = _collect_files(source)
    entries = [
        {
            "path": item.relative_to(source).as_posix(),
            "bytes": item.stat().st_size,
            "sha256": sha256_file(item),
        }
        for item in files
    ]
    manifest = {
        "schemaVersion": EVIDENCE_ARCHIVE_SCHEMA,
        "sourceDirectoryName": source.name,
        "fileCount": len(entries),
        "files": entries,
    }
    manifest_bytes = (
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")

    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        with output.open("xb") as raw_output:
            with ZipFile(raw_output, mode="w", compression=ZIP_DEFLATED, compresslevel=9) as archive:
                archive.writestr(_zip_info("evidence-manifest.json"), manifest_bytes)
                for entry, item in zip(entries, files, strict=True):
                    with item.open("rb") as source_handle, archive.open(
                        _zip_info(entry["path"]), mode="w"
                    ) as archive_handle:
                        shutil.copyfileobj(source_handle, archive_handle, length=1024 * 1024)
    except Exception:
        if output.exists():
            output.unlink()
        raise

    return {
        "success": True,
        "schemaVersion": EVIDENCE_ARCHIVE_SCHEMA,
        "sourceDirectory": str(source),
        "archive": {
            "path": str(output),
            "bytes": output.stat().st_size,
            "sha256": sha256_file(output),
        },
        "manifestSha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "fileCount": len(entries),
    }
