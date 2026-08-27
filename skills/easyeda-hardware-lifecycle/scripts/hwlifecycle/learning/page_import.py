"""Build JLC Hardware Learning imports from admitted native EasyEDA visual evidence."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from ..io_utils import is_sha256, load_json, sha256_file, sha256_json, utc_now


PAGE_IMPORT_SCHEMA = "learning.canvas-page-import.v1"
PROJECT_IMPORT_SCHEMA = "learning.canvas-project-import.v1"
NATIVE_VISUAL_IMPORT_SCHEMA = "learning.canvas-native-visual-import.v1"
NATIVE_PNG_BUNDLE_EXECUTION_SCHEMA = "easyeda.gateway.native-png-bundle-normalization.v1"
NATIVE_PNG_BUNDLE_EVIDENCE_SCHEMA = "easyeda.gateway.native-png-bundle-evidence.v1"
PDF_VISUAL_RENDER_EXECUTION_SCHEMA = "easyeda.gateway.native-pdf-visual-render.v1"
PDF_VISUAL_RENDER_EVIDENCE_SCHEMA = "easyeda.gateway.native-pdf-visual-evidence.v1"
PDF_VISUAL_IMPORT_SCHEMA = "learning.canvas-pdf-visual-import.v1"
NATIVE_CANVAS_DISPLAY_WIDTH = 1536
NATIVE_CANVAS_BUNDLE_MARGIN = 120
VISUAL_IMPORT_MODES = {
    "default": {"label": "Default", "easyedaTheme": "Default"},
    "black-white": {"label": "Black and white", "easyedaTheme": "Black on White"},
}
FORMAL_SOURCE_SCHEMA = "easyeda.gateway.formal-export-execution.v1"
SCHEMATIC_EXPORT_SCHEMA = "easyeda.gateway.schematic-export-execution.v1"
OFFLINE_RENDER_SCHEMA = "easyeda.gateway.offline-source-render.v1"
OFFLINE_PROJECT_RENDER_SCHEMA = "easyeda.gateway.offline-project-source-render.v1"
EPRO_VISUAL_IMPORT_DISABLED_MESSAGE = (
    "DISABLED_BY_POLICY: EPRO-derived canvas images are disabled because their visual "
    "fidelity is not acceptable; use an official EasyEDA Current Schematic PNG export instead"
)


def _identity(value: Mapping[str, Any], label: str) -> dict[str, Any]:
    nested = value.get("identity")
    source = nested if isinstance(nested, Mapping) else value
    result = {
        "projectUuid": source.get("projectUuid"),
        "documentUuid": source.get("documentUuid"),
        "documentType": source.get("documentType"),
    }
    if not isinstance(result["projectUuid"], str) or not result["projectUuid"].strip():
        raise ValueError(f"{label} is missing projectUuid")
    if not isinstance(result["documentUuid"], str) or not result["documentUuid"].strip():
        raise ValueError(f"{label} is missing documentUuid")
    document_type = result["documentType"]
    if document_type == "1":
        document_type = 1
    if document_type not in {1, "SCHEMATIC_PAGE"}:
        raise ValueError(f"{label} is not a schematic page")
    return {
        "projectUuid": result["projectUuid"].strip(),
        "documentUuid": result["documentUuid"].strip(),
        "documentType": 1,
    }


def _artifact(record: Any, label: str) -> tuple[Path, str]:
    if not isinstance(record, Mapping):
        raise ValueError(f"{label} must be an object")
    path_value = record.get("path")
    digest = record.get("sha256")
    if not isinstance(path_value, str) or not path_value.strip():
        raise ValueError(f"{label}.path is required")
    if not is_sha256(digest):
        raise ValueError(f"{label}.sha256 must be a SHA-256 digest")
    path = Path(path_value).resolve()
    if not path.is_file() or path.stat().st_size <= 0:
        raise ValueError(f"{label} does not exist or is empty: {path}")
    actual = sha256_file(path)
    if actual.lower() != str(digest).lower():
        raise ValueError(f"{label} digest mismatch")
    return path, actual


def _passing_envelope(path_value: Any, expected_schema: str, label: str) -> tuple[Path, dict[str, Any]]:
    if not isinstance(path_value, str) or not path_value.strip():
        raise ValueError(f"{label} evidencePath is required")
    path = Path(path_value).resolve()
    envelope = load_json(path)
    if envelope.get("schemaVersion") != expected_schema or envelope.get("status") != "PASS":
        raise ValueError(f"{label} evidence envelope is not PASS/{expected_schema}")
    return path, envelope


def _visual_import_mode(value: str) -> tuple[str, str]:
    mode = str(value or "").strip()
    record = VISUAL_IMPORT_MODES.get(mode)
    if record is None:
        choices = ", ".join(VISUAL_IMPORT_MODES)
        raise ValueError(f"visualMode must be one of: {choices}")
    return mode, record["easyedaTheme"]


def _require_export_theme(spec: Any, expected_theme: str, label: str) -> None:
    if not isinstance(spec, Mapping):
        raise ValueError(f"{label} spec is invalid")
    actual_theme = spec.get("theme")
    if actual_theme != expected_theme:
        raise ValueError(
            f"{label} theme {actual_theme!r} does not match the selected "
            f"visual mode theme {expected_theme!r}",
        )


class CanvasNativeVisualImportBuilder:
    """Emit a JLC Hardware Learning image import from an official native EasyEDA PNG export."""

    def build(
        self,
        *,
        project_dir: str | Path,
        canvas_page_id: str,
        identity_before: Mapping[str, Any],
        visual_execution: Mapping[str, Any],
        identity_after: Mapping[str, Any],
        visual_mode: str,
    ) -> dict[str, Any]:
        root = Path(project_dir).resolve()
        page_id = canvas_page_id.strip()
        if not page_id.startswith("page:") or len(page_id) <= len("page:"):
            raise ValueError("canvasPageId must use the page:<id> form")

        before = _identity(identity_before, "identityBefore")
        after = _identity(identity_after, "identityAfter")
        if before != after:
            raise ValueError("EasyEDA identity changed between native visual export and canvas import")
        mode, export_theme = _visual_import_mode(visual_mode)
        spec = visual_execution.get("spec")
        _require_export_theme(spec, export_theme, "native visual execution")

        if visual_execution.get("schemaVersion") == NATIVE_PNG_BUNDLE_EXECUTION_SCHEMA:
            return self._build_bundle(
                root=root,
                page_id=page_id,
                before=before,
                visual_execution=visual_execution,
                visual_mode=mode,
                export_theme=export_theme,
            )

        if visual_execution.get("schemaVersion") != SCHEMATIC_EXPORT_SCHEMA:
            raise ValueError("native visual execution schema is invalid")
        if visual_execution.get("success") is False:
            raise ValueError("native visual execution did not succeed")
        if _identity(visual_execution, "visualExecution.identity") != before:
            raise ValueError("native visual export identity does not match the guarded schematic")
        if spec.get("fileType") != "PNG":
            raise ValueError(
                "JLC Hardware Learning image import requires an official EasyEDA PNG; retain PDF for review/archive",
            )
        if spec.get("scope") != "current-schematic":
            raise ValueError("native visual import requires the verified current-schematic scope")

        artifact_path, artifact_sha256 = _artifact(
            visual_execution.get("artifact"), "native visual artifact"
        )
        if artifact_path.suffix.lower() != ".png":
            raise ValueError("native visual artifact must be PNG")
        artifact = visual_execution.get("artifact")
        if (
            isinstance(artifact, Mapping)
            and artifact.get("mediaType") == "application/zip"
            and artifact.get("containerFormat") == "easyeda.official-native-png-bundle.v1"
        ):
            return self._build_export_bundle(
                root=root,
                page_id=page_id,
                before=before,
                visual_execution=visual_execution,
                source_path=artifact_path,
                source_sha256=artifact_sha256,
                visual_mode=mode,
                export_theme=export_theme,
            )
        if (
            not isinstance(artifact, Mapping)
            or artifact.get("mediaType") != "image/png"
            or not isinstance(artifact.get("width"), int)
            or artifact.get("width", 0) <= 0
            or not isinstance(artifact.get("height"), int)
            or artifact.get("height", 0) <= 0
        ):
            raise ValueError("native visual artifact has no verified PNG dimensions")

        evidence_path, evidence = _passing_envelope(
            visual_execution.get("evidencePath"),
            "easyeda.gateway.schematic-export-evidence.v1",
            "native visual export",
        )
        if _identity(evidence, "nativeVisualEnvelope.identity") != before:
            raise ValueError("native visual evidence identity does not match the guarded schematic")
        _require_export_theme(evidence.get("spec"), export_theme, "native visual evidence")
        safety = evidence.get("safety")
        if (
            not isinstance(safety, Mapping)
            or safety.get("capabilityId") != "visual.current-schematic.png"
        ):
            raise ValueError("native visual evidence did not use the admitted official PNG capability")

        image_path = artifact_path
        published = evidence.get("publishedOutput")
        execution_published = visual_execution.get("publishedOutput")
        if published is not None:
            published_path, published_sha256 = _artifact(
                published, "published native visual artifact"
            )
            if published_sha256 != artifact_sha256:
                raise ValueError("published native visual artifact digest differs from evidence PNG")
            if (
                not isinstance(execution_published, str)
                or Path(execution_published).resolve() != published_path
            ):
                raise ValueError("native visual execution and evidence disagree on published output")
            image_path = published_path
        elif execution_published is not None:
            raise ValueError("native visual execution reports an unverified published output")

        captured_at = utc_now()
        warning = (
            "The artifact is the official current-schematic PNG and must not be relabeled "
            "as an exact current-page export."
        )
        asset_meta = {
            "schemaVersion": NATIVE_VISUAL_IMPORT_SCHEMA,
            "evidenceSource": "official-easyeda-export",
            "visualSource": "native-easyeda-png",
            "scope": "current-schematic-native-png",
            "projectUuid": before["projectUuid"],
            "documentUuid": before["documentUuid"],
            "documentType": before["documentType"],
            "visualPath": str(image_path),
            "visualSha256": artifact_sha256,
            "visualEvidencePath": str(evidence_path),
            "capturedAt": captured_at,
            "visualMode": mode,
            "easyedaExportTheme": export_theme,
        }
        manifest: dict[str, Any] = {
            "schemaVersion": NATIVE_VISUAL_IMPORT_SCHEMA,
            "status": "READY",
            "reviewRequired": True,
            "warnings": [warning],
            "createdAt": captured_at,
            "projectDir": str(root),
            "canvasPageId": page_id,
            "easyedaIdentity": before,
            "visualMode": mode,
            "easyedaExportTheme": export_theme,
            "visual": {
                "format": "PNG",
                "scope": "current-schematic",
                "path": str(image_path),
                "sha256": artifact_sha256,
                "evidencePath": str(evidence_path),
                "width": artifact["width"],
                "height": artifact["height"],
                "displayWidth": NATIVE_CANVAS_DISPLAY_WIDTH,
                "visualMode": mode,
                "easyedaExportTheme": export_theme,
            },
            "tool": "mcp__jlc_hardware_learning_mcp__insert_hardware_learning_image",
            "toolArgs": {
                "projectDir": str(root),
                "pageId": page_id,
                "imagePath": str(image_path),
                "displayWidth": NATIVE_CANVAS_DISPLAY_WIDTH,
                "replaceAiImageHolder": False,
                "evidenceSource": "official-easyeda-export",
                "altText": f"EasyEDA native current-schematic PNG ({before['documentUuid']})",
                "assetMeta": asset_meta,
                "shapeMeta": {
                    "hardwareLearningEvidence": True,
                    "easyedaDocumentUuid": before["documentUuid"],
                    "evidenceSha256": artifact_sha256,
                    "visualSource": "native-easyeda-png",
                    "visualMode": mode,
                    "easyedaExportTheme": export_theme,
                },
            },
        }
        manifest["manifestSha256"] = sha256_json(manifest)
        return manifest

    def _build_export_bundle(
        self,
        *,
        root: Path,
        page_id: str,
        before: Mapping[str, Any],
        visual_execution: Mapping[str, Any],
        source_path: Path,
        source_sha256: str,
        visual_mode: str,
        export_theme: str,
    ) -> dict[str, Any]:
        artifact = visual_execution.get("artifact")
        if not isinstance(artifact, Mapping):
            raise ValueError("official native PNG bundle artifact is invalid")
        pages = artifact.get("pages")
        if (
            not isinstance(pages, list)
            or not pages
            or artifact.get("pageCount") != len(pages)
        ):
            raise ValueError("official native PNG bundle page inventory is invalid")

        evidence_path, evidence = _passing_envelope(
            visual_execution.get("evidencePath"),
            "easyeda.gateway.schematic-export-evidence.v1",
            "native visual export",
        )
        if _identity(evidence, "nativeVisualEnvelope.identity") != dict(before):
            raise ValueError("native visual evidence identity does not match the guarded schematic")
        _require_export_theme(evidence.get("spec"), export_theme, "native visual evidence")
        safety = evidence.get("safety")
        if (
            not isinstance(safety, Mapping)
            or safety.get("capabilityId") != "visual.current-schematic.png"
            or safety.get("automaticRetry") is not False
        ):
            raise ValueError("native visual bundle evidence did not use one admitted official PNG call")
        if visual_execution.get("publishedOutput") is not None or evidence.get("publishedOutput") is not None:
            raise ValueError("official native PNG bundle import requires the immutable evidence artifact")

        sealed_files = evidence.get("files")
        if not isinstance(sealed_files, Mapping) or source_path.parent != evidence_path.parent:
            raise ValueError("official native PNG bundle is not colocated with its evidence envelope")
        source_relative = source_path.relative_to(evidence_path.parent).as_posix()
        if sealed_files.get(source_relative) != source_sha256:
            raise ValueError("official native PNG bundle source is not sealed by export evidence")
        for index, page in enumerate(pages, start=1):
            if not isinstance(page, Mapping):
                raise ValueError(f"official native PNG bundle page {index} is invalid")
            page_path, page_sha256 = _artifact(page, f"official native PNG bundle page {index}")
            if page_path.parent.parent != evidence_path.parent:
                raise ValueError(f"official native PNG bundle page {index} is outside its evidence directory")
            page_relative = page_path.relative_to(evidence_path.parent).as_posix()
            if sealed_files.get(page_relative) != page_sha256:
                raise ValueError(f"official native PNG bundle page {index} is not sealed by export evidence")

        return self._build_bundle_manifest(
            root=root,
            page_id=page_id,
            before=before,
            source_path=source_path,
            source_sha256=source_sha256,
            pages=pages,
            sealed_pages=pages,
            evidence_path=evidence_path,
            visual_mode=visual_mode,
            export_theme=export_theme,
        )

    def _build_bundle(
        self,
        *,
        root: Path,
        page_id: str,
        before: Mapping[str, Any],
        visual_execution: Mapping[str, Any],
        visual_mode: str,
        export_theme: str,
    ) -> dict[str, Any]:
        if visual_execution.get("success") is False:
            raise ValueError("native PNG bundle normalization did not succeed")
        if visual_execution.get("easyedaApiCallCount") != 0:
            raise ValueError("native PNG bundle normalization must be local-only")
        if _identity(visual_execution, "visualExecution.identity") != dict(before):
            raise ValueError("native PNG bundle identity does not match the guarded schematic")
        spec = visual_execution.get("spec")
        if (
            not isinstance(spec, Mapping)
            or spec.get("fileType") != "PNG"
            or spec.get("scope") != "current-schematic"
        ):
            raise ValueError("native PNG bundle did not originate from current-schematic PNG export")
        source_path, source_sha256 = _artifact(
            visual_execution.get("sourceArtifact"), "native PNG bundle source"
        )
        source_artifact = visual_execution.get("sourceArtifact")
        if (
            not isinstance(source_artifact, Mapping)
            or source_artifact.get("mediaType") != "application/zip"
            or source_artifact.get("containerFormat") != "easyeda.official-native-png-bundle.v1"
        ):
            raise ValueError("native PNG bundle source container is invalid")
        evidence_path, evidence = _passing_envelope(
            visual_execution.get("evidencePath"),
            NATIVE_PNG_BUNDLE_EVIDENCE_SCHEMA,
            "native PNG bundle normalization",
        )
        if _identity(evidence, "nativePngBundleEnvelope.identity") != dict(before):
            raise ValueError("native PNG bundle evidence identity differs from the guarded schematic")
        _require_export_theme(evidence.get("spec"), export_theme, "native PNG bundle evidence")
        safety = evidence.get("safety")
        if (
            evidence.get("easyedaApiCallCount") != 0
            or not isinstance(safety, Mapping)
            or safety.get("capabilityId") != "visual.current-schematic.png"
            or safety.get("officialCallRepeated") is not False
        ):
            raise ValueError("native PNG bundle evidence is not local-only normalization of one official call")
        sealed_source = evidence.get("sourceArtifact")
        if (
            not isinstance(sealed_source, Mapping)
            or Path(str(sealed_source.get("path"))).resolve() != source_path
            or sealed_source.get("sha256") != source_sha256
        ):
            raise ValueError("native PNG bundle source is not sealed by normalization evidence")

        pages = visual_execution.get("pages")
        evidence_pages = evidence.get("pages")
        if (
            not isinstance(pages, list)
            or not pages
            or not isinstance(evidence_pages, list)
            or len(pages) != len(evidence_pages)
            or visual_execution.get("pageCount") != len(pages)
            or evidence.get("pageCount") != len(pages)
        ):
            raise ValueError("native PNG bundle page inventory is invalid")

        return self._build_bundle_manifest(
            root=root,
            page_id=page_id,
            before=before,
            source_path=source_path,
            source_sha256=source_sha256,
            pages=pages,
            sealed_pages=evidence_pages,
            evidence_path=evidence_path,
            visual_mode=visual_mode,
            export_theme=export_theme,
        )

    def _build_bundle_manifest(
        self,
        *,
        root: Path,
        page_id: str,
        before: Mapping[str, Any],
        source_path: Path,
        source_sha256: str,
        pages: list[Any],
        sealed_pages: list[Any],
        evidence_path: Path,
        visual_mode: str,
        export_theme: str,
    ) -> dict[str, Any]:

        captured_at = utc_now()
        operations: list[dict[str, Any]] = []
        for index, (page, sealed_page) in enumerate(zip(pages, sealed_pages), start=1):
            if not isinstance(page, Mapping) or not isinstance(sealed_page, Mapping):
                raise ValueError(f"native PNG bundle page {index} is invalid")
            page_path, page_sha256 = _artifact(page, f"native PNG bundle page {index}")
            if (
                page_path.suffix.lower() != ".png"
                or page.get("mediaType") != "image/png"
                or not isinstance(page.get("width"), int)
                or page.get("width", 0) <= 0
                or not isinstance(page.get("height"), int)
                or page.get("height", 0) <= 0
            ):
                raise ValueError(f"native PNG bundle page {index} has invalid PNG metadata")
            entry_name = page.get("entryName")
            if (
                page.get("index") != index
                or not isinstance(entry_name, str)
                or sealed_page.get("index") != index
                or sealed_page.get("entryName") != entry_name
                or Path(str(sealed_page.get("path"))).resolve() != page_path
                or sealed_page.get("sha256") != page_sha256
            ):
                raise ValueError(f"native PNG bundle page {index} differs from sealed evidence")
            asset_meta = {
                "schemaVersion": NATIVE_VISUAL_IMPORT_SCHEMA,
                "evidenceSource": "official-easyeda-export",
                "visualSource": "native-easyeda-png",
                "scope": "current-schematic-native-png-entry",
                "projectUuid": before["projectUuid"],
                "documentUuid": before["documentUuid"],
                "documentType": before["documentType"],
                "nativeBundlePath": str(source_path),
                "nativeBundleSha256": source_sha256,
                "nativeBundleEntryName": entry_name,
                "nativeBundlePageIndex": index,
                "nativeBundlePageCount": len(pages),
                "visualPath": str(page_path),
                "visualSha256": page_sha256,
                "visualEvidencePath": str(evidence_path),
                "capturedAt": captured_at,
                "visualMode": visual_mode,
                "easyedaExportTheme": export_theme,
            }
            operations.append({
                "index": index,
                "entryName": entry_name,
                "tool": "mcp__jlc_hardware_learning_mcp__insert_hardware_learning_image",
                "toolArgs": {
                    "projectDir": str(root),
                    "pageId": page_id,
                    "imagePath": str(page_path),
                    "displayWidth": NATIVE_CANVAS_DISPLAY_WIDTH,
                    "replaceAiImageHolder": False,
                    "evidenceSource": "official-easyeda-export",
                    "altText": f"EasyEDA official native current-schematic PNG {index}/{len(pages)} ({entry_name})",
                    "placement": "right",
                    "margin": NATIVE_CANVAS_BUNDLE_MARGIN,
                    "matchAnchor": False,
                    "assetMeta": asset_meta,
                    "shapeMeta": {
                        "hardwareLearningEvidence": True,
                        "easyedaDocumentUuid": before["documentUuid"],
                        "evidenceSha256": page_sha256,
                        "visualSource": "native-easyeda-png",
                        "nativeBundlePageIndex": index,
                        "visualMode": visual_mode,
                        "easyedaExportTheme": export_theme,
                    },
                },
            })

        warning = (
            "These are official native pages from one current-schematic PNG bundle; "
            "individual entries must not be relabeled as exact EasyEDA document UUID exports."
        )
        manifest: dict[str, Any] = {
            "schemaVersion": NATIVE_VISUAL_IMPORT_SCHEMA,
            "status": "READY",
            "reviewRequired": True,
            "warnings": [warning],
            "createdAt": captured_at,
            "projectDir": str(root),
            "canvasPageId": page_id,
            "easyedaIdentity": dict(before),
            "visualMode": visual_mode,
            "easyedaExportTheme": export_theme,
            "visual": {
                "format": "PNG_BUNDLE",
                "scope": "current-schematic",
                "containerPath": str(source_path),
                "containerSha256": source_sha256,
                "pageCount": len(operations),
                "evidencePath": str(evidence_path),
                "displayWidth": NATIVE_CANVAS_DISPLAY_WIDTH,
                "visualMode": visual_mode,
                "easyedaExportTheme": export_theme,
            },
            "operations": operations,
        }
        manifest["manifestSha256"] = sha256_json(manifest)
        return manifest


class CanvasPdfVisualImportBuilder:
    """Emit JLC Hardware Learning operations from locally rendered official EasyEDA PDF evidence."""

    def build(
        self,
        *,
        project_dir: str | Path,
        canvas_page_id: str,
        identity_before: Mapping[str, Any],
        render_execution: Mapping[str, Any],
        identity_after: Mapping[str, Any],
        visual_mode: str,
    ) -> dict[str, Any]:
        root = Path(project_dir).resolve()
        page_id = canvas_page_id.strip()
        if not page_id.startswith("page:") or len(page_id) <= len("page:"):
            raise ValueError("canvasPageId must use the page:<id> form")

        before = _identity(identity_before, "identityBefore")
        after = _identity(identity_after, "identityAfter")
        if before != after:
            raise ValueError("EasyEDA identity changed between official PDF export and canvas import")
        mode, export_theme = _visual_import_mode(visual_mode)
        if render_execution.get("schemaVersion") != PDF_VISUAL_RENDER_EXECUTION_SCHEMA:
            raise ValueError("official PDF visual render execution schema is invalid")
        if render_execution.get("success") is False:
            raise ValueError("official PDF visual render did not succeed")
        if render_execution.get("easyedaApiCallCount") != 0:
            raise ValueError("official PDF visual render must be local-only")
        if render_execution.get("automaticRetry") is not False:
            raise ValueError("official PDF visual render must not retry automatically")
        if _identity(render_execution, "pdfRenderExecution.identity") != before:
            raise ValueError("official PDF visual render identity differs from the guarded schematic")
        spec = render_execution.get("spec")
        _require_export_theme(spec, export_theme, "official PDF visual render execution")
        if (
            not isinstance(spec, Mapping)
            or spec.get("fileType") != "PDF"
            or spec.get("scope") != "current-schematic"
        ):
            raise ValueError("canvas PDF visual import requires an official current-schematic PDF")

        source_pdf, source_pdf_sha256 = _artifact(
            render_execution.get("sourceArtifact"), "official source PDF"
        )
        source_record = render_execution.get("sourceArtifact")
        if (
            source_pdf.suffix.lower() != ".pdf"
            or not isinstance(source_record, Mapping)
            or source_record.get("mediaType") != "application/pdf"
        ):
            raise ValueError("official source artifact is not a validated PDF")

        evidence_path, evidence = _passing_envelope(
            render_execution.get("evidencePath"),
            PDF_VISUAL_RENDER_EVIDENCE_SCHEMA,
            "official PDF visual render",
        )
        if _identity(evidence, "pdfRenderEnvelope.identity") != before:
            raise ValueError("official PDF visual evidence differs from the guarded schematic")
        _require_export_theme(evidence.get("sourceSpec"), export_theme, "official PDF visual evidence")
        safety = evidence.get("safety")
        if (
            evidence.get("easyedaApiCallCount") != 0
            or not isinstance(safety, Mapping)
            or safety.get("sourceCapabilityId") != "visual.current-schematic.pdf"
            or safety.get("officialCallRepeated") is not False
            or safety.get("automaticRetry") is not False
        ):
            raise ValueError("official PDF visual evidence is not a local derivation of one admitted call")
        sealed_source = evidence.get("sourceArtifact")
        if (
            not isinstance(sealed_source, Mapping)
            or Path(str(sealed_source.get("path"))).resolve() != source_pdf
            or sealed_source.get("sha256") != source_pdf_sha256
        ):
            raise ValueError("official source PDF differs from rendered evidence")

        official_evidence_path, official_evidence = _passing_envelope(
            evidence.get("sourceOfficialEvidencePath"),
            "easyeda.gateway.schematic-export-evidence.v1",
            "official PDF export",
        )
        if _identity(official_evidence, "officialPdfEnvelope.identity") != before:
            raise ValueError("official PDF export evidence identity differs from the guarded schematic")
        _require_export_theme(official_evidence.get("spec"), export_theme, "official PDF export evidence")
        official_safety = official_evidence.get("safety")
        if (
            not isinstance(official_safety, Mapping)
            or official_safety.get("capabilityId") != "visual.current-schematic.pdf"
            or official_safety.get("automaticRetry") is not False
        ):
            raise ValueError("official PDF source did not use the admitted serial capability")
        official_files = official_evidence.get("files")
        if source_pdf.parent != official_evidence_path.parent:
            raise ValueError("official source PDF is outside its export evidence directory")
        official_relative = source_pdf.relative_to(official_evidence_path.parent).as_posix()
        if not isinstance(official_files, Mapping) or official_files.get(official_relative) != source_pdf_sha256:
            raise ValueError("official source PDF is not sealed by its export evidence")

        pages = render_execution.get("pages")
        evidence_pages = evidence.get("pages")
        if (
            not isinstance(pages, list)
            or not pages
            or not isinstance(evidence_pages, list)
            or len(pages) != len(evidence_pages)
            or render_execution.get("pageCount") != len(pages)
            or evidence.get("pageCount") != len(pages)
        ):
            raise ValueError("official PDF rendered page inventory is invalid")
        if render_execution.get("renderSettings") != evidence.get("renderSettings"):
            raise ValueError("official PDF render settings differ from sealed evidence")
        if render_execution.get("renderer") != evidence.get("renderer"):
            raise ValueError("official PDF renderer identity differs from sealed evidence")

        sealed_files = evidence.get("files")
        if not isinstance(sealed_files, Mapping):
            raise ValueError("official PDF visual evidence has no sealed file inventory")
        captured_at = utc_now()
        operations: list[dict[str, Any]] = []
        for index, (page, sealed_page) in enumerate(zip(pages, evidence_pages), start=1):
            if not isinstance(page, Mapping) or not isinstance(sealed_page, Mapping):
                raise ValueError(f"official PDF rendered page {index} is invalid")
            page_path, page_sha256 = _artifact(page, f"official PDF rendered page {index}")
            if (
                page_path.suffix.lower() != ".png"
                or page.get("mediaType") != "image/png"
                or page.get("index") != index
                or page.get("pdfPageIndex") != index
                or not isinstance(page.get("width"), int)
                or page.get("width", 0) <= 0
                or not isinstance(page.get("height"), int)
                or page.get("height", 0) <= 0
            ):
                raise ValueError(f"official PDF rendered page {index} has invalid PNG metadata")
            if page_path.parent.parent != evidence_path.parent:
                raise ValueError(f"official PDF rendered page {index} is outside its evidence directory")
            page_relative = page_path.relative_to(evidence_path.parent).as_posix()
            if sealed_files.get(page_relative) != page_sha256:
                raise ValueError(f"official PDF rendered page {index} is not sealed by evidence")
            if (
                sealed_page.get("index") != index
                or sealed_page.get("pdfPageIndex") != index
                or Path(str(sealed_page.get("path"))).resolve() != page_path
                or sealed_page.get("sha256") != page_sha256
                or sealed_page.get("width") != page.get("width")
                or sealed_page.get("height") != page.get("height")
            ):
                raise ValueError(f"official PDF rendered page {index} differs from sealed evidence")

            asset_meta = {
                "schemaVersion": PDF_VISUAL_IMPORT_SCHEMA,
                "evidenceSource": "official-easyeda-pdf-render",
                "visualSource": "native-easyeda-pdf-rendered-png",
                "scope": "current-schematic-pdf-render-page",
                "projectUuid": before["projectUuid"],
                "documentUuid": before["documentUuid"],
                "documentType": before["documentType"],
                "sourcePdfPath": str(source_pdf),
                "sourcePdfSha256": source_pdf_sha256,
                "sourcePdfEvidencePath": str(official_evidence_path),
                "pdfPageIndex": index,
                "pdfPageCount": len(pages),
                "visualPath": str(page_path),
                "visualSha256": page_sha256,
                "visualEvidencePath": str(evidence_path),
                "renderSettings": render_execution.get("renderSettings"),
                "renderer": render_execution.get("renderer"),
                "capturedAt": captured_at,
                "visualMode": mode,
                "easyedaExportTheme": export_theme,
            }
            operations.append({
                "index": index,
                "entryName": page.get("entryName"),
                "tool": "mcp__jlc_hardware_learning_mcp__insert_hardware_learning_image",
                "toolArgs": {
                    "projectDir": str(root),
                    "pageId": page_id,
                    "imagePath": str(page_path),
                    "displayWidth": NATIVE_CANVAS_DISPLAY_WIDTH,
                    "replaceAiImageHolder": False,
                    "evidenceSource": "official-easyeda-pdf-render",
                    "altText": f"EasyEDA official current-schematic PDF render {index}/{len(pages)}",
                    "placement": "right",
                    "margin": NATIVE_CANVAS_BUNDLE_MARGIN,
                    "matchAnchor": False,
                    "assetMeta": asset_meta,
                    "shapeMeta": {
                        "hardwareLearningEvidence": True,
                        "easyedaDocumentUuid": before["documentUuid"],
                        "evidenceSha256": page_sha256,
                        "visualSource": "native-easyeda-pdf-rendered-png",
                        "sourcePdfSha256": source_pdf_sha256,
                        "pdfPageIndex": index,
                        "visualMode": mode,
                        "easyedaExportTheme": export_theme,
                    },
                },
            })

        warning = (
            "These PNG pages are local high-resolution renders of one official current-schematic PDF; "
            "they are not EPRO-derived and must not be relabeled as exact EasyEDA page UUID exports."
        )
        manifest: dict[str, Any] = {
            "schemaVersion": PDF_VISUAL_IMPORT_SCHEMA,
            "status": "READY",
            "reviewRequired": True,
            "warnings": [warning],
            "createdAt": captured_at,
            "projectDir": str(root),
            "canvasPageId": page_id,
            "easyedaIdentity": before,
            "visualMode": mode,
            "easyedaExportTheme": export_theme,
            "visual": {
                "format": "PDF_RENDERED_PNG_PAGES",
                "sourceFormat": "PDF",
                "scope": "current-schematic",
                "sourcePath": str(source_pdf),
                "sourceSha256": source_pdf_sha256,
                "pageCount": len(operations),
                "evidencePath": str(evidence_path),
                "displayWidth": NATIVE_CANVAS_DISPLAY_WIDTH,
                "renderSettings": render_execution.get("renderSettings"),
                "visualMode": mode,
                "easyedaExportTheme": export_theme,
            },
            "operations": operations,
        }
        manifest["manifestSha256"] = sha256_json(manifest)
        return manifest


class CanvasPageImportBuilder:
    """Validate a stable EasyEDA page and emit exact JLC Hardware Learning image tool arguments."""

    def build(
        self,
        *,
        project_dir: str | Path,
        canvas_page_id: str,
        identity_before: Mapping[str, Any],
        source_execution: Mapping[str, Any],
        render_execution: Mapping[str, Any],
        identity_after: Mapping[str, Any],
    ) -> dict[str, Any]:
        raise ValueError(EPRO_VISUAL_IMPORT_DISABLED_MESSAGE)
        root = Path(project_dir).resolve()
        page_id = canvas_page_id.strip()
        if not page_id.startswith("page:") or len(page_id) <= len("page:"):
            raise ValueError("canvasPageId must use the page:<id> form")

        before = _identity(identity_before, "identityBefore")
        after = _identity(identity_after, "identityAfter")
        if before != after:
            raise ValueError("EasyEDA identity changed between source export and canvas import")

        if source_execution.get("schemaVersion") != FORMAL_SOURCE_SCHEMA:
            raise ValueError("source execution schema is invalid")
        if source_execution.get("success") is False:
            raise ValueError("source execution did not succeed")
        if _identity(source_execution, "sourceExecution.identity") != before:
            raise ValueError("source export identity does not match the guarded page")
        spec = source_execution.get("spec")
        if not isinstance(spec, Mapping) or spec.get("kind") != "source" or spec.get("variant") != "epro":
            raise ValueError("page import requires a source/epro formal export")
        source_path, source_sha256 = _artifact(source_execution.get("artifact"), "source artifact")
        if source_path.suffix.lower() != ".epro":
            raise ValueError("page import source artifact must be .epro")
        source_evidence_path, source_envelope = _passing_envelope(
            source_execution.get("evidencePath"),
            "easyeda.gateway.formal-export-evidence.v1",
            "source export",
        )
        preservation = source_envelope.get("sourcePreservation")
        if not isinstance(preservation, Mapping) or preservation.get("sourceUnchanged") is not True:
            raise ValueError("source export did not prove source preservation")
        if _identity(source_envelope, "sourceEnvelope.identity") != before:
            raise ValueError("source evidence identity does not match the guarded page")
        allowed_source_paths = {source_path}
        published_output = source_envelope.get("publishedOutput")
        if published_output is not None:
            published_path, published_sha256 = _artifact(
                published_output, "published source artifact"
            )
            if published_sha256 != source_sha256:
                raise ValueError("published source artifact digest differs from guarded EPRO")
            execution_published = source_execution.get("publishedOutput")
            if not isinstance(execution_published, str) or Path(execution_published).resolve() != published_path:
                raise ValueError("source execution and envelope disagree on published output")
            allowed_source_paths.add(published_path)

        if render_execution.get("schemaVersion") != OFFLINE_RENDER_SCHEMA:
            raise ValueError("render execution schema is invalid")
        if render_execution.get("success") is False:
            raise ValueError("render execution did not succeed")
        if render_execution.get("executionModel") != "LOCAL_ONLY_NO_EASYEDA_CALLS":
            raise ValueError("page PNG was not rendered by the local-only renderer")
        rendered_source_path, rendered_source_sha256 = _artifact(
            render_execution.get("source"), "render source"
        )
        if rendered_source_path not in allowed_source_paths or rendered_source_sha256 != source_sha256:
            raise ValueError("render source is not the guarded EPRO artifact or its verified published copy")
        png_path, png_sha256 = _artifact(render_execution.get("png"), "render PNG")
        if png_path.suffix.lower() != ".png":
            raise ValueError("canvas import artifact must be PNG")
        render_evidence_path, render_envelope = _passing_envelope(
            render_execution.get("evidencePath"),
            OFFLINE_RENDER_SCHEMA,
            "offline render",
        )
        if render_envelope.get("easyedaApiCallCount") != 0:
            raise ValueError("offline renderer evidence reports an EasyEDA API call")
        render_spec = render_envelope.get("spec")
        if not isinstance(render_spec, Mapping) or render_spec.get("documentUuid") != before["documentUuid"]:
            raise ValueError("offline render selected a different EasyEDA page UUID")
        if render_spec.get("renderPng") is not True:
            raise ValueError("offline render evidence does not include PNG rendering")
        render_quality_value = render_envelope.get("quality")
        if isinstance(render_quality_value, Mapping):
            render_quality = dict(render_quality_value)
        else:
            render_quality = {
                "structuralStatus": "PASS",
                "visualStatus": "LEGACY_UNSPECIFIED",
                "visualReviewRequired": True,
                "limitations": [
                    "Legacy renderer evidence did not declare a visual-fidelity contract."
                ],
            }
        if render_quality.get("structuralStatus") != "PASS":
            raise ValueError("offline render did not pass structural artifact generation")
        visual_review_required = render_quality.get("visualReviewRequired") is not False

        captured_at = utc_now()
        asset_meta = {
            "schemaVersion": PAGE_IMPORT_SCHEMA,
            "evidenceSource": "official-easyeda-export",
            "scope": "current-page-from-epro",
            "projectUuid": before["projectUuid"],
            "documentUuid": before["documentUuid"],
            "documentType": before["documentType"],
            "sourcePath": str(source_path),
            "sourceSha256": source_sha256,
            "sourceEvidencePath": str(source_evidence_path),
            "renderPath": str(png_path),
            "renderSha256": png_sha256,
            "renderEvidencePath": str(render_evidence_path),
            "renderQuality": render_quality,
            "capturedAt": captured_at,
        }
        manifest: dict[str, Any] = {
            "schemaVersion": PAGE_IMPORT_SCHEMA,
            "status": "READY",
            "reviewRequired": visual_review_required,
            "warnings": list(render_quality.get("limitations") or []),
            "createdAt": captured_at,
            "projectDir": str(root),
            "canvasPageId": page_id,
            "easyedaIdentity": before,
            "source": {
                "path": str(source_path),
                "sha256": source_sha256,
                "evidencePath": str(source_evidence_path),
            },
            "render": {
                "path": str(png_path),
                "sha256": png_sha256,
                "evidencePath": str(render_evidence_path),
                "quality": render_quality,
            },
            "tool": "mcp__jlc_hardware_learning_mcp__insert_hardware_learning_image",
            "toolArgs": {
                "projectDir": str(root),
                "pageId": page_id,
                "imagePath": str(png_path),
                "replaceAiImageHolder": False,
                "evidenceSource": "official-easyeda-export",
                "altText": f"EasyEDA schematic page {before['documentUuid']}",
                "assetMeta": asset_meta,
                "shapeMeta": {
                    "hardwareLearningEvidence": True,
                    "easyedaDocumentUuid": before["documentUuid"],
                    "evidenceSha256": png_sha256,
                },
            },
        }
        manifest["manifestSha256"] = sha256_json(manifest)
        return manifest


class CanvasProjectImportBuilder:
    """Validate one guarded project EPRO and emit ordered JLC Hardware Learning page imports."""

    def build(
        self,
        *,
        project_dir: str | Path,
        canvas_page_id: str,
        identity_before: Mapping[str, Any],
        source_execution: Mapping[str, Any],
        render_execution: Mapping[str, Any],
        identity_after: Mapping[str, Any],
    ) -> dict[str, Any]:
        raise ValueError(EPRO_VISUAL_IMPORT_DISABLED_MESSAGE)
        root = Path(project_dir).resolve()
        page_id = canvas_page_id.strip()
        if not page_id.startswith("page:") or len(page_id) <= len("page:"):
            raise ValueError("canvasPageId must use the page:<id> form")

        before = _identity(identity_before, "identityBefore")
        after = _identity(identity_after, "identityAfter")
        if before != after:
            raise ValueError("EasyEDA identity changed between project export and canvas import")

        if source_execution.get("schemaVersion") != FORMAL_SOURCE_SCHEMA:
            raise ValueError("project source execution schema is invalid")
        if source_execution.get("success") is False:
            raise ValueError("project source execution did not succeed")
        if _identity(source_execution, "sourceExecution.identity") != before:
            raise ValueError("project source export identity does not match the guarded page")
        spec = source_execution.get("spec")
        if (
            not isinstance(spec, Mapping)
            or spec.get("kind") != "project-source"
            or spec.get("variant") != "epro"
        ):
            raise ValueError("project import requires a project-source/epro formal export")
        source_path, source_sha256 = _artifact(
            source_execution.get("artifact"), "project source artifact"
        )
        if source_path.suffix.lower() != ".epro":
            raise ValueError("project import source artifact must be .epro")
        source_artifact = source_execution.get("artifact")
        source_sheets = source_artifact.get("sheets") if isinstance(source_artifact, Mapping) else None
        if not isinstance(source_sheets, list) or not source_sheets:
            raise ValueError("project source execution has no verified schematic page inventory")
        source_page_uuids = [
            item.get("documentUuid") if isinstance(item, Mapping) else None
            for item in source_sheets
        ]
        if any(not isinstance(item, str) or not item for item in source_page_uuids):
            raise ValueError("project source page inventory contains an invalid UUID")
        if len(set(source_page_uuids)) != len(source_page_uuids):
            raise ValueError("project source page inventory contains duplicate UUIDs")

        source_evidence_path, source_envelope = _passing_envelope(
            source_execution.get("evidencePath"),
            "easyeda.gateway.formal-export-evidence.v1",
            "project source export",
        )
        preservation = source_envelope.get("projectTreePreservation")
        if (
            not isinstance(preservation, Mapping)
            or preservation.get("treeUnchanged") is not True
            or preservation.get("pageUuidSetMatch") is not True
        ):
            raise ValueError("project source export did not prove schematic tree preservation")
        if _identity(source_envelope, "sourceEnvelope.identity") != before:
            raise ValueError("project source evidence identity does not match the guarded page")
        allowed_source_paths = {source_path}
        published_output = source_envelope.get("publishedOutput")
        if published_output is not None:
            published_path, published_sha256 = _artifact(
                published_output, "published project source artifact"
            )
            if published_sha256 != source_sha256:
                raise ValueError("published project source digest differs from guarded EPRO")
            execution_published = source_execution.get("publishedOutput")
            if (
                not isinstance(execution_published, str)
                or Path(execution_published).resolve() != published_path
            ):
                raise ValueError("project source execution and envelope disagree on published output")
            allowed_source_paths.add(published_path)

        if render_execution.get("schemaVersion") != OFFLINE_PROJECT_RENDER_SCHEMA:
            raise ValueError("project render execution schema is invalid")
        if render_execution.get("success") is False:
            raise ValueError("project render execution did not succeed")
        if render_execution.get("executionModel") != "LOCAL_ONLY_NO_EASYEDA_CALLS":
            raise ValueError("project pages were not rendered by the local-only renderer")
        if render_execution.get("easyedaApiCallCount") != 0:
            raise ValueError("project renderer execution reports an EasyEDA API call")
        rendered_source_path, rendered_source_sha256 = _artifact(
            render_execution.get("source"), "project render source"
        )
        if rendered_source_path not in allowed_source_paths or rendered_source_sha256 != source_sha256:
            raise ValueError("project render source is not the guarded EPRO artifact")
        batch_evidence_path, batch_envelope = _passing_envelope(
            render_execution.get("evidencePath"),
            OFFLINE_PROJECT_RENDER_SCHEMA,
            "offline project render",
        )
        if batch_envelope.get("easyedaApiCallCount") != 0:
            raise ValueError("offline project render evidence reports an EasyEDA API call")
        batch_quality_value = batch_envelope.get("quality")
        if isinstance(batch_quality_value, Mapping):
            batch_quality = dict(batch_quality_value)
        else:
            batch_quality = {
                "structuralStatus": "PASS",
                "visualStatus": "LEGACY_UNSPECIFIED",
                "visualReviewRequired": True,
                "limitations": [
                    "Legacy project renderer evidence did not declare a visual-fidelity contract."
                ],
            }
        if batch_quality.get("structuralStatus") != "PASS":
            raise ValueError("offline project render did not pass structural artifact generation")
        pages = render_execution.get("pages")
        if not isinstance(pages, list) or not pages:
            raise ValueError("project render execution contains no pages")
        render_page_uuids = [
            item.get("documentUuid") if isinstance(item, Mapping) else None for item in pages
        ]
        if render_page_uuids != source_page_uuids:
            raise ValueError("project render page order or UUIDs differ from the guarded EPRO")

        captured_at = utc_now()
        operations: list[dict[str, Any]] = []
        warnings = list(batch_quality.get("limitations") or [])
        review_required = batch_quality.get("visualReviewRequired") is not False
        for index, page in enumerate(pages, start=1):
            if not isinstance(page, Mapping):
                raise ValueError(f"project render page {index} must be an object")
            document_uuid = str(page["documentUuid"])
            page_render = page.get("renderExecution")
            if not isinstance(page_render, Mapping):
                raise ValueError(f"project render page {document_uuid} has no render execution")
            if page_render.get("schemaVersion") != OFFLINE_RENDER_SCHEMA:
                raise ValueError(f"project render page {document_uuid} schema is invalid")
            if page_render.get("executionModel") != "LOCAL_ONLY_NO_EASYEDA_CALLS":
                raise ValueError(f"project render page {document_uuid} was not local-only")
            page_source_path, page_source_sha256 = _artifact(
                page_render.get("source"), f"project render page {document_uuid} source"
            )
            if page_source_path not in allowed_source_paths or page_source_sha256 != source_sha256:
                raise ValueError(f"project render page {document_uuid} used a different EPRO")
            png_path, png_sha256 = _artifact(
                page_render.get("png"), f"project render page {document_uuid} PNG"
            )
            published_png = page.get("publishedPng")
            if isinstance(published_png, str) and published_png.strip():
                published_png_path, published_png_sha256 = _artifact(
                    {"path": published_png, "sha256": png_sha256},
                    f"published project render page {document_uuid} PNG",
                )
                if published_png_sha256 != png_sha256:
                    raise ValueError(f"published project render page {document_uuid} digest mismatch")
                png_path = published_png_path
            render_evidence_path, render_envelope = _passing_envelope(
                page_render.get("evidencePath"),
                OFFLINE_RENDER_SCHEMA,
                f"project render page {document_uuid}",
            )
            render_spec = render_envelope.get("spec")
            if (
                render_envelope.get("easyedaApiCallCount") != 0
                or not isinstance(render_spec, Mapping)
                or render_spec.get("documentUuid") != document_uuid
                or render_spec.get("renderPng") is not True
            ):
                raise ValueError(f"project render page {document_uuid} evidence is not page-bound")
            page_quality_value = render_envelope.get("quality")
            if isinstance(page_quality_value, Mapping):
                page_quality = dict(page_quality_value)
            else:
                page_quality = {
                    "structuralStatus": "PASS",
                    "visualStatus": "LEGACY_UNSPECIFIED",
                    "visualReviewRequired": True,
                    "limitations": [
                        f"Legacy renderer evidence for page {document_uuid} did not declare a visual-fidelity contract."
                    ],
                }
            if page_quality.get("structuralStatus") != "PASS":
                raise ValueError(
                    f"project render page {document_uuid} did not pass structural artifact generation"
                )
            review_required = (
                review_required or page_quality.get("visualReviewRequired") is not False
            )
            for warning in page_quality.get("limitations") or []:
                if warning not in warnings:
                    warnings.append(warning)

            page_name = str(page.get("pageName") or document_uuid)
            schematic_name = str(page.get("schematicName") or "")
            asset_meta = {
                "schemaVersion": PROJECT_IMPORT_SCHEMA,
                "evidenceSource": "official-easyeda-export",
                "scope": "current-project-from-epro",
                "projectUuid": before["projectUuid"],
                "documentUuid": document_uuid,
                "documentType": 1,
                "schematicUuid": str(page.get("schematicUuid") or ""),
                "schematicName": schematic_name,
                "pageName": page_name,
                "projectPageIndex": index,
                "projectPageCount": len(pages),
                "sourcePath": str(source_path),
                "sourceSha256": source_sha256,
                "sourceEvidencePath": str(source_evidence_path),
                "batchRenderEvidencePath": str(batch_evidence_path),
                "renderPath": str(png_path),
                "renderSha256": png_sha256,
                "renderEvidencePath": str(render_evidence_path),
                "renderQuality": page_quality,
                "capturedAt": captured_at,
            }
            operations.append(
                {
                    "index": index,
                    "documentUuid": document_uuid,
                    "schematicUuid": asset_meta["schematicUuid"],
                    "schematicName": schematic_name,
                    "pageName": page_name,
                    "reviewRequired": page_quality.get("visualReviewRequired") is not False,
                    "tool": "mcp__jlc_hardware_learning_mcp__insert_hardware_learning_image",
                    "toolArgs": {
                        "projectDir": str(root),
                        "pageId": page_id,
                        "imagePath": str(png_path),
                        "replaceAiImageHolder": False,
                        "evidenceSource": "official-easyeda-export",
                        "altText": f"EasyEDA {schematic_name} / {page_name} ({document_uuid})",
                        "placement": "right",
                        "margin": 60,
                        "matchAnchor": False,
                        "assetMeta": asset_meta,
                        "shapeMeta": {
                            "hardwareLearningEvidence": True,
                            "easyedaProjectUuid": before["projectUuid"],
                            "easyedaDocumentUuid": document_uuid,
                            "evidenceSha256": png_sha256,
                            "projectPageIndex": index,
                        },
                    },
                }
            )

        manifest: dict[str, Any] = {
            "schemaVersion": PROJECT_IMPORT_SCHEMA,
            "status": "READY",
            "reviewRequired": review_required,
            "warnings": warnings,
            "createdAt": captured_at,
            "projectDir": str(root),
            "canvasPageId": page_id,
            "easyedaIdentity": before,
            "source": {
                "path": str(source_path),
                "sha256": source_sha256,
                "evidencePath": str(source_evidence_path),
            },
            "render": {
                "pageCount": len(operations),
                "evidencePath": str(batch_evidence_path),
                "quality": batch_quality,
            },
            "layout": {
                "strategy": "ordered-horizontal",
                "anchorFromPreviousResult": True,
                "placement": "right",
                "margin": 60,
            },
            "operations": operations,
        }
        manifest["manifestSha256"] = sha256_json(manifest)
        return manifest
