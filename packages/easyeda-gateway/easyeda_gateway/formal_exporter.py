"""Guarded BOM, netlist, and document-source exports for EasyEDA schematics."""

from __future__ import annotations

from dataclasses import dataclass
import csv
import hashlib
import io
import json
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
from .source_renderer_v22 import PdfSourceError, list_v22_sheets
from .version import GATEWAY_VERSION
from .window_guard import resolve_window


FORMAL_EXPORT_RESULT_SCHEMA = "easyeda.gateway.formal-export-result.v1"
FORMAL_EXPORT_EVIDENCE_SCHEMA = "easyeda.gateway.formal-export-evidence.v1"
FORMAL_EXPORT_ADAPTER_VERSION = "1.2.0"
SOURCE_NORMALIZATION_IGNORED = (
    "DOCHEAD.client",
    "DOCHEAD.updateTime",
    "DOCHEAD.version",
)

IDENTITY_METHOD_IDS = (
    "DMT_Project.getCurrentProjectInfo#1",
    "DMT_SelectControl.getCurrentDocumentInfo#1",
)
LOCAL_SAVE_METHOD_ID = "SYS_FileSystem.saveFileToFileSystem#1"
KIND_METHOD_IDS = {
    "bom": ("SCH_ManufactureData.getBomFile#1",),
    "netlist": ("SCH_ManufactureData.getNetlistFile#1",),
    "source": (
        "SYS_FileManager.getDocumentFile#1",
        "SYS_FileManager.getDocumentSource#1",
    ),
    "project-source": (
        "DMT_Schematic.getAllSchematicsInfo#1",
        "SYS_FileManager.getProjectFile#1",
    ),
}
VARIANTS = {
    "bom": {"csv", "xlsx"},
    "netlist": {"jlceda", "protel2"},
    "source": {"epro", "epro2"},
    "project-source": {"epro"},
}
SUFFIXES = {
    ("bom", "csv"): ".csv",
    ("bom", "xlsx"): ".xlsx",
    ("netlist", "jlceda"): ".net",
    ("netlist", "protel2"): ".net",
    ("source", "epro"): ".epro",
    ("source", "epro2"): ".epro2",
    ("project-source", "epro"): ".epro",
}
ARTIFACT_STEMS = {
    "bom": "official-bom",
    "netlist": "official-netlist",
    "source": "active-document-source",
    "project-source": "active-project-source",
}
NETLIST_ENUM_MEMBERS = {"jlceda": "JLCEDA_PRO", "protel2": "PROTEL2"}


@dataclass(frozen=True)
class FormalExportSpec:
    kind: str
    variant: str

    def normalized(self) -> "FormalExportSpec":
        kind = self.kind.strip().lower()
        variant = self.variant.strip().lower()
        if kind not in VARIANTS:
            raise ContractError(f"Unsupported formal export kind: {self.kind}")
        if variant not in VARIANTS[kind]:
            raise ContractError(f"Unsupported {kind} export variant: {self.variant}")
        return FormalExportSpec(kind, variant)

    @property
    def capability_id(self) -> str:
        value = self.normalized()
        return f"{value.kind}.{value.variant}"

    @property
    def suffix(self) -> str:
        value = self.normalized()
        return SUFFIXES[(value.kind, value.variant)]

    @property
    def artifact_name(self) -> str:
        value = self.normalized()
        return f"{ARTIFACT_STEMS[value.kind]}{value.suffix}"

    def as_dict(self) -> dict[str, str]:
        value = self.normalized()
        return {
            "kind": value.kind,
            "variant": value.variant,
            "capabilityId": value.capability_id,
            "suffix": value.suffix,
        }


@dataclass(frozen=True)
class FormalExportResult:
    bridge_url: str
    window_id: str
    identity: dict[str, Any]
    spec: FormalExportSpec
    artifact_path: Path
    artifact_sha256: str
    artifact_bytes: int
    inspection: dict[str, Any]
    evidence_path: Path
    published_output: Path | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "schemaVersion": "easyeda.gateway.formal-export-execution.v1",
            "adapterVersion": FORMAL_EXPORT_ADAPTER_VERSION,
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
        }


class EasyedaFormalExportAdapter:
    """Export exactly one formal artifact per bridge request."""

    def __init__(self, registry: ApiRegistry, client: BridgeClient):
        self.registry = registry
        self.client = client
        self._validate_contract()

    def _validate_contract(self) -> None:
        method_ids = {
            *IDENTITY_METHOD_IDS,
            LOCAL_SAVE_METHOD_ID,
            *(item for values in KIND_METHOD_IDS.values() for item in values),
        }
        for method_id in method_ids:
            descriptor = self.registry.resolve_method(method_id)
            if descriptor.deprecated:
                raise ContractError(f"Formal export references deprecated method: {method_id}")
        if not self.registry.validate_enum_reference("ESYS_NetlistType.JLCEDA_PRO"):
            raise ContractError("Locked JLCEDA netlist enum is unavailable")
        if not self.registry.validate_enum_reference("ESYS_NetlistType.PROTEL2"):
            raise ContractError("Locked Protel2 netlist enum is unavailable")

    def build_code(
        self,
        spec: FormalExportSpec,
        artifact_path: str | Path,
        identity: Mapping[str, Any] | None = None,
    ) -> str:
        value = spec.normalized()
        target = Path(artifact_path).resolve()
        if target.suffix.lower() != value.suffix:
            raise ContractError(f"{value.kind}/{value.variant} output must use {value.suffix}")
        expected = {
            "projectUuid": (identity or {}).get("projectUuid"),
            "documentUuid": (identity or {}).get("documentUuid"),
            "documentType": 1,
        }
        statements = [
            f"const __artifactPath={canonical_json(str(target))}",
            "const __readIdentity=async()=>{const project=await eda.dmt_Project.getCurrentProjectInfo();const document=await eda.dmt_SelectControl.getCurrentDocumentInfo();return {projectUuid:project?.uuid??document?.parentProjectUuid??null,documentUuid:document?.uuid??null,documentType:document?.documentType??null,project,document}}",
            f"const __expected={canonical_json(expected)}",
            "const __before=await __readIdentity()",
            "for(const key of ['projectUuid','documentUuid','documentType']){if(__expected[key]!==null&&__expected[key]!==__before[key]){throw new Error(`EasyEDA identity mismatch for ${key}: expected ${String(__expected[key])}, got ${String(__before[key])}`)}}",
        ]
        if value.kind == "bom":
            statements.append(
                f"const __file=await eda.sch_ManufactureData.getBomFile('easyeda-official-bom',{canonical_json(value.variant)})",
            )
        elif value.kind == "netlist":
            statements.extend(
                [
                    "const ESYS_NetlistType=Object.freeze({JLCEDA_PRO:'JLCEDA',PROTEL2:'Protel2'})",
                    (
                        "const __file=await eda.sch_ManufactureData.getNetlistFile("
                        "'easyeda-official-netlist',"
                        f"ESYS_NetlistType.{NETLIST_ENUM_MEMBERS[value.variant]})"
                    ),
                ],
            )
        elif value.kind == "source":
            statements.extend(
                [
                    "const __normalizeSource=(source)=>{if(typeof source!=='string'||!source){return null}const lines=source.split('\\n');const line=lines[0]||'';const split=line.indexOf('||');if(split<0||!line.endsWith('|')){return source}try{const meta=JSON.parse(line.slice(split+2,-1));if(meta?.docType!=='SCH_PAGE'){return source}delete meta.client;delete meta.updateTime;delete meta.version;lines[0]=line.slice(0,split+2)+JSON.stringify(meta)+'|';return lines.join('\\n')}catch{return source}}",
                    "const __sourceBefore=await eda.sys_FileManager.getDocumentSource()",
                    "if(typeof __sourceBefore!=='string'||!__sourceBefore){throw new Error('EasyEDA did not return the active document source')}",
                    "const __normalizedSourceBefore=__normalizeSource(__sourceBefore)",
                    "if(typeof __normalizedSourceBefore!=='string'||!__normalizedSourceBefore){throw new Error('EasyEDA document source could not be normalized safely')}",
                    (
                        "const __file=await eda.sys_FileManager.getDocumentFile("
                        f"'easyeda-active-document',undefined,{canonical_json(value.variant)})"
                    ),
                ],
            )
        else:
            statements.extend(
                [
                    "const __readProjectPages=async()=>{const schematics=await eda.dmt_Schematic.getAllSchematicsInfo();return (schematics||[]).flatMap(s=>(s.page||[]).map(p=>({schematicUuid:String(s.uuid??''),schematicName:String(s.name??''),documentUuid:String(p.uuid??''),pageName:String(p.name??''),parentSchematicUuid:String(p.parentSchematicUuid??s.uuid??'')})))}",
                    "const __projectPagesBefore=await __readProjectPages()",
                    "if(!Array.isArray(__projectPagesBefore)||__projectPagesBefore.length<1){throw new Error('EasyEDA current project contains no schematic pages')}",
                    (
                        "const __file=await eda.sys_FileManager.getProjectFile("
                        f"'easyeda-active-project',undefined,{canonical_json(value.variant)})"
                    ),
                ],
            )
        statements.extend(
            [
                "if(!__file){throw new Error('EasyEDA did not return the formal export file')}",
                "const __saved=await eda.sys_FileSystem.saveFileToFileSystem(__artifactPath,__file,undefined,false)",
                "if(__saved!==true){throw new Error('EasyEDA did not save the formal export artifact')}",
            ],
        )
        if value.kind == "source":
            statements.extend(
                [
                    "const __sourceAfter=await eda.sys_FileManager.getDocumentSource()",
                    "const __normalizedSourceAfter=__normalizeSource(__sourceAfter)",
                    "const __rawSourceUnchanged=__sourceBefore===__sourceAfter",
                    "const __sourceUnchanged=__normalizedSourceBefore!==null&&__normalizedSourceBefore===__normalizedSourceAfter",
                    "if(!__sourceUnchanged){throw new Error('EasyEDA document source changed outside the allowed volatile DOCHEAD metadata during read-only export')}",
                ],
            )
        elif value.kind == "project-source":
            statements.extend(
                [
                    "const __projectPagesAfter=await __readProjectPages()",
                    "const __projectTreeUnchanged=JSON.stringify(__projectPagesBefore)===JSON.stringify(__projectPagesAfter)",
                    "if(!__projectTreeUnchanged){throw new Error('EasyEDA project schematic tree changed during read-only export')}",
                ],
            )
        statements.extend(
            [
                "const __after=await __readIdentity()",
                "for(const key of ['projectUuid','documentUuid','documentType']){if(__before[key]!==__after[key]){throw new Error(`EasyEDA identity changed during formal export for ${key}`)}}",
                (
                    f"return {{schemaVersion:'{FORMAL_EXPORT_RESULT_SCHEMA}',adapterVersion:'{FORMAL_EXPORT_ADAPTER_VERSION}',"
                    "identityBefore:__before,identityAfter:__after,saved:__saved,"
                    "rawSourceUnchanged:typeof __rawSourceUnchanged==='undefined'||__rawSourceUnchanged,"
                    "sourceUnchanged:typeof __sourceUnchanged==='undefined'||__sourceUnchanged,"
                    "sourceNormalizationIgnored:typeof __sourceUnchanged==='undefined'?[]:['DOCHEAD.client','DOCHEAD.updateTime','DOCHEAD.version'],"
                    "projectTreeUnchanged:typeof __projectTreeUnchanged==='undefined'||__projectTreeUnchanged,"
                    "projectPages:typeof __projectPagesBefore==='undefined'?[]:__projectPagesBefore,"
                    "artifact:{path:__artifactPath,name:__file.name??'',type:__file.type??'',size:__file.size??0}}"
                ),
            ],
        )
        code = ";".join(statements) + ";"
        if "//" in code or "/*" in code:
            raise ContractError("Formal export compilation produced a JavaScript comment")
        return code

    def execute(
        self,
        spec: FormalExportSpec,
        evidence_root: str | Path,
        *,
        identity: Mapping[str, Any] | None = None,
        window_id: str | None = None,
        output_path: str | Path | None = None,
        safety_state_path: str | Path | None = None,
        allow_window_rebind: bool = False,
    ) -> FormalExportResult:
        value = spec.normalized()
        published = _validate_output(output_path, value)
        evidence_directory = create_evidence_directory(evidence_root, f"{value.kind}-export")
        artifact = evidence_directory / value.artifact_name
        safety_path = Path(safety_state_path).resolve() if safety_state_path else default_safety_state_path(evidence_root)
        started_at = utc_now()
        code = self.build_code(value, artifact, identity)
        request = {
            "schemaVersion": "easyeda.gateway.formal-export-request.v1",
            "adapterVersion": FORMAL_EXPORT_ADAPTER_VERSION,
            "registry": self.registry.identity,
            "expectedIdentity": dict(identity or {}),
            "spec": value.as_dict(),
            "artifactPath": str(artifact),
            "safetyStatePath": str(safety_path),
            "generatedCodeSha256": hashlib.sha256(code.encode("utf-8")).hexdigest(),
            "methods": [*IDENTITY_METHOD_IDS, *KIND_METHOD_IDS[value.kind], LOCAL_SAVE_METHOD_ID],
        }
        atomic_write_json(evidence_directory / "request.json", request)
        try:
            return self._execute_request(
                value,
                artifact,
                evidence_directory,
                code,
                identity=identity,
                window_id=window_id,
                published=published,
                safety_path=safety_path,
                started_at=started_at,
                allow_window_rebind=allow_window_rebind,
            )
        except Exception as exc:
            try:
                _record_failure(
                    evidence_directory,
                    self.registry.identity,
                    value,
                    identity,
                    started_at,
                    exc,
                )
            except OSError:
                pass
            raise

    def _execute_request(
        self,
        spec: FormalExportSpec,
        artifact: Path,
        evidence_directory: Path,
        code: str,
        *,
        identity: Mapping[str, Any] | None,
        window_id: str | None,
        published: Path | None,
        safety_path: Path,
        started_at: str,
        allow_window_rebind: bool,
    ) -> FormalExportResult:
        health_before = self.client.health()
        windows_before = self.client.windows()
        window_resolution = resolve_window(
            windows_before,
            requested_window_id=window_id,
            identity=identity,
            allow_rebind=allow_window_rebind,
        )
        target_window = window_resolution.resolved_window_id
        safety = ExportSafetyController(safety_path)
        safety.acquire(spec.capability_id, self.client, str(target_window))
        try:
            response = self.client.execute_code(code, str(target_window))
            health_after = self.client.health()
        except Exception as exc:
            safety.finish(success=False, error=exc)
            raise
        else:
            safety.finish(success=True)
        result = response.get("result")
        if not isinstance(result, Mapping) or result.get("schemaVersion") != FORMAL_EXPORT_RESULT_SCHEMA:
            raise BridgeError("Formal export returned an invalid result envelope")
        if result.get("adapterVersion") != FORMAL_EXPORT_ADAPTER_VERSION or result.get("saved") is not True:
            raise BridgeError("Formal export adapter identity or saved status mismatch")
        before = identity_subset(result.get("identityBefore"))
        after = identity_subset(result.get("identityAfter"))
        if before != after or before.get("documentType") != 1:
            raise BridgeError("EasyEDA identity changed or is not a schematic during formal export")
        if spec.kind == "source":
            if result.get("sourceUnchanged") is not True:
                raise BridgeError("EasyEDA source was not preserved during source export")
            if not isinstance(result.get("rawSourceUnchanged"), bool):
                raise BridgeError("EasyEDA source export omitted the raw preservation result")
            if result.get("sourceNormalizationIgnored") != list(SOURCE_NORMALIZATION_IGNORED):
                raise BridgeError("EasyEDA source export used an unexpected normalization allowlist")
        bridge_project_pages: list[dict[str, str]] = []
        if spec.kind == "project-source":
            if result.get("projectTreeUnchanged") is not True:
                raise BridgeError("EasyEDA project schematic tree was not preserved during export")
            raw_project_pages = result.get("projectPages")
            if not isinstance(raw_project_pages, list) or not raw_project_pages:
                raise BridgeError("EasyEDA project source export returned no schematic page tree")
            seen_document_uuids: set[str] = set()
            for index, item in enumerate(raw_project_pages):
                if not isinstance(item, Mapping):
                    raise BridgeError(f"EasyEDA project page {index} is not an object")
                document_uuid = item.get("documentUuid")
                schematic_uuid = item.get("schematicUuid")
                if not isinstance(document_uuid, str) or not document_uuid:
                    raise BridgeError(f"EasyEDA project page {index} has no document UUID")
                if not isinstance(schematic_uuid, str) or not schematic_uuid:
                    raise BridgeError(f"EasyEDA project page {document_uuid} has no schematic UUID")
                if document_uuid in seen_document_uuids:
                    raise BridgeError(f"EasyEDA project tree repeats page UUID {document_uuid}")
                seen_document_uuids.add(document_uuid)
                bridge_project_pages.append(
                    {
                        "documentUuid": document_uuid,
                        "schematicUuid": schematic_uuid,
                        "schematicName": str(item.get("schematicName") or ""),
                        "pageName": str(item.get("pageName") or ""),
                    }
                )
        if not artifact.is_file() or artifact.stat().st_size <= 0:
            raise BridgeError(f"Formal export artifact was not written: {artifact}")
        artifact_bytes = artifact.stat().st_size
        bridge_artifact = result.get("artifact") if isinstance(result.get("artifact"), Mapping) else {}
        reported_size = bridge_artifact.get("size")
        if isinstance(reported_size, (int, float)) and reported_size > 0 and int(reported_size) != artifact_bytes:
            raise BridgeError(
                f"Formal export size mismatch: bridge reported {reported_size}, local file is {artifact_bytes}",
            )
        inspection = inspect_formal_artifact(artifact, spec)
        if spec.kind == "project-source":
            try:
                archive_sheets = list_v22_sheets(artifact)
            except PdfSourceError as exc:
                raise BridgeError(f"Project EPRO page inventory is invalid: {exc}") from exc
            archive_uuids = {item.document_uuid for item in archive_sheets}
            bridge_uuids = {item["documentUuid"] for item in bridge_project_pages}
            if archive_uuids != bridge_uuids:
                raise BridgeError(
                    "Project EPRO schematic page UUIDs differ from the guarded live project tree"
                )
            inspection = {
                **inspection,
                "sheetCount": len(archive_sheets),
                "sheets": [item.as_dict() for item in archive_sheets],
                "bridgeProjectPages": bridge_project_pages,
            }
        artifact_sha256 = sha256_file(artifact)
        published_output = None
        if published is not None:
            publish_copy_no_overwrite(artifact, published)
            if sha256_file(published) != artifact_sha256:
                raise BridgeError("Published formal export digest mismatch")
            published_output = published
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
            "schemaVersion": FORMAL_EXPORT_EVIDENCE_SCHEMA,
            "status": "PASS",
            "risk": "READ_WITH_LOCAL_ARTIFACT",
            "startedAt": started_at,
            "finishedAt": utc_now(),
            "gatewayVersion": GATEWAY_VERSION,
            "adapterVersion": FORMAL_EXPORT_ADAPTER_VERSION,
            "registry": self.registry.identity,
            "identity": before,
            "bridge": {
                "service": health_before.get("service"),
                "url": self.client.base_url,
                "windowId": str(target_window),
                "healthBefore": health_before,
                "healthAfter": health_after,
                "windowsBefore": windows_before,
                "windowResolution": window_resolution.as_dict(),
            },
            "safety": {
                "capabilityId": spec.capability_id,
                "statePath": str(safety_path),
                "executionModel": "ONE_OFFICIAL_CALL_PER_BRIDGE_REQUEST",
                "automaticRetry": False,
            },
            "files": {
                "request.json": sha256_file(evidence_directory / "request.json"),
                "result.json": sha256_file(evidence_directory / "result.json"),
                artifact.name: artifact_sha256,
            },
        }
        if published_output is not None:
            envelope["publishedOutput"] = {"path": str(published_output), "sha256": artifact_sha256}
        if spec.kind == "source":
            envelope["sourcePreservation"] = {
                "rawSourceUnchanged": result["rawSourceUnchanged"],
                "sourceUnchanged": True,
                "normalizationIgnored": list(SOURCE_NORMALIZATION_IGNORED),
            }
        elif spec.kind == "project-source":
            envelope["projectTreePreservation"] = {
                "treeUnchanged": True,
                "bridgePageCount": len(bridge_project_pages),
                "archivePageCount": inspection["sheetCount"],
                "pageUuidSetMatch": True,
                "pages": bridge_project_pages,
            }
        atomic_write_json(evidence_directory / "envelope.json", envelope)
        return FormalExportResult(
            bridge_url=self.client.base_url,
            window_id=str(target_window),
            identity=before,
            spec=spec,
            artifact_path=artifact,
            artifact_sha256=artifact_sha256,
            artifact_bytes=artifact_bytes,
            inspection=inspection,
            evidence_path=evidence_directory / "envelope.json",
            published_output=published_output,
        )


def inspect_formal_artifact(path: Path, spec: FormalExportSpec) -> dict[str, Any]:
    value = spec.normalized()
    data = path.read_bytes()
    if value.kind == "bom" and value.variant == "xlsx":
        if not data.startswith(b"PK\x03\x04"):
            raise BridgeError("BOM XLSX export has no ZIP/XLSX signature")
        return {"mediaType": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}
    if value.kind == "bom":
        text, encoding = _decode_bom(data)
        first_line = next((line for line in text.splitlines() if line.strip()), "")
        delimiter = "\t" if first_line.count("\t") >= first_line.count(",") else ","
        reader = csv.reader(io.StringIO(text), delimiter=delimiter)
        rows = [row for row in reader if any(cell.strip() for cell in row)]
        if not rows or not any(cell.strip() for cell in rows[0]):
            raise BridgeError("BOM CSV export has no header")
        return {
            "mediaType": "text/csv",
            "encoding": encoding,
            "delimiter": "tab" if delimiter == "\t" else "comma",
            "headers": [cell.strip() for cell in rows[0]],
            "dataRowCount": max(0, len(rows) - 1),
        }
    if value.kind == "netlist" and value.variant == "jlceda":
        try:
            root = json.loads(data.decode("utf-8-sig"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise BridgeError(f"JLCEDA netlist is not valid UTF-8 JSON: {exc}") from exc
        if not isinstance(root, dict) or not isinstance(root.get("components"), (dict, list)):
            raise BridgeError("JLCEDA netlist has no components object or array")
        components = root["components"]
        return {
            "mediaType": "application/json",
            "format": "JLCEDA_PRO",
            "componentCount": len(components),
        }
    if value.kind == "netlist":
        text = data.decode("utf-8-sig", errors="strict")
        if not text.strip():
            raise BridgeError("Protel2 netlist is empty")
        return {"mediaType": "text/plain", "format": "PROTEL2", "characterCount": len(text)}
    if len(data) < 4:
        raise BridgeError("EasyEDA document source artifact is too small")
    return {
        "mediaType": "application/octet-stream",
        "format": value.variant.upper(),
        "signatureHex": data[:8].hex(),
    }


def _decode_bom(data: bytes) -> tuple[str, str]:
    encodings = [("utf-16", "utf-16")] if data.startswith((b"\xff\xfe", b"\xfe\xff")) else [
        ("utf-8-sig", "utf-8-sig"),
        ("utf-16", "utf-16"),
    ]
    for codec, label in encodings:
        try:
            return data.decode(codec), label
        except UnicodeDecodeError:
            continue
    raise BridgeError("Formal BOM encoding is unsupported")


def _validate_output(output_path: str | Path | None, spec: FormalExportSpec) -> Path | None:
    if output_path is None:
        return None
    target = Path(output_path).resolve()
    if target.suffix.lower() != spec.suffix:
        raise ContractError(f"Published {spec.kind}/{spec.variant} output must use {spec.suffix}")
    if target.exists():
        raise ContractError(f"Published formal export already exists: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    return target


def _record_failure(
    evidence_directory: Path,
    registry: dict[str, Any],
    spec: FormalExportSpec,
    identity: Mapping[str, Any] | None,
    started_at: str,
    error: Exception,
) -> None:
    capability = CAPABILITIES[spec.capability_id]
    pre_execution_rejection = isinstance(error, ContractError) and not capability.executable
    safety = {
        "capabilityId": capability.capability_id,
        "capabilityStatus": capability.status,
        "rejectionStage": "CAPABILITY_ADMISSION" if pre_execution_rejection else None,
        "officialCallIssued": False if pre_execution_rejection else None,
        "automaticRetry": False,
    }
    failure = {
        "schemaVersion": "easyeda.gateway.formal-export-failure.v1",
        "status": "FAIL",
        "startedAt": started_at,
        "finishedAt": utc_now(),
        "gatewayVersion": GATEWAY_VERSION,
        "adapterVersion": FORMAL_EXPORT_ADAPTER_VERSION,
        "registry": registry,
        "expectedIdentity": dict(identity or {}),
        "spec": spec.as_dict(),
        "error": {"type": type(error).__name__, "message": str(error)},
        "safety": safety,
    }
    atomic_write_json(evidence_directory / "failure.json", failure)
    files = {
        item.name: sha256_file(item)
        for item in sorted(evidence_directory.iterdir(), key=lambda candidate: candidate.name)
        if item.is_file() and item.name != "envelope.json"
    }
    atomic_write_json(
        evidence_directory / "envelope.json",
        {
            "schemaVersion": FORMAL_EXPORT_EVIDENCE_SCHEMA,
            "status": "FAIL",
            "risk": "READ_WITH_LOCAL_ARTIFACT",
            "startedAt": started_at,
            "finishedAt": failure["finishedAt"],
            "gatewayVersion": GATEWAY_VERSION,
            "adapterVersion": FORMAL_EXPORT_ADAPTER_VERSION,
            "registry": registry,
            "expectedIdentity": dict(identity or {}),
            "spec": spec.as_dict(),
            "error": failure["error"],
            "safety": safety,
            "files": files,
        },
    )
