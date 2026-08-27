"""Guarded adapters for source-pinned official EasyEDA example plugins."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
from typing import Any, Mapping
import xml.etree.ElementTree as ET
import zipfile

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
from .export_safety import ExportSafetyController, default_safety_state_path
from .version import GATEWAY_VERSION
from .window_guard import resolve_window


OFFICIAL_PLUGIN_RESULT_SCHEMA = "easyeda.gateway.official-plugin-result.v1"
OFFICIAL_PLUGIN_EVIDENCE_SCHEMA = "easyeda.gateway.official-plugin-evidence.v1"
OFFICIAL_PLUGIN_ADAPTER_VERSION = "1.0.0"
IDENTITY_METHOD_IDS = (
    "DMT_Project.getCurrentProjectInfo#1",
    "DMT_SelectControl.getCurrentDocumentInfo#1",
)
LOCAL_SAVE_METHOD_ID = "SYS_FileSystem.saveFileToFileSystem#1"


@dataclass(frozen=True)
class OfficialPluginDefinition:
    kind: str
    capability_id: str
    artifact_name: str
    bundle_name: str
    bundle_global: str
    bundle_sha256: str
    source_repository: str
    source_commit: str
    source_path: str
    method_ids: tuple[str, ...]
    intercepted_method_ids: tuple[str, ...]


DEFINITIONS = {
    "dfm": OfficialPluginDefinition(
        kind="dfm",
        capability_id="pcb.dfm-report",
        artifact_name="official-pcb-dfm-report.json",
        bundle_name="dfm-checker.min.js",
        bundle_global="EasyedaOfficialDfm",
        bundle_sha256="0796c3afcea83a8e8ecf40d694b7d99df0565d75591d7e216cc61a9f40aca112",
        source_repository="easyeda/eext-jlc-order-dfm-checker",
        source_commit="afd538786d510f537ad4fa47c6329e6a99dc7625",
        source_path="src/index.ts",
        method_ids=(
            "PCB_Layer.getTheNumberOfCopperLayers#1",
            "PCB_MathPolygon.discretize#1",
            "PCB_Net.getAllNetsName#1",
            "PCB_Net.getAllPrimitivesByNet#1",
            "PCB_Primitive.getPrimitivesBBox#1",
            "PCB_PrimitiveArc.getAll#1",
            "PCB_PrimitiveAttribute.getAll#1",
            "PCB_PrimitiveComponent.getAll#1",
            "PCB_PrimitiveFill.getAll#1",
            "PCB_PrimitiveLine.getAll#1",
            "PCB_PrimitiveLine.getAllPrimitiveId#1",
            "PCB_PrimitivePad.getAll#1",
            "PCB_PrimitivePad.getAllPrimitiveId#1",
            "PCB_PrimitivePolyline.getAll#1",
            "PCB_PrimitivePour.getAll#1",
            "PCB_PrimitivePoured.getAll#1",
            "PCB_PrimitiveString.getAll#1",
            "PCB_PrimitiveString.getAllPrimitiveId#1",
            "PCB_PrimitiveVia.getAll#1",
            "PCB_PrimitiveVia.getAllPrimitiveId#1",
            "SYS_FileManager.getDocumentSource#1",
            "SYS_Unit.milToMm#1",
            "SYS_Unit.mmToMil#1",
        ),
        intercepted_method_ids=(
            "SYS_Storage.setExtensionUserConfig#1",
            "SYS_Log.clear#1",
            "SYS_Log.add#1",
            "SYS_PanelControl.openBottomPanel#1",
            "SYS_IFrame.openIFrame#1",
        ),
    ),
    "manufacturing-svg": OfficialPluginDefinition(
        kind="manufacturing-svg",
        capability_id="pcb.manufacturing-svg",
        artifact_name="official-manufacturing-svg.zip",
        bundle_name="manufacturing-svg.min.js",
        bundle_global="EasyedaOfficialManufacturingSvg",
        bundle_sha256="19cb25ef5d878f73fb5d630e823d3bc734ce493c5b40f4cceb1e43a15a7a725c",
        source_repository="easyeda/eext-export-pcb-to-svg",
        source_commit="f68898d18c8279e2aaf84a5b2ff07969ebeb005e",
        source_path="src/index.ts",
        method_ids=(
            "DMT_Board.getCurrentBoardInfo#1",
            "PCB_Document.getPrimitiveAtPoint#1",
            "PCB_Layer.getAllLayers#1",
            "PCB_ManufactureData.getGerberFile#1",
            "PCB_PrimitivePour.getAll#1",
        ),
        intercepted_method_ids=(
            "SYS_FileSystem.saveFile#1",
            "SYS_Message.showToastMessage#1",
            "SYS_Dialog.showInformationMessage#1",
        ),
    ),
    "gencad": OfficialPluginDefinition(
        kind="gencad",
        capability_id="pcb.gencad",
        artifact_name="official-board-gencad.cad",
        bundle_name="gencad-export.min.js",
        bundle_global="EasyedaOfficialGencad",
        bundle_sha256="91de722f3b61610ddd59593948003e8c909c0ff5e31a6b4d97fced450d45176d",
        source_repository="easyeda/eext-export-gencad",
        source_commit="aba4dff5b0fb8e1c5ad8288b07eb56b01dd0ab9e",
        source_path="src/index.ts",
        method_ids=(
            "PCB_Layer.getAllLayers#1",
            "PCB_Layer.getTheNumberOfCopperLayers#1",
            "PCB_Net.getAllNetsName#1",
            "PCB_PrimitiveArc.getAll#1",
            "PCB_PrimitiveAttribute.getAll#1",
            "PCB_PrimitiveComponent.getAll#1",
            "PCB_PrimitiveLine.getAll#1",
            "PCB_PrimitivePad.getAll#1",
            "PCB_PrimitivePolyline.getAll#1",
            "PCB_PrimitiveVia.getAll#1",
            "SYS_FileManager.getFootprintFileByFootprintUuid#1",
        ),
        intercepted_method_ids=(
            "SYS_FileSystem.saveFile#1",
            "SYS_Message.showToastMessage#1",
            "SYS_Dialog.showInformationMessage#1",
        ),
    ),
}
SUPPORTED_MATERIALS = ("FR4", "HDI板", "高频板", "铝基板", "铜基板")


@dataclass(frozen=True)
class OfficialPluginSpec:
    kind: str
    material: str = "FR4"
    thickness_mm: float = 1.6

    def normalized(self) -> "OfficialPluginSpec":
        kind = self.kind.strip().lower()
        if kind not in DEFINITIONS:
            raise ContractError(f"Unsupported official plugin kind: {self.kind}")
        material = self.material.strip()
        if material not in SUPPORTED_MATERIALS:
            raise ContractError(f"Unsupported JLC PCB material: {self.material}")
        try:
            thickness = float(self.thickness_mm)
        except (TypeError, ValueError) as exc:
            raise ContractError("PCB thickness must be numeric") from exc
        if not 0.05 <= thickness <= 20:
            raise ContractError("PCB thickness must be between 0.05 and 20 mm")
        return OfficialPluginSpec(kind, material, thickness)

    @property
    def definition(self) -> OfficialPluginDefinition:
        return DEFINITIONS[self.normalized().kind]

    def as_dict(self) -> dict[str, Any]:
        value = self.normalized()
        definition = DEFINITIONS[value.kind]
        result: dict[str, Any] = {
            "kind": value.kind,
            "capabilityId": definition.capability_id,
        }
        if value.kind == "dfm":
            result.update({"material": value.material, "thicknessMm": value.thickness_mm})
        return result


@dataclass(frozen=True)
class OfficialPluginResult:
    bridge_url: str
    window_id: str
    identity: dict[str, Any]
    spec: OfficialPluginSpec
    artifact_path: Path
    artifact_sha256: str
    artifact_bytes: int
    inspection: dict[str, Any]
    evidence_path: Path
    published_output: Path | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "schemaVersion": "easyeda.gateway.official-plugin-execution.v1",
            "adapterVersion": OFFICIAL_PLUGIN_ADAPTER_VERSION,
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


class EasyedaOfficialPluginAdapter:
    """Execute exactly one source-pinned official plugin export per request."""

    def __init__(self, registry: ApiRegistry, client: BridgeClient):
        self.registry = registry
        self.client = client
        self.runtime_root = Path(__file__).resolve().parent / "official_runtime"
        self._validate_contract()

    def _validate_contract(self) -> None:
        method_ids = {
            *IDENTITY_METHOD_IDS,
            LOCAL_SAVE_METHOD_ID,
            *(method for definition in DEFINITIONS.values() for method in definition.method_ids),
            *(method for definition in DEFINITIONS.values() for method in definition.intercepted_method_ids),
        }
        for method_id in sorted(method_ids):
            descriptor = self.registry.resolve_method(method_id)
            if descriptor.deprecated:
                raise ContractError(f"Official plugin adapter references deprecated method: {method_id}")
        for definition in DEFINITIONS.values():
            self._load_bundle(definition)

    def _load_bundle(self, definition: OfficialPluginDefinition) -> str:
        path = self.runtime_root / definition.bundle_name
        if not path.is_file():
            raise ContractError(f"Pinned official plugin bundle is missing: {path}")
        digest = sha256_file(path)
        if digest != definition.bundle_sha256:
            raise ContractError(
                f"Pinned official plugin bundle digest mismatch for {definition.kind}: {digest}",
            )
        return path.read_text(encoding="utf-8")

    def build_code(
        self,
        spec: OfficialPluginSpec,
        artifact_path: str | Path,
        identity: Mapping[str, Any] | None = None,
    ) -> str:
        value = spec.normalized()
        definition = DEFINITIONS[value.kind]
        target = Path(artifact_path).resolve()
        expected_suffix = Path(definition.artifact_name).suffix.casefold()
        if target.suffix.casefold() != expected_suffix:
            raise ContractError(f"{value.kind} output must use {expected_suffix}")
        expected = {
            "projectUuid": (identity or {}).get("projectUuid"),
            "documentUuid": (identity or {}).get("documentUuid"),
            "documentType": 3,
        }
        bundle = self._load_bundle(definition)
        plugin_prelude, plugin_call = _build_plugin_parts(value, definition)
        return "\n".join(
            [
                f"const __artifactPath={canonical_json(str(target))};",
                f"const __expected={canonical_json(expected)};",
                "const __realEda=eda;",
                "const __readIdentity=async()=>{const project=await __realEda.dmt_Project.getCurrentProjectInfo();const document=await __realEda.dmt_SelectControl.getCurrentDocumentInfo();return {projectUuid:project?.uuid??document?.parentProjectUuid??null,documentUuid:document?.uuid??null,documentType:document?.documentType??null,project,document}};",
                "const __assertIdentity=(actual,label)=>{for(const key of ['projectUuid','documentUuid','documentType']){if(__expected[key]!==null&&__expected[key]!==actual[key]){throw new Error(`EasyEDA ${label} identity mismatch for ${key}: expected ${String(__expected[key])}, got ${String(actual[key])}`)}}};",
                "const __before=await __readIdentity();",
                "__assertIdentity(__before,'preflight');",
                "const __pluginResult=await (async(__pluginRealEda)=>{",
                plugin_prelude,
                "const eda=__safeEda;",
                bundle,
                plugin_call,
                "})(__realEda);",
                "const __after=await __readIdentity();",
                "__assertIdentity(__after,'postflight');",
                "for(const key of ['projectUuid','documentUuid','documentType']){if(__before[key]!==__after[key]){throw new Error(`EasyEDA identity changed for ${key}`)}}",
                f"return {{schemaVersion:{canonical_json(OFFICIAL_PLUGIN_RESULT_SCHEMA)},adapterVersion:{canonical_json(OFFICIAL_PLUGIN_ADAPTER_VERSION)},kind:{canonical_json(value.kind)},saved:true,identityBefore:__before,identityAfter:__after,plugin:__pluginResult}};",
            ],
        )

    def export(
        self,
        spec: OfficialPluginSpec,
        evidence_root: str | Path,
        *,
        output_path: str | Path | None = None,
        identity: Mapping[str, Any] | None = None,
        window_id: str | None = None,
        safety_state_path: str | Path | None = None,
        allow_window_rebind: bool = False,
    ) -> OfficialPluginResult:
        value = spec.normalized()
        definition = DEFINITIONS[value.kind]
        published = _validate_output(output_path, definition)
        evidence_directory = create_evidence_directory(evidence_root, definition.capability_id.replace(".", "-"))
        artifact = evidence_directory / definition.artifact_name
        safety_path = (
            Path(safety_state_path).resolve()
            if safety_state_path
            else default_safety_state_path(evidence_root)
        )
        code = self.build_code(value, artifact, identity)
        started_at = utc_now()
        request = {
            "schemaVersion": "easyeda.gateway.official-plugin-request.v1",
            "adapterVersion": OFFICIAL_PLUGIN_ADAPTER_VERSION,
            "registry": self.registry.identity,
            "expectedIdentity": dict(identity or {}),
            "spec": value.as_dict(),
            "artifactPath": str(artifact),
            "safetyStatePath": str(safety_path),
            "generatedCodeSha256": hashlib.sha256(code.encode("utf-8")).hexdigest(),
            "officialSource": _source_record(definition),
            "methods": [*IDENTITY_METHOD_IDS, *definition.method_ids, LOCAL_SAVE_METHOD_ID],
            "interceptedMethods": list(definition.intercepted_method_ids),
            "executionModel": "ONE_SOURCE_PINNED_PLUGIN_CALL_PER_BRIDGE_REQUEST",
            "automaticRetry": False,
        }
        atomic_write_json(evidence_directory / "request.json", request)
        try:
            health_before = self.client.health()
            windows_before = self.client.windows()
            resolution = resolve_window(
                windows_before,
                requested_window_id=window_id,
                identity=identity,
                allow_rebind=allow_window_rebind,
            )
            target_window = str(resolution.resolved_window_id)
            safety = ExportSafetyController(safety_path)
            safety.acquire(definition.capability_id, self.client, target_window)
            try:
                response = self.client.execute_code(code, target_window)
                health_after = self.client.health()
            except Exception as exc:
                safety.finish(success=False, error=exc)
                raise
            else:
                safety.finish(success=True)
            result = response.get("result")
            if not isinstance(result, Mapping) or result.get("schemaVersion") != OFFICIAL_PLUGIN_RESULT_SCHEMA:
                raise BridgeError("Official plugin returned an invalid result envelope")
            if result.get("adapterVersion") != OFFICIAL_PLUGIN_ADAPTER_VERSION:
                raise BridgeError("Official plugin adapter version mismatch")
            if result.get("kind") != value.kind or result.get("saved") is not True:
                raise BridgeError("Official plugin kind or saved status mismatch")
            before = identity_subset(result.get("identityBefore"))
            after = identity_subset(result.get("identityAfter"))
            if before != after or before.get("documentType") != 3:
                raise BridgeError("EasyEDA identity changed or is not a PCB during official plugin execution")
            if not artifact.is_file() or artifact.stat().st_size <= 0:
                raise BridgeError(f"Official plugin artifact was not written: {artifact}")
            inspection = inspect_official_plugin_artifact(artifact, value)
            artifact_sha256 = sha256_file(artifact)
            published_output = None
            if published is not None:
                publish_copy_no_overwrite(artifact, published)
                if sha256_file(published) != artifact_sha256:
                    raise BridgeError("Published official plugin artifact digest mismatch")
                published_output = published
            result_record = {
                "bridgeResponse": response,
                "bridgeResponseSha256": sha256_json(response),
                "artifact": {
                    "path": str(artifact),
                    "sha256": artifact_sha256,
                    "bytes": artifact.stat().st_size,
                    **inspection,
                },
                "officialSource": _source_record(definition),
                "publishedOutput": str(published_output) if published_output else None,
            }
            atomic_write_json(evidence_directory / "result.json", result_record)
            envelope = {
                "schemaVersion": OFFICIAL_PLUGIN_EVIDENCE_SCHEMA,
                "status": inspection.get("status", "PASS"),
                "risk": "READ_WITH_LOCAL_ARTIFACT",
                "startedAt": started_at,
                "finishedAt": utc_now(),
                "gatewayVersion": GATEWAY_VERSION,
                "adapterVersion": OFFICIAL_PLUGIN_ADAPTER_VERSION,
                "registry": self.registry.identity,
                "identity": before,
                "officialSource": _source_record(definition),
                "bridge": {
                    "service": health_before.get("service"),
                    "url": self.client.base_url,
                    "windowId": target_window,
                    "healthBefore": health_before,
                    "healthAfter": health_after,
                    "windowsBefore": windows_before,
                    "windowResolution": resolution.as_dict(),
                },
                "safety": {
                    "capabilityId": definition.capability_id,
                    "statePath": str(safety_path),
                    "executionModel": "ONE_SOURCE_PINNED_PLUGIN_CALL_PER_BRIDGE_REQUEST",
                    "automaticRetry": False,
                },
                "files": {
                    "request.json": sha256_file(evidence_directory / "request.json"),
                    "result.json": sha256_file(evidence_directory / "result.json"),
                    artifact.name: artifact_sha256,
                },
                "inspection": inspection,
            }
            if published_output is not None:
                envelope["publishedOutput"] = {"path": str(published_output), "sha256": artifact_sha256}
            atomic_write_json(evidence_directory / "envelope.json", envelope)
            return OfficialPluginResult(
                bridge_url=self.client.base_url,
                window_id=target_window,
                identity=before,
                spec=value,
                artifact_path=artifact,
                artifact_sha256=artifact_sha256,
                artifact_bytes=artifact.stat().st_size,
                inspection=inspection,
                evidence_path=evidence_directory / "envelope.json",
                published_output=published_output,
            )
        except Exception as exc:
            _record_failure(evidence_directory, self.registry.identity, value, identity, started_at, exc)
            raise


def _build_plugin_parts(
    spec: OfficialPluginSpec,
    definition: OfficialPluginDefinition,
) -> tuple[str, str]:
    common = [
        "const __module=(base,overrides)=>new Proxy(base??{},{get:(target,key)=>Object.prototype.hasOwnProperty.call(overrides,key)?overrides[key]:Reflect.get(target,key)});",
        "let __captureCount=0;",
        "let __captureMeta=null;",
        "let __dialogMessages=[];",
    ]
    if spec.kind == "dfm":
        common.extend(
            [
                "const ESYS_LogType=Object.freeze({INFO:'info',WARNING:'warn',ERROR:'error',FATAL_ERROR:'fatalError',FIND:'find',REPLACE:'replace',OPEN_PROJECT:'openProject'});",
                "const ESYS_BottomPanelTab=Object.freeze({LIBRARY:'library',LOG:'log',PCB_DRC:'drcResult',SCHEMATIC_DRC:'schDrcResult',FIND:'findResult'});",
                "const EPCB_LayerId=Object.freeze({BOARD_OUTLINE:11,MULTI:12});",
                "let __report=null;",
                "const __safeStorage=__module(__pluginRealEda.sys_Storage,{setExtensionUserConfig:async(key,value)=>{if(key!=='pcbDfmReportData'){throw new Error(`Unexpected DFM storage key: ${String(key)}`)}__captureCount++;__report=JSON.parse(JSON.stringify(value));return true;}});",
                "const __safeLog=__module(__pluginRealEda.sys_Log,{clear:()=>undefined,add:()=>undefined});",
                "const __safePanel=__module(__pluginRealEda.sys_PanelControl,{openBottomPanel:()=>undefined});",
                "const __safeIFrame=__module(__pluginRealEda.sys_IFrame,{openIFrame:()=>false,closeIFrame:async()=>false});",
                "const __safeEda=new Proxy(Object.create(null),{get:(local,key)=>Object.prototype.hasOwnProperty.call(local,key)?local[key]:key==='sys_Storage'?__safeStorage:key==='sys_Log'?__safeLog:key==='sys_PanelControl'?__safePanel:key==='sys_IFrame'?__safeIFrame:Reflect.get(__pluginRealEda,key),set:(local,key,value)=>{local[key]=value;return true;}});",
            ],
        )
        call = "\n".join(
            [
                f"await {definition.bundle_global}.pcbDfmWithMaterial({canonical_json(spec.material)},{canonical_json(spec.thickness_mm)});",
                "if(__captureCount!==1||!__report?.result||!Array.isArray(__report.result.results)){throw new Error(`Official DFM result capture count is ${__captureCount}`)}",
                "const __blob=new Blob([JSON.stringify(__report,null,2)+'\\n'],{type:'application/json'});",
                "const __saved=await __pluginRealEda.sys_FileSystem.saveFileToFileSystem(__artifactPath,__blob,undefined,false);",
                "if(__saved!==true){throw new Error('Official DFM report local save failed')}",
                "return {captureCount:__captureCount,artifact:{size:__blob.size,type:__blob.type},summary:{checkCount:__report.result.results.length,errorCount:__report.result.errorCount,warningCount:__report.result.warningCount,passed:__report.result.passed}};",
            ],
        )
        return "\n".join(common), call
    function_name = (
        "exportCurrentBoardToSvg" if spec.kind == "manufacturing-svg" else "exportGencad"
    )
    common.extend(
        [
            "const __safeFileSystem=__module(__pluginRealEda.sys_FileSystem,{saveFile:async(blob,name)=>{if(__captureCount!==0){throw new Error('Official plugin attempted multiple artifact saves')}if(!(blob instanceof Blob)){throw new Error('Official plugin produced a non-Blob artifact')}__captureCount++;__captureMeta={name:String(name??''),size:blob.size,type:blob.type};const saved=await __pluginRealEda.sys_FileSystem.saveFileToFileSystem(__artifactPath,blob,undefined,false);if(saved!==true){throw new Error('Official plugin local save failed')}return true;}});",
            "const __safeMessage=__module(__pluginRealEda.sys_Message,{showToastMessage:()=>undefined});",
            "const __safeDialog=__module(__pluginRealEda.sys_Dialog,{showInformationMessage:(...args)=>{__dialogMessages.push(args.map(value=>String(value)).join(' | '));return undefined;}});",
            "const __safeIFrame=__module(__pluginRealEda.sys_IFrame,{openIFrame:async()=>false,closeIFrame:async()=>false});",
            "const __safeEda=new Proxy(Object.create(null),{get:(local,key)=>Object.prototype.hasOwnProperty.call(local,key)?local[key]:key==='sys_FileSystem'?__safeFileSystem:key==='sys_Message'?__safeMessage:key==='sys_Dialog'?__safeDialog:key==='sys_IFrame'?__safeIFrame:Reflect.get(__pluginRealEda,key),set:(local,key,value)=>{local[key]=value;return true;}});",
        ],
    )
    call = "\n".join(
        [
            f"await {definition.bundle_global}.{function_name}();",
            "if(__captureCount!==1){throw new Error(`Official plugin did not produce exactly one artifact; captureCount=${__captureCount}; dialogs=${__dialogMessages.join(' / ')}`)}",
            "return {captureCount:__captureCount,artifact:__captureMeta,dialogMessages:__dialogMessages};",
        ],
    )
    return "\n".join(common), call


def inspect_official_plugin_artifact(path: Path, spec: OfficialPluginSpec) -> dict[str, Any]:
    value = spec.normalized()
    if value.kind == "dfm":
        return _inspect_dfm(path)
    if value.kind == "manufacturing-svg":
        return _inspect_svg_zip(path)
    return _inspect_gencad(path)


def _inspect_dfm(path: Path) -> dict[str, Any]:
    try:
        root = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BridgeError(f"Official DFM report is not valid UTF-8 JSON: {exc}") from exc
    result = root.get("result") if isinstance(root, dict) else None
    rows = result.get("results") if isinstance(result, dict) else None
    if not isinstance(rows, list) or len(rows) != 18:
        raise BridgeError(f"Official DFM report must contain exactly 18 checks, got {len(rows) if isinstance(rows, list) else 'invalid'}")
    statuses: list[str] = []
    numbers: list[int] = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise BridgeError(f"Official DFM check {index + 1} is not an object")
        status = row.get("result")
        if status not in {"success", "warning", "error"}:
            raise BridgeError(f"Official DFM check {index + 1} has invalid status {status!r}")
        statuses.append(status)
        numbers.append(row.get("number"))
    if numbers != list(range(1, 19)):
        raise BridgeError(f"Official DFM check numbers are not 1..18: {numbers}")
    error_count = statuses.count("error")
    warning_count = statuses.count("warning")
    if result.get("errorCount") != error_count or result.get("warningCount") != warning_count:
        raise BridgeError("Official DFM summary counts do not match the 18 result rows")
    status = "BLOCKED_BY_DFM" if error_count else "REVIEW_REQUIRED" if warning_count else "PASS"
    return {
        "mediaType": "application/json",
        "format": "JLC_OFFICIAL_PCB_DFM",
        "status": status,
        "checkCount": 18,
        "errorCount": error_count,
        "warningCount": warning_count,
        "passedCount": statuses.count("success"),
        "fabricationApproval": False,
        "note": "A zero-error DFM result is not fabrication approval.",
    }


def _inspect_svg_zip(path: Path) -> dict[str, Any]:
    try:
        archive = zipfile.ZipFile(path)
    except (OSError, zipfile.BadZipFile) as exc:
        raise BridgeError(f"Official manufacturing SVG artifact is not a valid ZIP: {exc}") from exc
    with archive:
        infos = archive.infolist()
        if not infos or len(infos) > 512:
            raise BridgeError("Official manufacturing SVG ZIP has an invalid entry count")
        total_uncompressed = sum(info.file_size for info in infos)
        if total_uncompressed > 256 * 1024 * 1024:
            raise BridgeError("Official manufacturing SVG ZIP exceeds the 256 MiB inspection limit")
        names: list[str] = []
        svg_names: list[str] = []
        for info in infos:
            pure = PurePosixPath(info.filename.replace("\\", "/"))
            if pure.is_absolute() or ".." in pure.parts:
                raise BridgeError(f"Official manufacturing SVG ZIP contains an unsafe path: {info.filename}")
            if info.is_dir():
                continue
            names.append(pure.as_posix())
            if pure.suffix.casefold() == ".svg":
                svg_names.append(pure.as_posix())
                try:
                    root = ET.fromstring(archive.read(info))
                except (ET.ParseError, OSError, RuntimeError) as exc:
                    raise BridgeError(f"Invalid SVG XML in {info.filename}: {exc}") from exc
                if root.tag.rsplit("}", 1)[-1].casefold() != "svg":
                    raise BridgeError(f"ZIP entry is not an SVG root document: {info.filename}")
        if not svg_names:
            raise BridgeError("Official manufacturing SVG ZIP contains no SVG files")
        return {
            "mediaType": "application/zip",
            "format": "JLC_OFFICIAL_MANUFACTURING_SVG",
            "status": "PASS",
            "fileCount": len(names),
            "svgCount": len(svg_names),
            "uncompressedBytes": total_uncompressed,
            "entries": names,
            "svgEntries": svg_names,
        }


def _inspect_gencad(path: Path) -> dict[str, Any]:
    try:
        text = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError) as exc:
        raise BridgeError(f"Official GenCAD artifact is not valid UTF-8 text: {exc}") from exc
    required = ("$HEADER", "$ENDHEADER", "$BOARD", "$ENDBOARD", "$COMPONENTS", "$ENDCOMPONENTS", "$SIGNALS", "$ENDSIGNALS", "$END")
    missing = [section for section in required if section not in text]
    if missing:
        raise BridgeError(f"Official GenCAD artifact is missing sections: {missing}")
    component_count = len(re.findall(r'^COMPONENT\s+"', text, flags=re.MULTILINE))
    signal_count = len(re.findall(r'^SIGNAL\s+"', text, flags=re.MULTILINE))
    return {
        "mediaType": "text/plain",
        "format": "GENCAD_1_4",
        "status": "PASS",
        "characterCount": len(text),
        "componentCount": component_count,
        "signalCount": signal_count,
        "sections": list(required),
    }


def _source_record(definition: OfficialPluginDefinition) -> dict[str, str]:
    return {
        "repository": definition.source_repository,
        "commit": definition.source_commit,
        "path": definition.source_path,
        "bundle": definition.bundle_name,
        "bundleSha256": definition.bundle_sha256,
    }


def _validate_output(
    output_path: str | Path | None,
    definition: OfficialPluginDefinition,
) -> Path | None:
    if output_path is None:
        return None
    target = Path(output_path).resolve()
    expected_suffix = Path(definition.artifact_name).suffix.casefold()
    if target.suffix.casefold() != expected_suffix:
        raise ContractError(f"Published {definition.kind} output must use {expected_suffix}")
    if target.exists():
        raise ContractError(f"Published official plugin artifact already exists: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    return target


def _record_failure(
    evidence_directory: Path,
    registry: dict[str, Any],
    spec: OfficialPluginSpec,
    identity: Mapping[str, Any] | None,
    started_at: str,
    error: Exception,
) -> None:
    try:
        failure = {
            "schemaVersion": "easyeda.gateway.official-plugin-failure.v1",
            "status": "FAIL",
            "startedAt": started_at,
            "finishedAt": utc_now(),
            "gatewayVersion": GATEWAY_VERSION,
            "adapterVersion": OFFICIAL_PLUGIN_ADAPTER_VERSION,
            "registry": registry,
            "expectedIdentity": dict(identity or {}),
            "spec": spec.as_dict(),
            "error": {"type": type(error).__name__, "message": str(error)},
            "automaticRetry": False,
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
                "schemaVersion": OFFICIAL_PLUGIN_EVIDENCE_SCHEMA,
                "status": "FAIL",
                "risk": "READ_WITH_LOCAL_ARTIFACT",
                "startedAt": started_at,
                "finishedAt": failure["finishedAt"],
                "gatewayVersion": GATEWAY_VERSION,
                "adapterVersion": OFFICIAL_PLUGIN_ADAPTER_VERSION,
                "registry": registry,
                "expectedIdentity": dict(identity or {}),
                "spec": spec.as_dict(),
                "error": failure["error"],
                "automaticRetry": False,
                "files": files,
            },
        )
    except OSError:
        pass
