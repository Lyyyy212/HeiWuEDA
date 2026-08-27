"""Offline V2.2 EPRO to SVG/PNG/PDF rendering with immutable evidence."""

from __future__ import annotations

from dataclasses import dataclass
import os
import shutil
from pathlib import Path
from typing import Any

from .artifact_io import (
    atomic_write_json,
    create_evidence_directory,
    publish_copy_no_overwrite,
    sha256_file,
    utc_now,
)
from .errors import ContractError
from .source_renderer_v22 import (
    PdfSourceError,
    convert_svg_to_png,
    convert_svg_to_pdf,
    list_v22_sheets,
    load_v22_archive,
    render_svg,
)


SOURCE_RENDER_SCHEMA = "easyeda.gateway.offline-source-render.v1"
SOURCE_RENDER_ADAPTER_VERSION = "1.2.0"
PROJECT_SOURCE_RENDER_SCHEMA = "easyeda.gateway.offline-project-source-render.v1"
PROJECT_SOURCE_RENDER_ADAPTER_VERSION = "1.0.0"


def _render_quality() -> dict[str, Any]:
    """Describe what the local renderer proves without overstating fidelity."""

    return {
        "structuralStatus": "PASS",
        "visualStatus": "UNQUALIFIED",
        "visualReviewRequired": True,
        "limitations": [
            "Artifact generation proves that the selected EPRO page was parsed and rendered, not that the result matches EasyEDA native layout pixel-for-pixel.",
            "Complex rotation, mirroring, symbol text overrides, and unsupported records require visual comparison before design decisions.",
        ],
    }


@dataclass(frozen=True)
class SourceRenderSpec:
    document_uuid: str
    margin: float = 20.0
    render_png: bool = False
    render_pdf: bool = False

    def validate(self) -> "SourceRenderSpec":
        document_uuid = self.document_uuid.strip()
        if not document_uuid:
            raise ContractError("Offline source render requires the exported page document UUID")
        if self.margin < 0:
            raise ContractError("Offline source render margin cannot be negative")
        return SourceRenderSpec(
            document_uuid,
            float(self.margin),
            bool(self.render_png),
            bool(self.render_pdf),
        )


@dataclass(frozen=True)
class SourceRenderResult:
    source_path: Path
    source_sha256: str
    svg_path: Path
    svg_sha256: str
    png_path: Path | None
    png_sha256: str | None
    pdf_path: Path | None
    pdf_sha256: str | None
    evidence_path: Path
    published_svg: Path | None = None
    published_png: Path | None = None
    published_pdf: Path | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "schemaVersion": SOURCE_RENDER_SCHEMA,
            "adapterVersion": SOURCE_RENDER_ADAPTER_VERSION,
            "renderStatus": "STRUCTURAL_PASS",
            "visualStatus": "UNQUALIFIED",
            "quality": _render_quality(),
            "executionModel": "LOCAL_ONLY_NO_EASYEDA_CALLS",
            "source": {"path": str(self.source_path), "sha256": self.source_sha256},
            "svg": {"path": str(self.svg_path), "sha256": self.svg_sha256},
            "png": (
                {"path": str(self.png_path), "sha256": self.png_sha256}
                if self.png_path is not None
                else None
            ),
            "pdf": (
                {"path": str(self.pdf_path), "sha256": self.pdf_sha256}
                if self.pdf_path is not None
                else None
            ),
            "publishedSvg": str(self.published_svg) if self.published_svg else None,
            "publishedPng": str(self.published_png) if self.published_png else None,
            "publishedPdf": str(self.published_pdf) if self.published_pdf else None,
            "evidencePath": str(self.evidence_path),
        }


class OfflineSourceRenderAdapter:
    """Render an already-exported EPRO archive without touching the EDA process."""

    def execute(
        self,
        spec: SourceRenderSpec,
        source_path: str | Path,
        evidence_root: str | Path,
        *,
        svg_output: str | Path | None = None,
        png_output: str | Path | None = None,
        pdf_output: str | Path | None = None,
        node_executable: str | Path | None = None,
        node_path: str | Path | None = None,
        conversion_timeout: float = 45.0,
    ) -> SourceRenderResult:
        value = spec.validate()
        source = Path(source_path).resolve()
        if not source.is_file() or source.stat().st_size <= 0:
            raise ContractError(f"EPRO source does not exist or is empty: {source}")
        if source.suffix.lower() != ".epro":
            raise ContractError("Offline V2.2 source render requires an .epro archive")
        published_svg = Path(svg_output).resolve() if svg_output else None
        published_png = Path(png_output).resolve() if png_output else None
        published_pdf = Path(pdf_output).resolve() if pdf_output else None
        if published_svg is not None and published_svg.exists():
            raise ContractError(f"SVG output already exists: {published_svg}")
        if published_pdf is not None and published_pdf.exists():
            raise ContractError(f"PDF output already exists: {published_pdf}")
        if published_png is not None and published_png.exists():
            raise ContractError(f"PNG output already exists: {published_png}")
        if published_png is not None and not value.render_png:
            raise ContractError("--png-output requires PNG rendering to be enabled")
        if published_pdf is not None and not value.render_pdf:
            raise ContractError("--pdf-output requires PDF rendering to be enabled")

        evidence_dir = create_evidence_directory(evidence_root, "offline-source-render")
        evidence_path = evidence_dir / "envelope.json"
        svg_path = evidence_dir / "source-render.svg"
        png_path = evidence_dir / "source-render.png" if value.render_png else None
        pdf_path = evidence_dir / "source-render.pdf" if value.render_pdf else None
        report: dict[str, Any] = {
            "schemaVersion": SOURCE_RENDER_SCHEMA,
            "adapterVersion": SOURCE_RENDER_ADAPTER_VERSION,
            "capturedAt": utc_now(),
            "status": "BLOCKED",
            "renderStatus": "BLOCKED",
            "quality": {
                "structuralStatus": "BLOCKED",
                "visualStatus": "NOT_EVALUATED",
                "visualReviewRequired": True,
                "limitations": [],
            },
            "executionModel": "LOCAL_ONLY_NO_EASYEDA_CALLS",
            "easyedaApiCallCount": 0,
            "uiFreezeRisk": "NONE_FROM_RENDERER",
            "spec": {
                "documentUuid": value.document_uuid,
                "margin": value.margin,
                "renderPng": value.render_png,
                "renderPdf": value.render_pdf,
            },
            "source": {
                "path": str(source),
                "sha256": sha256_file(source),
                "bytes": source.stat().st_size,
            },
            "artifacts": {},
            "error": None,
        }
        try:
            archive = load_v22_archive(source, value.document_uuid)
            rendered = render_svg(archive, margin=value.margin)
            with svg_path.open("x", encoding="utf-8", newline="\n") as handle:
                handle.write(rendered.svg)
            report["records"] = {
                "counts": archive.record_counts,
                "referencedSymbols": list(archive.referenced_symbol_ids),
                "unsupported": list(rendered.unsupported_records),
            }
            report["artifacts"]["svg"] = {
                "path": str(svg_path),
                "sha256": sha256_file(svg_path),
                "bytes": svg_path.stat().st_size,
                "width": rendered.width,
                "height": rendered.height,
                "primitiveCount": rendered.primitive_count,
            }
            if png_path is not None:
                node = Path(node_executable).resolve() if node_executable else _discover_node()
                resolved_node_path = (
                    Path(node_path).resolve() if node_path else _discover_node_path()
                )
                png_info = convert_svg_to_png(
                    svg_path,
                    png_path,
                    node_executable=node,
                    node_path=resolved_node_path,
                    timeout=conversion_timeout,
                )
                report["artifacts"]["png"] = {
                    "path": str(png_path),
                    "sha256": sha256_file(png_path),
                    "bytes": png_info.bytes,
                    "width": png_info.width,
                    "height": png_info.height,
                }
            if pdf_path is not None:
                node = Path(node_executable).resolve() if node_executable else _discover_node()
                resolved_node_path = (
                    Path(node_path).resolve() if node_path else _discover_node_path()
                )
                pdf_info = convert_svg_to_pdf(
                    svg_path,
                    pdf_path,
                    node_executable=node,
                    node_path=resolved_node_path,
                    timeout=conversion_timeout,
                )
                report["artifacts"]["pdf"] = {
                    "path": str(pdf_path),
                    "sha256": sha256_file(pdf_path),
                    "bytes": pdf_path.stat().st_size,
                    "pageCount": pdf_info.page_count,
                    "contentStreamBytes": pdf_info.content_stream_bytes,
                }
            if published_svg is not None:
                published_svg.parent.mkdir(parents=True, exist_ok=True)
                publish_copy_no_overwrite(svg_path, published_svg)
            if published_png is not None and png_path is not None:
                published_png.parent.mkdir(parents=True, exist_ok=True)
                publish_copy_no_overwrite(png_path, published_png)
            if published_pdf is not None and pdf_path is not None:
                published_pdf.parent.mkdir(parents=True, exist_ok=True)
                publish_copy_no_overwrite(pdf_path, published_pdf)
            report["status"] = "PASS"
            report["renderStatus"] = "STRUCTURAL_PASS"
            report["quality"] = _render_quality()
            report["published"] = {
                "svg": str(published_svg) if published_svg else None,
                "png": str(published_png) if published_png else None,
                "pdf": str(published_pdf) if published_pdf else None,
            }
            atomic_write_json(evidence_path, report)
        except (PdfSourceError, ContractError, OSError, ValueError) as exc:
            report["error"] = str(exc)
            atomic_write_json(evidence_path, report)
            raise ContractError(
                f"Offline EPRO rendering failed; EasyEDA was not called. Evidence: {evidence_path}. {exc}"
            ) from exc

        return SourceRenderResult(
            source_path=source,
            source_sha256=report["source"]["sha256"],
            svg_path=svg_path,
            svg_sha256=report["artifacts"]["svg"]["sha256"],
            png_path=png_path,
            png_sha256=(report["artifacts"].get("png") or {}).get("sha256"),
            pdf_path=pdf_path,
            pdf_sha256=(report["artifacts"].get("pdf") or {}).get("sha256"),
            evidence_path=evidence_path,
            published_svg=published_svg,
            published_png=published_png,
            published_pdf=published_pdf,
        )


@dataclass(frozen=True)
class ProjectSourceRenderResult:
    source_path: Path
    source_sha256: str
    output_directory: Path
    pages: tuple[dict[str, Any], ...]
    evidence_path: Path

    def as_dict(self) -> dict[str, Any]:
        return {
            "schemaVersion": PROJECT_SOURCE_RENDER_SCHEMA,
            "adapterVersion": PROJECT_SOURCE_RENDER_ADAPTER_VERSION,
            "renderStatus": "STRUCTURAL_PASS",
            "visualStatus": "UNQUALIFIED",
            "quality": _render_quality(),
            "executionModel": "LOCAL_ONLY_NO_EASYEDA_CALLS",
            "easyedaApiCallCount": 0,
            "source": {"path": str(self.source_path), "sha256": self.source_sha256},
            "outputDirectory": str(self.output_directory),
            "pageCount": len(self.pages),
            "pages": list(self.pages),
            "evidencePath": str(self.evidence_path),
        }


class OfflineProjectSourceRenderAdapter:
    """Enumerate and render every schematic page in one exported project EPRO."""

    def execute(
        self,
        source_path: str | Path,
        evidence_root: str | Path,
        output_directory: str | Path,
        *,
        margin: float = 20.0,
        node_executable: str | Path | None = None,
        node_path: str | Path | None = None,
        conversion_timeout: float = 45.0,
    ) -> ProjectSourceRenderResult:
        source = Path(source_path).resolve()
        output = Path(output_directory).resolve()
        if not source.is_file() or source.stat().st_size <= 0:
            raise ContractError(f"EPRO project source does not exist or is empty: {source}")
        if source.suffix.lower() != ".epro":
            raise ContractError("Offline project source render requires an .epro archive")
        if margin < 0:
            raise ContractError("Offline project source render margin cannot be negative")
        if output.exists():
            raise ContractError(f"Project render output directory already exists: {output}")

        sheets = list_v22_sheets(source)
        evidence_dir = create_evidence_directory(evidence_root, "offline-project-source-render")
        evidence_path = evidence_dir / "envelope.json"
        source_sha256 = sha256_file(source)
        report: dict[str, Any] = {
            "schemaVersion": PROJECT_SOURCE_RENDER_SCHEMA,
            "adapterVersion": PROJECT_SOURCE_RENDER_ADAPTER_VERSION,
            "capturedAt": utc_now(),
            "status": "BLOCKED",
            "renderStatus": "BLOCKED",
            "executionModel": "LOCAL_ONLY_NO_EASYEDA_CALLS",
            "easyedaApiCallCount": 0,
            "uiFreezeRisk": "NONE_FROM_RENDERER",
            "source": {
                "path": str(source),
                "sha256": source_sha256,
                "bytes": source.stat().st_size,
            },
            "outputDirectory": str(output),
            "pageCount": len(sheets),
            "pages": [],
            "error": None,
        }
        page_results: list[dict[str, Any]] = []
        try:
            output.mkdir(parents=True, exist_ok=False)
            for index, sheet in enumerate(sheets, start=1):
                png_output = output / f"{index:03d}-{sheet.document_uuid}.png"
                rendered = OfflineSourceRenderAdapter().execute(
                    SourceRenderSpec(
                        document_uuid=sheet.document_uuid,
                        margin=margin,
                        render_png=True,
                    ),
                    source,
                    evidence_dir / "pages",
                    png_output=png_output,
                    node_executable=node_executable,
                    node_path=node_path,
                    conversion_timeout=conversion_timeout,
                )
                execution = rendered.as_dict()
                page_result = {
                    **sheet.as_dict(),
                    "index": index,
                    "png": execution["png"],
                    "publishedPng": execution["publishedPng"],
                    "renderEvidencePath": execution["evidencePath"],
                    "renderExecution": execution,
                }
                page_results.append(page_result)
            report["status"] = "PASS"
            report["renderStatus"] = "STRUCTURAL_PASS"
            report["quality"] = _render_quality()
            report["pages"] = page_results
            atomic_write_json(evidence_path, report)
        except (PdfSourceError, ContractError, OSError, ValueError) as exc:
            report["pages"] = page_results
            report["error"] = str(exc)
            atomic_write_json(evidence_path, report)
            raise ContractError(
                "Offline project EPRO rendering failed; EasyEDA was not called. "
                f"Evidence: {evidence_path}. {exc}"
            ) from exc

        return ProjectSourceRenderResult(
            source_path=source,
            source_sha256=source_sha256,
            output_directory=output,
            pages=tuple(page_results),
            evidence_path=evidence_path,
        )


def _discover_node() -> Path:
    configured = os.environ.get("JLC_NODE_EXECUTABLE")
    bundled = (
        Path.home()
        / ".cache"
        / "codex-runtimes"
        / "codex-primary-runtime"
        / "dependencies"
        / "node"
        / "bin"
        / "node.exe"
    )
    candidates = [Path(configured) if configured else None, bundled, None]
    for candidate in candidates:
        if candidate is not None and candidate.is_file():
            return candidate.resolve()
        if candidate is None:
            value = shutil.which("node")
            if value:
                return Path(value).resolve()
    raise ContractError("Node is unavailable; pass --node-executable for optional PDF rendering")


def _discover_node_path() -> Path | None:
    configured = os.environ.get("JLC_NODE_PATH")
    bundled = (
        Path.home()
        / ".cache"
        / "codex-runtimes"
        / "codex-primary-runtime"
        / "dependencies"
        / "node"
        / "node_modules"
    )
    for candidate in (Path(configured) if configured else None, bundled):
        if candidate is not None and (candidate / "playwright").is_dir():
            return candidate.resolve()
    return None
