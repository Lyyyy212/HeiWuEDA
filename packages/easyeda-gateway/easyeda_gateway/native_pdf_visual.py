"""Render an admitted official EasyEDA PDF into bounded Cowart PNG evidence."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
from typing import Any, Mapping

from .artifact_io import (
    atomic_write_json,
    create_evidence_directory,
    identity_subset,
    sha256_file,
    utc_now,
)
from .errors import BridgeError, ContractError
from .native_visual import inspect_png_bytes


PDF_RENDER_EXECUTION_SCHEMA = "easyeda.gateway.native-pdf-visual-render.v1"
PDF_RENDER_EVIDENCE_SCHEMA = "easyeda.gateway.native-pdf-visual-evidence.v1"
SCHEMATIC_EXPORT_EXECUTION_SCHEMA = "easyeda.gateway.schematic-export-execution.v1"
SCHEMATIC_EXPORT_EVIDENCE_SCHEMA = "easyeda.gateway.schematic-export-evidence.v1"
DEFAULT_MAX_LONG_EDGE = 6144
MIN_LONG_EDGE = 1024
MAX_LONG_EDGE = 8192
MAX_PDF_BYTES = 250 * 1024 * 1024
MAX_PAGES = 100
MAX_RENDERED_PAGE_BYTES = 64 * 1024 * 1024
MAX_RENDERED_TOTAL_BYTES = 512 * 1024 * 1024
DEFAULT_RENDER_TIMEOUT_SECONDS = 300.0


def render_existing_official_pdf(
    *,
    source_execution: Mapping[str, Any],
    identity_before: Mapping[str, Any],
    identity_after: Mapping[str, Any],
    evidence_root: Path,
    output_path: Path,
    pdftoppm_path: Path | None = None,
    max_long_edge: int = DEFAULT_MAX_LONG_EDGE,
    timeout_seconds: float = DEFAULT_RENDER_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Render one already-exported official current-schematic PDF without Bridge calls."""

    output_path = output_path.resolve()
    if output_path.exists():
        raise ContractError(f"Native PDF visual render output already exists: {output_path}")
    if not isinstance(max_long_edge, int) or not MIN_LONG_EDGE <= max_long_edge <= MAX_LONG_EDGE:
        raise ContractError(
            f"max-long-edge must be an integer from {MIN_LONG_EDGE} through {MAX_LONG_EDGE}",
        )
    if timeout_seconds <= 0 or timeout_seconds > 1800:
        raise ContractError("PDF render timeout must be greater than 0 and no more than 1800 seconds")

    before = identity_subset(identity_before)
    after = identity_subset(identity_after)
    if before != after or before.get("documentType") != 1:
        raise ContractError("EasyEDA identity changed or is not a schematic page")

    source_path, source_sha256, source_bytes, source_evidence_path = _validate_source_execution(
        source_execution,
        before,
    )
    page_geometry = _inspect_pdf(source_path)
    renderer = _discover_pdftoppm(pdftoppm_path)
    renderer_record = {
        "name": "pdftoppm",
        "path": str(renderer),
        "sha256": sha256_file(renderer),
        "version": _renderer_version(renderer),
    }

    evidence_directory = create_evidence_directory(evidence_root, "native-pdf-visual-render")
    request = {
        "schemaVersion": "easyeda.gateway.native-pdf-visual-request.v1",
        "risk": "LOCAL_ONLY_NO_EASYEDA_CALLS",
        "identity": before,
        "sourceOfficialExecutionSchema": source_execution.get("schemaVersion"),
        "sourceOfficialEvidencePath": str(source_evidence_path),
        "sourceArtifact": {
            "path": str(source_path),
            "sha256": source_sha256,
            "bytes": source_bytes,
            "mediaType": "application/pdf",
        },
        "renderSettings": {
            "format": "PNG",
            "maxLongEdge": max_long_edge,
            "timeoutSeconds": timeout_seconds,
            "background": "white",
        },
        "renderer": renderer_record,
        "easyedaApiCallCount": 0,
        "automaticRetry": False,
    }
    atomic_write_json(evidence_directory / "request.json", request)

    temporary_directory = evidence_directory / ".rendering"
    pages_directory = evidence_directory / "native-pages"
    try:
        temporary_directory.mkdir(parents=False, exist_ok=False)
        rendered = _run_pdftoppm(
            renderer,
            source_path,
            temporary_directory,
            len(page_geometry),
            max_long_edge,
            timeout_seconds,
        )
        pages_directory.mkdir(parents=False, exist_ok=False)
        pages: list[dict[str, Any]] = []
        total_bytes = 0
        for index, temporary_png in enumerate(rendered, start=1):
            data = temporary_png.read_bytes()
            inspection = inspect_png_bytes(data, f"Rendered PDF page {index}")
            if max(inspection["width"], inspection["height"]) > max_long_edge:
                raise BridgeError(
                    f"Rendered PDF page {index} exceeds the {max_long_edge}px long-edge limit",
                )
            page_bytes = len(data)
            if page_bytes <= 0 or page_bytes > MAX_RENDERED_PAGE_BYTES:
                raise BridgeError(f"Rendered PDF page {index} exceeds the per-page size limit")
            total_bytes += page_bytes
            if total_bytes > MAX_RENDERED_TOTAL_BYTES:
                raise BridgeError("Rendered PDF pages exceed the total size limit")
            target = pages_directory / f"{index:03d}-official-pdf-render.png"
            temporary_png.replace(target)
            pages.append({
                "index": index,
                "pdfPageIndex": index,
                "entryName": f"pdf-page-{index:03d}.png",
                "path": str(target),
                "sha256": sha256_file(target),
                "bytes": page_bytes,
                **inspection,
                "sourcePageWidthPoints": page_geometry[index - 1]["widthPoints"],
                "sourcePageHeightPoints": page_geometry[index - 1]["heightPoints"],
                "sourcePageRotation": page_geometry[index - 1]["rotation"],
            })

        result = {
            "schemaVersion": "easyeda.gateway.native-pdf-visual-result.v1",
            "sourceArtifact": request["sourceArtifact"],
            "pageCount": len(pages),
            "renderedTotalBytes": total_bytes,
            "pages": pages,
            "renderSettings": request["renderSettings"],
            "renderer": renderer_record,
        }
        atomic_write_json(evidence_directory / "result.json", result)
        files = {
            "request.json": sha256_file(evidence_directory / "request.json"),
            "result.json": sha256_file(evidence_directory / "result.json"),
        }
        files.update({
            Path(item["path"]).relative_to(evidence_directory).as_posix(): item["sha256"]
            for item in pages
        })
        evidence = {
            "schemaVersion": PDF_RENDER_EVIDENCE_SCHEMA,
            "status": "PASS",
            "risk": "LOCAL_ONLY_NO_EASYEDA_CALLS",
            "createdAt": utc_now(),
            "identity": before,
            "sourceOfficialEvidencePath": str(source_evidence_path),
            "sourceArtifact": request["sourceArtifact"],
            "sourceSpec": dict(source_execution.get("spec") or {}),
            "safety": {
                "sourceCapabilityId": "visual.current-schematic.pdf",
                "officialCallRepeated": False,
                "automaticRetry": False,
                "maxLongEdge": max_long_edge,
            },
            "easyedaApiCallCount": 0,
            "pageCount": len(pages),
            "renderedTotalBytes": total_bytes,
            "pages": pages,
            "renderSettings": request["renderSettings"],
            "renderer": renderer_record,
            "files": files,
        }
        evidence_path = evidence_directory / "envelope.json"
        atomic_write_json(evidence_path, evidence)
        execution = {
            "success": True,
            "schemaVersion": PDF_RENDER_EXECUTION_SCHEMA,
            "identity": before,
            "spec": dict(source_execution.get("spec") or {}),
            "sourceArtifact": request["sourceArtifact"],
            "pageCount": len(pages),
            "pages": pages,
            "renderSettings": request["renderSettings"],
            "renderer": renderer_record,
            "evidencePath": str(evidence_path),
            "easyedaApiCallCount": 0,
            "automaticRetry": False,
        }
        atomic_write_json(output_path, execution)
        return execution
    except Exception as exc:
        failure = {
            "schemaVersion": PDF_RENDER_EVIDENCE_SCHEMA,
            "status": "FAIL",
            "risk": "LOCAL_ONLY_NO_EASYEDA_CALLS",
            "createdAt": utc_now(),
            "identity": before,
            "sourceOfficialEvidencePath": str(source_evidence_path),
            "sourceArtifact": request["sourceArtifact"],
            "renderSettings": request["renderSettings"],
            "renderer": renderer_record,
            "easyedaApiCallCount": 0,
            "automaticRetry": False,
            "error": {"type": type(exc).__name__, "message": str(exc)},
            "files": {"request.json": sha256_file(evidence_directory / "request.json")},
        }
        atomic_write_json(evidence_directory / "envelope.json", failure)
        raise
    finally:
        shutil.rmtree(temporary_directory, ignore_errors=True)


def _validate_source_execution(
    execution: Mapping[str, Any],
    expected_identity: Mapping[str, Any],
) -> tuple[Path, str, int, Path]:
    if execution.get("schemaVersion") != SCHEMATIC_EXPORT_EXECUTION_SCHEMA:
        raise ContractError("Source execution is not an official schematic export execution")
    if execution.get("success") is False:
        raise ContractError("Source official PDF export did not succeed")
    if identity_subset(execution.get("identity")) != dict(expected_identity):
        raise ContractError("Source official PDF identity differs from the guarded schematic")
    spec = execution.get("spec")
    if not isinstance(spec, Mapping) or spec.get("fileType") != "PDF" or spec.get("scope") != "current-schematic":
        raise ContractError("Source must be an official current-schematic PDF export")
    artifact = execution.get("artifact")
    if not isinstance(artifact, Mapping):
        raise ContractError("Source official PDF artifact record is invalid")
    path_value = artifact.get("path")
    digest = artifact.get("sha256")
    if not isinstance(path_value, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", str(digest or "")):
        raise ContractError("Source official PDF path or digest is invalid")
    source = Path(path_value).resolve()
    if source.suffix.lower() != ".pdf" or not source.is_file():
        raise ContractError("Source official PDF artifact is missing or has the wrong suffix")
    source_bytes = source.stat().st_size
    if source_bytes <= 0 or source_bytes > MAX_PDF_BYTES:
        raise ContractError("Source official PDF artifact exceeds the admitted size")
    actual_digest = sha256_file(source)
    if actual_digest.lower() != str(digest).lower():
        raise ContractError("Source official PDF artifact digest mismatch")
    if artifact.get("mediaType") != "application/pdf":
        raise ContractError("Source official artifact is not declared as application/pdf")

    evidence_value = execution.get("evidencePath")
    if not isinstance(evidence_value, str):
        raise ContractError("Source official PDF evidencePath is required")
    evidence_path = Path(evidence_value).resolve()
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    if evidence.get("schemaVersion") != SCHEMATIC_EXPORT_EVIDENCE_SCHEMA or evidence.get("status") != "PASS":
        raise ContractError("Source official PDF evidence is not PASS")
    if identity_subset(evidence.get("identity")) != dict(expected_identity):
        raise ContractError("Source official PDF evidence identity differs from the guarded schematic")
    safety = evidence.get("safety")
    if (
        not isinstance(safety, Mapping)
        or safety.get("capabilityId") != "visual.current-schematic.pdf"
        or safety.get("automaticRetry") is not False
    ):
        raise ContractError("Source official PDF evidence did not use the admitted serial capability")
    if source.parent != evidence_path.parent:
        raise ContractError("Source official PDF is outside its immutable evidence directory")
    files = evidence.get("files")
    relative = source.relative_to(evidence_path.parent).as_posix()
    if not isinstance(files, Mapping) or files.get(relative) != actual_digest:
        raise ContractError("Source official PDF is not sealed by export evidence")
    return source, actual_digest, source_bytes, evidence_path


def _inspect_pdf(source: Path) -> list[dict[str, Any]]:
    if not source.read_bytes()[:5] == b"%PDF-":
        raise BridgeError("Source official PDF has an invalid signature")
    try:
        from pypdf import PdfReader

        reader = PdfReader(str(source), strict=True)
        if reader.is_encrypted:
            raise BridgeError("Encrypted PDF files are not admitted for canvas rendering")
        if not 1 <= len(reader.pages) <= MAX_PAGES:
            raise BridgeError(f"Official PDF page count must be from 1 through {MAX_PAGES}")
        geometry = []
        for index, page in enumerate(reader.pages, start=1):
            width = float(page.mediabox.width)
            height = float(page.mediabox.height)
            if not width > 0 or not height > 0:
                raise BridgeError(f"Official PDF page {index} has invalid dimensions")
            rotation = int(page.get("/Rotate", 0) or 0) % 360
            geometry.append({
                "index": index,
                "widthPoints": round(width, 6),
                "heightPoints": round(height, 6),
                "rotation": rotation,
            })
        return geometry
    except BridgeError:
        raise
    except Exception as exc:
        raise BridgeError(f"Cannot validate official PDF before rendering: {exc}") from exc


def _discover_pdftoppm(requested: Path | None) -> Path:
    candidates: list[Path] = []
    if requested is not None:
        candidates.append(requested)
    configured = os.environ.get("POPPLER_BIN")
    if configured:
        candidates.append(Path(configured) / ("pdftoppm.exe" if os.name == "nt" else "pdftoppm"))
    discovered = shutil.which("pdftoppm")
    if discovered:
        candidates.append(Path(discovered))
    if os.name == "nt":
        runtime_root = Path.home() / ".cache" / "codex-runtimes"
        candidates.append(
            runtime_root
            / "codex-primary-runtime"
            / "dependencies"
            / "native"
            / "poppler"
            / "Library"
            / "bin"
            / "pdftoppm.exe"
        )
        if runtime_root.is_dir():
            candidates.extend(runtime_root.glob("*/dependencies/native/poppler/Library/bin/pdftoppm.exe"))
    for candidate in candidates:
        resolved = candidate.expanduser().resolve()
        if resolved.is_file():
            return resolved
    raise ContractError(
        "pdftoppm was not found; pass --pdftoppm or install Poppler before rendering the official PDF",
    )


def _renderer_version(renderer: Path) -> str:
    creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    try:
        completed = subprocess.run(
            [str(renderer), "-v"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
            check=False,
            creationflags=creationflags,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ContractError(f"Cannot identify pdftoppm: {exc}") from exc
    detail = (completed.stderr or completed.stdout).strip().splitlines()
    if completed.returncode != 0 or not detail:
        raise ContractError("pdftoppm version check failed")
    return detail[0][:200]


def _run_pdftoppm(
    renderer: Path,
    source: Path,
    temporary_directory: Path,
    page_count: int,
    max_long_edge: int,
    timeout_seconds: float,
) -> list[Path]:
    prefix = temporary_directory / "rendered"
    command = [
        str(renderer),
        "-png",
        "-scale-to",
        str(max_long_edge),
        "-f",
        "1",
        "-l",
        str(page_count),
        str(source),
        str(prefix),
    ]
    creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    try:
        completed = subprocess.run(
            command,
            cwd=str(temporary_directory),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
            check=False,
            creationflags=creationflags,
        )
    except subprocess.TimeoutExpired as exc:
        raise BridgeError(f"PDF rendering exceeded {timeout_seconds:g} seconds") from exc
    except (OSError, subprocess.SubprocessError) as exc:
        raise BridgeError(f"Cannot run pdftoppm: {exc}") from exc
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "unknown error").strip()
        raise BridgeError(f"pdftoppm failed ({completed.returncode}): {detail[:2000]}")

    numbered: dict[int, Path] = {}
    for candidate in temporary_directory.glob("rendered-*.png"):
        match = re.fullmatch(r"rendered-(\d+)\.png", candidate.name, re.IGNORECASE)
        if not match:
            continue
        page_index = int(match.group(1))
        if page_index in numbered:
            raise BridgeError(f"pdftoppm emitted duplicate page {page_index}")
        numbered[page_index] = candidate
    expected = list(range(1, page_count + 1))
    if sorted(numbered) != expected:
        raise BridgeError(
            f"pdftoppm page inventory mismatch: expected {expected}, got {sorted(numbered)}",
        )
    return [numbered[index] for index in expected]
