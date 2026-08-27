"""Guarded schematic exports through the official EasyEDA bridge."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
from typing import Any, Mapping

from .artifact_io import (
    atomic_write_json,
    create_evidence_directory,
    identity_subset,
    publish_copy_no_overwrite,
    sha256_file,
    sha256_json,
    utc_now,
)
from .client import BridgeClient
from .contract import ApiRegistry, canonical_json
from .errors import BridgeError, ContractError
from .export_safety import CAPABILITIES, ExportSafetyController, default_safety_state_path
from .native_visual import inspect_native_png_artifact
from .version import GATEWAY_VERSION
from .window_guard import resolve_window


EXPORT_RESULT_SCHEMA = "easyeda.gateway.schematic-export-result.v1"
EXPORT_EVIDENCE_SCHEMA = "easyeda.gateway.schematic-export-evidence.v1"
EXPORT_ADAPTER_VERSION = "1.0.0"

IDENTITY_METHOD_IDS = (
    "DMT_Project.getCurrentProjectInfo#1",
    "DMT_SelectControl.getCurrentDocumentInfo#1",
)
EXPORT_METHOD_ID = "SCH_ManufactureData.getExportDocumentFile#1"
LOCAL_SAVE_METHOD_ID = "SYS_FileSystem.saveFileToFileSystem#1"

FORMAT_SUFFIXES = {"PNG": ".png", "PDF": ".pdf", "SVG": ".svg"}
FORMAT_ENUM_MEMBERS = {
    "PNG": "ESCH_ExportDocumentFileType.PNG",
    "PDF": "ESCH_ExportDocumentFileType.PDF",
    "SVG": "ESCH_ExportDocumentFileType.SVG",
}
SCOPES = {
    "current-page": "Current Schematic Page",
    "current-schematic": "Current Schematic",
}
THEMES = {"Default", "White on Black", "Black on White"}
LINE_WIDTHS = {"Default", "Always 1px", "Follow the Zoom Change"}

COMPATIBILITY_CONTRACT = {
    "status": "QUARANTINED_CAPABILITY_MATRIX",
    "methodId": EXPORT_METHOD_ID,
    "deprecatedSince": "EDA v4.1",
    "reason": (
        "The official API has no non-deprecated schematic visual-export replacement; "
        "the retained $jlc exporter established the compatible official-bridge route."
    ),
    "localArtifactWriteMethodId": LOCAL_SAVE_METHOD_ID,
    "verifiedScope": "Current Schematic",
    "currentPageScopeStatus": "BLOCKED_KNOWN_HANG",
    "ordinaryTypedPlansRemainBlocked": True,
}


@dataclass(frozen=True)
class SchematicExportSpec:
    file_type: str = "PNG"
    scope: str = "current-schematic"
    theme: str = "Black on White"
    line_width: str = "Always 1px"

    def normalized(self) -> "SchematicExportSpec":
        file_type = self.file_type.upper()
        if file_type not in FORMAT_SUFFIXES:
            raise ContractError(f"Unsupported schematic export format: {self.file_type}")
        if self.scope not in SCOPES:
            raise ContractError(f"Unsupported schematic export scope: {self.scope}")
        if self.theme not in THEMES:
            raise ContractError(f"Unsupported schematic export theme: {self.theme}")
        if self.line_width not in LINE_WIDTHS:
            raise ContractError(f"Unsupported schematic export line width: {self.line_width}")
        return SchematicExportSpec(file_type, self.scope, self.theme, self.line_width)

    @property
    def suffix(self) -> str:
        return FORMAT_SUFFIXES[self.normalized().file_type]

    def as_dict(self) -> dict[str, str]:
        value = self.normalized()
        return {
            "fileType": value.file_type,
            "scope": value.scope,
            "officialScope": SCOPES[value.scope],
            "theme": value.theme,
            "lineWidth": value.line_width,
        }


@dataclass(frozen=True)
class SchematicExportResult:
    bridge_url: str
    window_id: str
    identity: dict[str, Any]
    spec: SchematicExportSpec
    artifact_path: Path
    artifact_sha256: str
    artifact_bytes: int
    inspection: dict[str, Any]
    evidence_path: Path
    published_output: Path | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "schemaVersion": "easyeda.gateway.schematic-export-execution.v1",
            "adapterVersion": EXPORT_ADAPTER_VERSION,
            "bridgeUrl": self.bridge_url,
            "windowId": self.window_id,
            "identity": self.identity,
            "spec": self.spec.as_dict(),
            "artifact": {
                "path": str(self.artifact_path),
                "sha256": self.artifact_sha256,
                "bytes": self.artifact_bytes,
                **self.inspection,
            },
            "publishedOutput": str(self.published_output) if self.published_output else None,
            "evidencePath": str(self.evidence_path),
            "compatibility": dict(COMPATIBILITY_CONTRACT),
        }


class EasyedaExportAdapter:
    """Export fixed schematic artifacts without weakening ordinary plan validation."""

    def __init__(self, registry: ApiRegistry, client: BridgeClient):
        self.registry = registry
        self.client = client
        self._validate_contract()

    def _validate_contract(self) -> None:
        for method_id in IDENTITY_METHOD_IDS:
            descriptor = self.registry.resolve_method(method_id)
            if descriptor.deprecated:
                raise ContractError(f"Export identity guard references deprecated method: {method_id}")
        export_method = self.registry.resolve_method(EXPORT_METHOD_ID)
        if export_method.runtime_module != "sch_ManufactureData":
            raise ContractError("Locked schematic export method runtime module changed")
        save_method = self.registry.resolve_method(LOCAL_SAVE_METHOD_ID)
        if save_method.runtime_module != "sys_FileSystem" or save_method.method_name != "saveFileToFileSystem":
            raise ContractError("Locked local artifact save method changed")
        for enum_reference in FORMAT_ENUM_MEMBERS.values():
            if not self.registry.validate_enum_reference(enum_reference):
                raise ContractError(f"Locked export enum reference is unavailable: {enum_reference}")

    def build_code(
        self,
        spec: SchematicExportSpec,
        artifact_path: str | Path,
        identity: Mapping[str, Any] | None = None,
    ) -> str:
        value = spec.normalized()
        target = Path(artifact_path).resolve()
        if target.suffix.lower() != FORMAT_SUFFIXES[value.file_type]:
            raise ContractError(
                f"{value.file_type} export path must use the {FORMAT_SUFFIXES[value.file_type]} suffix",
            )
        expected = {
            "projectUuid": (identity or {}).get("projectUuid"),
            "documentUuid": (identity or {}).get("documentUuid"),
            "documentType": 1,
        }
        enum_member = FORMAT_ENUM_MEMBERS[value.file_type]
        statements = [
            "const ESCH_ExportDocumentFileType=Object.freeze({PDF:'PDF',PNG:'PNG',SVG:'SVG'})",
            f"const __artifactPath={canonical_json(str(target))}",
            "const __readIdentity=async()=>{const project=await eda.dmt_Project.getCurrentProjectInfo();const document=await eda.dmt_SelectControl.getCurrentDocumentInfo();return {projectUuid:project?.uuid??document?.parentProjectUuid??null,documentUuid:document?.uuid??null,documentType:document?.documentType??null,project,document}}",
            f"const __expected={canonical_json(expected)}",
            "const __before=await __readIdentity()",
            "for(const key of ['projectUuid','documentUuid','documentType']){if(__expected[key]!==null&&__expected[key]!==__before[key]){throw new Error(`EasyEDA identity mismatch for ${key}: expected ${String(__expected[key])}, got ${String(__before[key])}`)}}",
            (
                "const __file=await eda.sch_ManufactureData.getExportDocumentFile("
                f"'easyeda-schematic-export',{enum_member},"
                f"{{theme:{canonical_json(value.theme)},lineWidth:{canonical_json(value.line_width)},displayAttributesAsMenu:false,size:'Original Size'}},"
                f"{canonical_json(SCOPES[value.scope])})"
            ),
            "if(!__file){throw new Error('EasyEDA did not return a schematic export file')}",
            "const __saved=await eda.sys_FileSystem.saveFileToFileSystem(__artifactPath,__file,undefined,false)",
            "if(__saved!==true){throw new Error('EasyEDA did not save the schematic export artifact')}",
            "const __after=await __readIdentity()",
            "for(const key of ['projectUuid','documentUuid','documentType']){if(__before[key]!==__after[key]){throw new Error(`EasyEDA identity changed during schematic export for ${key}`)}}",
            (
                f"return {{schemaVersion:'{EXPORT_RESULT_SCHEMA}',adapterVersion:'{EXPORT_ADAPTER_VERSION}',"
                "identityBefore:__before,identityAfter:__after,saved:__saved,"
                "artifact:{path:__artifactPath,name:__file.name??'',type:__file.type??'',size:__file.size??0}}"
            ),
        ]
        code = ";".join(statements) + ";"
        if "//" in code or "/*" in code:
            raise ContractError("Schematic export compilation produced a JavaScript comment")
        return code

    def execute(
        self,
        spec: SchematicExportSpec,
        evidence_root: str | Path,
        *,
        identity: Mapping[str, Any] | None = None,
        window_id: str | None = None,
        output_path: str | Path | None = None,
        safety_state_path: str | Path | None = None,
        allow_window_rebind: bool = False,
    ) -> SchematicExportResult:
        value = spec.normalized()
        published = self._validate_published_output(output_path, value)
        evidence_directory = create_evidence_directory(evidence_root, "schematic-export")
        started_at = utc_now()
        safety_path = Path(safety_state_path).resolve() if safety_state_path else default_safety_state_path(evidence_root)
        try:
            return self._execute_in_directory(
                value,
                evidence_directory,
                identity=identity,
                window_id=window_id,
                published=published,
                started_at=started_at,
                safety_state_path=safety_path,
                allow_window_rebind=allow_window_rebind,
            )
        except Exception as exc:
            try:
                self._record_failure(
                    evidence_directory,
                    value,
                    identity=identity,
                    started_at=started_at,
                    error=exc,
                )
            except OSError:
                pass
            raise

    def _execute_in_directory(
        self,
        value: SchematicExportSpec,
        evidence_directory: Path,
        *,
        identity: Mapping[str, Any] | None,
        window_id: str | None,
        published: Path | None,
        started_at: str,
        safety_state_path: Path,
        allow_window_rebind: bool,
    ) -> SchematicExportResult:
        artifact_stem = "current-schematic-page" if value.scope == "current-page" else "current-schematic"
        artifact = evidence_directory / f"{artifact_stem}{FORMAT_SUFFIXES[value.file_type]}"
        code = self.build_code(value, artifact, identity)
        request = {
            "schemaVersion": "easyeda.gateway.schematic-export-request.v1",
            "adapterVersion": EXPORT_ADAPTER_VERSION,
            "registry": self.registry.identity,
            "expectedIdentity": dict(identity or {}),
            "spec": value.as_dict(),
            "capabilityId": _capability_id(value),
            "safetyStatePath": str(safety_state_path),
            "artifactPath": str(artifact),
            "generatedCodeSha256": hashlib.sha256(code.encode("utf-8")).hexdigest(),
            "methods": [*IDENTITY_METHOD_IDS, EXPORT_METHOD_ID, LOCAL_SAVE_METHOD_ID],
            "compatibility": dict(COMPATIBILITY_CONTRACT),
            "allowWindowRebind": bool(allow_window_rebind),
        }
        atomic_write_json(evidence_directory / "request.json", request)

        health_before = self.client.health()
        windows_before = self.client.windows()
        window_resolution = resolve_window(
            windows_before,
            requested_window_id=window_id,
            identity=identity,
            allow_rebind=allow_window_rebind,
        )
        target_window = window_resolution.resolved_window_id

        safety = ExportSafetyController(safety_state_path)
        safety.acquire(_capability_id(value), self.client, str(target_window))
        try:
            response = self.client.execute_code(code, str(target_window))
            health_after = self.client.health()
        except Exception as exc:
            safety.finish(success=False, error=exc)
            raise
        else:
            safety.finish(success=True)
        finished_at = utc_now()
        result = response.get("result")
        if not isinstance(result, Mapping) or result.get("schemaVersion") != EXPORT_RESULT_SCHEMA:
            raise BridgeError("Schematic export returned an invalid result envelope")
        if result.get("adapterVersion") != EXPORT_ADAPTER_VERSION or result.get("saved") is not True:
            raise BridgeError("Schematic export adapter identity or saved status mismatch")
        before = identity_subset(result.get("identityBefore"))
        after = identity_subset(result.get("identityAfter"))
        if before != after:
            raise BridgeError("EasyEDA identity drifted during schematic export")
        if before.get("documentType") != 1:
            raise BridgeError(f"Schematic export requires documentType=1, got {before.get('documentType')!r}")
        if not artifact.is_file() or artifact.stat().st_size <= 0:
            raise BridgeError(f"EasyEDA schematic export artifact was not written: {artifact}")

        artifact_bytes = artifact.stat().st_size
        bridge_artifact = result.get("artifact") if isinstance(result.get("artifact"), Mapping) else {}
        reported_size = bridge_artifact.get("size")
        if isinstance(reported_size, (int, float)) and reported_size > 0 and int(reported_size) != artifact_bytes:
            raise BridgeError(
                f"Schematic export size mismatch: bridge reported {reported_size}, local file is {artifact_bytes}",
            )
        inspection = _inspect_artifact(artifact, value.file_type)
        artifact_sha256 = sha256_file(artifact)

        published_output = None
        if published is not None:
            if inspection.get("containerFormat") is None:
                publish_copy_no_overwrite(artifact, published)
                if sha256_file(published) != artifact_sha256:
                    raise BridgeError("Published schematic export digest mismatch")
                published_output = published
            else:
                inspection["publicationOmitted"] = {
                    "requestedPath": str(published),
                    "reason": "multi-page official PNG bundle cannot be published as one PNG file",
                }

        result_record = {
            "bridgeResponse": response,
            "bridgeResponseSha256": sha256_json(response),
            "artifact": {
                "path": str(artifact),
                "sha256": artifact_sha256,
                "bytes": artifact_bytes,
                **inspection,
            },
            "publishedOutput": str(published_output) if published_output else None,
        }
        atomic_write_json(evidence_directory / "result.json", result_record)
        envelope = {
            "schemaVersion": EXPORT_EVIDENCE_SCHEMA,
            "status": "PASS",
            "risk": "READ_WITH_LOCAL_ARTIFACT",
            "startedAt": started_at,
            "finishedAt": finished_at,
            "gatewayVersion": GATEWAY_VERSION,
            "adapterVersion": EXPORT_ADAPTER_VERSION,
            "registry": self.registry.identity,
            "identity": before,
            "spec": value.as_dict(),
            "bridge": {
                "service": health_before.get("service"),
                "url": self.client.base_url,
                "windowId": str(target_window),
                "healthBefore": health_before,
                "healthAfter": health_after,
                "windowsBefore": windows_before,
                "windowResolution": window_resolution.as_dict(),
            },
            "compatibility": dict(COMPATIBILITY_CONTRACT),
            "safety": {
                "capabilityId": _capability_id(value),
                "statePath": str(safety_state_path),
                "automaticRetry": False,
            },
            "files": {
                "request.json": sha256_file(evidence_directory / "request.json"),
                "result.json": sha256_file(evidence_directory / "result.json"),
                artifact.name: artifact_sha256,
            },
        }
        for page in inspection.get("pages", []):
            page_path = Path(page["path"])
            envelope["files"][page_path.relative_to(evidence_directory).as_posix()] = page["sha256"]
        if published_output is not None:
            envelope["publishedOutput"] = {
                "path": str(published_output),
                "sha256": artifact_sha256,
            }
        atomic_write_json(evidence_directory / "envelope.json", envelope)
        return SchematicExportResult(
            bridge_url=self.client.base_url,
            window_id=str(target_window),
            identity=before,
            spec=value,
            artifact_path=artifact,
            artifact_sha256=artifact_sha256,
            artifact_bytes=artifact_bytes,
            inspection=inspection,
            evidence_path=evidence_directory / "envelope.json",
            published_output=published_output,
        )

    def _record_failure(
        self,
        evidence_directory: Path,
        spec: SchematicExportSpec,
        *,
        identity: Mapping[str, Any] | None,
        started_at: str,
        error: Exception,
    ) -> None:
        failure_path = evidence_directory / "failure.json"
        capability = CAPABILITIES[_capability_id(spec)]
        pre_execution_rejection = isinstance(error, ContractError) and not capability.executable
        safety = {
            "capabilityId": capability.capability_id,
            "capabilityStatus": capability.status,
            "rejectionStage": "CAPABILITY_ADMISSION" if pre_execution_rejection else None,
            "officialCallIssued": False if pre_execution_rejection else None,
            "automaticRetry": False,
        }
        failure = {
            "schemaVersion": "easyeda.gateway.schematic-export-failure.v1",
            "status": "FAIL",
            "startedAt": started_at,
            "finishedAt": utc_now(),
            "gatewayVersion": GATEWAY_VERSION,
            "adapterVersion": EXPORT_ADAPTER_VERSION,
            "registry": self.registry.identity,
            "expectedIdentity": dict(identity or {}),
            "spec": spec.as_dict(),
            "capabilityId": _capability_id(spec),
            "error": {
                "type": type(error).__name__,
                "message": str(error),
            },
            "compatibility": dict(COMPATIBILITY_CONTRACT),
            "safety": safety,
        }
        atomic_write_json(failure_path, failure)
        evidence_files = {}
        for candidate in sorted(evidence_directory.iterdir(), key=lambda item: item.name):
            if candidate.is_file() and candidate.name != "envelope.json":
                evidence_files[candidate.name] = sha256_file(candidate)
        envelope = {
            "schemaVersion": EXPORT_EVIDENCE_SCHEMA,
            "status": "FAIL",
            "risk": "READ_WITH_LOCAL_ARTIFACT",
            "startedAt": started_at,
            "finishedAt": failure["finishedAt"],
            "gatewayVersion": GATEWAY_VERSION,
            "adapterVersion": EXPORT_ADAPTER_VERSION,
            "registry": self.registry.identity,
            "expectedIdentity": dict(identity or {}),
            "spec": spec.as_dict(),
            "error": failure["error"],
            "compatibility": dict(COMPATIBILITY_CONTRACT),
            "safety": safety,
            "files": evidence_files,
        }
        atomic_write_json(evidence_directory / "envelope.json", envelope)

    @staticmethod
    def _validate_published_output(
        output_path: str | Path | None,
        spec: SchematicExportSpec,
    ) -> Path | None:
        if output_path is None:
            return None
        target = Path(output_path).resolve()
        if target.suffix.lower() != FORMAT_SUFFIXES[spec.file_type]:
            raise ContractError(
                f"{spec.file_type} published output must use the {FORMAT_SUFFIXES[spec.file_type]} suffix",
            )
        if target.exists():
            raise ContractError(f"Published schematic export already exists: {target}")
        target.parent.mkdir(parents=True, exist_ok=True)
        return target

def _capability_id(spec: SchematicExportSpec) -> str:
    value = spec.normalized()
    return f"visual.{value.scope}.{value.file_type.lower()}"


def _inspect_artifact(path: Path, file_type: str) -> dict[str, Any]:
    if file_type == "PNG":
        return inspect_native_png_artifact(path, extract_dir=path.parent / "native-pages")
    data = path.read_bytes()
    if file_type == "PDF":
        if not data.startswith(b"%PDF-"):
            raise BridgeError("Schematic PDF export has an invalid PDF signature")
        return {"mediaType": "application/pdf"}
    prefix = data[:4096].decode("utf-8-sig", errors="replace").lstrip()
    if "<svg" not in prefix:
        raise BridgeError("Schematic SVG export has no SVG root element")
    return {"mediaType": "image/svg+xml"}
