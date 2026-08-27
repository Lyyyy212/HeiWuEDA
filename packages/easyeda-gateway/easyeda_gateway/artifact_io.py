"""Shared immutable-artifact helpers for EasyEDA export adapters."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
from typing import Any, Mapping
from uuid import uuid4

from .contract import canonical_json
from .errors import ContractError


def identity_subset(value: Any) -> dict[str, Any]:
    item = dict(value) if isinstance(value, Mapping) else {}
    return {key: item.get(key) for key in ("projectUuid", "documentUuid", "documentType")}


def create_evidence_directory(evidence_root: str | Path, operation: str) -> Path:
    root = Path(evidence_root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    directory = root / f"{stamp}-{operation}-{uuid4().hex[:8]}"
    directory.mkdir(parents=False, exist_ok=False)
    return directory


def publish_copy_no_overwrite(source: Path, target: Path) -> None:
    temporary = target.with_name(f".{uuid4().hex[:8]}.tmp")
    try:
        shutil.copyfile(source, temporary)
        try:
            os.link(temporary, target)
        except FileExistsError as exc:
            raise ContractError(f"Published EasyEDA artifact already exists: {target}") from exc
        except OSError:
            try:
                with temporary.open("rb") as source_handle, target.open("xb") as target_handle:
                    shutil.copyfileobj(source_handle, target_handle)
            except FileExistsError as exc:
                raise ContractError(f"Published EasyEDA artifact already exists: {target}") from exc
    finally:
        if temporary.exists():
            temporary.unlink()


def atomic_write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{uuid4().hex[:8]}.tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
