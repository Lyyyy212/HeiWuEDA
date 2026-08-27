"""Read-only device matching dry-run based on the official standardization plugin."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
import re
from typing import Any, Mapping, Sequence

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
from .version import GATEWAY_VERSION
from .window_guard import resolve_window


DEVICE_MATCH_RESULT_SCHEMA = "easyeda.gateway.device-match-read-result.v1"
DEVICE_MATCH_EVIDENCE_SCHEMA = "easyeda.gateway.device-match-evidence.v1"
DEVICE_MATCH_ADAPTER_VERSION = "1.0.0"
DEVICE_MATCH_SOURCE = {
    "repository": "easyeda/eext-ai-device-standardization",
    "commit": "89abac48075bd4e0ebc2a30bee55939251f8660f",
    "paths": ["iframe/app.js", "src/bom-service.ts"],
    "scoringReference": "iframe/app.js:calcMatchScore",
}
METHOD_IDS = (
    "DMT_Project.getCurrentProjectInfo#1",
    "DMT_SelectControl.getCurrentDocumentInfo#1",
    "SCH_PrimitiveComponent.getAll#1",
    "LIB_Device.search#1",
)
DESIGNATOR_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_.+-]{0,63}$")


@dataclass(frozen=True)
class DeviceMatchSpec:
    designators: tuple[str, ...] = ()
    max_components: int = 25
    max_candidates: int = 5

    def normalized(self) -> "DeviceMatchSpec":
        normalized_designators: list[str] = []
        seen: set[str] = set()
        for raw in self.designators:
            value = str(raw).strip().upper()
            if not DESIGNATOR_RE.fullmatch(value):
                raise ContractError(f"Invalid schematic designator: {raw!r}")
            if value not in seen:
                seen.add(value)
                normalized_designators.append(value)
        if len(normalized_designators) > 128:
            raise ContractError("Device match dry-run accepts at most 128 designators")
        if isinstance(self.max_components, bool) or not 1 <= int(self.max_components) <= 100:
            raise ContractError("max_components must be between 1 and 100")
        if isinstance(self.max_candidates, bool) or not 1 <= int(self.max_candidates) <= 20:
            raise ContractError("max_candidates must be between 1 and 20")
        return DeviceMatchSpec(
            tuple(normalized_designators),
            int(self.max_components),
            int(self.max_candidates),
        )

    def as_dict(self) -> dict[str, Any]:
        value = self.normalized()
        return {
            "designators": list(value.designators),
            "maxComponents": value.max_components,
            "maxCandidates": value.max_candidates,
            "dryRun": True,
        }


@dataclass(frozen=True)
class DeviceMatchResult:
    bridge_url: str
    window_id: str
    identity: dict[str, Any]
    report_path: Path
    report_sha256: str
    component_count: int
    status: str
    evidence_path: Path
    published_output: Path | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "schemaVersion": "easyeda.gateway.device-match-execution.v1",
            "adapterVersion": DEVICE_MATCH_ADAPTER_VERSION,
            "bridgeUrl": self.bridge_url,
            "windowId": self.window_id,
            "identity": self.identity,
            "status": self.status,
            "componentCount": self.component_count,
            "report": {"path": str(self.report_path), "sha256": self.report_sha256},
            "publishedOutput": str(self.published_output) if self.published_output else None,
            "evidencePath": str(self.evidence_path),
        }


class EasyedaDeviceMatchDryRunAdapter:
    """Search official device candidates without creating or modifying any design object."""

    def __init__(self, registry: ApiRegistry, client: BridgeClient):
        self.registry = registry
        self.client = client
        for method_id in METHOD_IDS:
            descriptor = registry.resolve_method(method_id)
            if descriptor.deprecated:
                raise ContractError(f"Device match adapter references deprecated method: {method_id}")

    def build_code(
        self,
        spec: DeviceMatchSpec,
        identity: Mapping[str, Any] | None = None,
    ) -> str:
        value = spec.normalized()
        expected = {
            "projectUuid": (identity or {}).get("projectUuid"),
            "documentUuid": (identity or {}).get("documentUuid"),
            "documentType": 1,
        }
        options = value.as_dict()
        return "\n".join(
            [
                f"const __expected={canonical_json(expected)};",
                f"const __options={canonical_json(options)};",
                "const __readIdentity=async()=>{const project=await eda.dmt_Project.getCurrentProjectInfo();const document=await eda.dmt_SelectControl.getCurrentDocumentInfo();return {projectUuid:project?.uuid??document?.parentProjectUuid??null,documentUuid:document?.uuid??null,documentType:document?.documentType??null,project,document}};",
                "const __assertIdentity=(actual,label)=>{for(const key of ['projectUuid','documentUuid','documentType']){if(__expected[key]!==null&&__expected[key]!==actual[key]){throw new Error(`EasyEDA ${label} identity mismatch for ${key}: expected ${String(__expected[key])}, got ${String(actual[key])}`)}}};",
                "const __before=await __readIdentity();",
                "__assertIdentity(__before,'preflight');",
                "if(__before.documentType!==1){throw new Error(`Device match dry-run requires an active schematic page; got documentType=${String(__before.documentType)}`)}",
                "const __text=value=>value===null||value===undefined?'':String(value).trim();",
                "const __plainRef=value=>value&&typeof value==='object'?{uuid:__text(value.uuid),libraryUuid:__text(value.libraryUuid),name:__text(value.name)}:{uuid:'',libraryUuid:'',name:''};",
                "const __components=await eda.sch_PrimitiveComponent.getAll(undefined,false);",
                "const __wanted=new Set(__options.designators.map(value=>value.toUpperCase()));",
                "const __selected=[];",
                "for(const component of (__components??[])){const designator=__text(component.getState_Designator?.()).toUpperCase();if(!designator||(__wanted.size&&!__wanted.has(designator)))continue;const other=component.getState_OtherProperty?.()??{};const item={primitiveId:__text(component.getState_PrimitiveId?.()),designator,name:__text(component.getState_Name?.()),value:__text(other.Value??other.value??other.Comment??other.comment),component:__plainRef(component.getState_Component?.()),footprint:__plainRef(component.getState_Footprint?.()),manufacturer:__text(component.getState_Manufacturer?.()??other.Manufacturer),manufacturerId:__text(component.getState_ManufacturerId?.()??other['Manufacturer Part']??other.MPN),supplier:__text(component.getState_Supplier?.()??other.Supplier),supplierId:__text(component.getState_SupplierId?.()??other['Supplier Part']??other.LCSC??other['立创编号']),otherProperty:Object.fromEntries(Object.entries(other).slice(0,128).map(([key,value])=>[String(key).slice(0,128),__text(value).slice(0,512)]))};__selected.push(item);if(__selected.length>=__options.maxComponents)break;}",
                "const __items=[];",
                "for(const component of __selected){const queries=[component.manufacturerId,component.supplierId,component.value,component.name,component.component.name].map(__text).filter(Boolean).filter((value,index,array)=>array.findIndex(item=>item.toUpperCase()===value.toUpperCase())===index).slice(0,3);const candidateMap=new Map();const searchErrors=[];for(const query of queries){try{const found=await eda.lib_Device.search(query,undefined,undefined,undefined,Math.max(20,__options.maxCandidates),1);for(const raw of (found??[])){const candidate={name:__text(raw.name),footprintName:__text(raw.footprint?.name??raw.footprintName??raw.package),supplier:__text(raw.supplier),supplierId:__text(raw.supplierId??raw.lcsc),manufacturer:__text(raw.manufacturer),manufacturerId:__text(raw.manufacturerId??raw.mpn),description:__text(raw.description).slice(0,1024),uuid:__text(raw.uuid??raw.targetUuid),libraryUuid:__text(raw.libraryUuid??raw.targetLibraryUuid),symbolUuid:__text(raw.symbol?.uuid??raw.symbolUuid),footprintUuid:__text(raw.footprint?.uuid??raw.footprintUuid),matchedQuery:query};const key=[candidate.uuid,candidate.libraryUuid,candidate.supplierId,candidate.manufacturerId,candidate.name].join('|').toUpperCase();if(!candidateMap.has(key))candidateMap.set(key,candidate);}}catch(error){searchErrors.push({query,error:__text(error?.message??error)});}}__items.push({component,queries,candidates:Array.from(candidateMap.values()).slice(0,__options.maxCandidates*3),searchErrors});}",
                "const __after=await __readIdentity();",
                "__assertIdentity(__after,'postflight');",
                "for(const key of ['projectUuid','documentUuid','documentType']){if(__before[key]!==__after[key]){throw new Error(`EasyEDA identity changed for ${key}`)}}",
                f"return {{schemaVersion:{canonical_json(DEVICE_MATCH_RESULT_SCHEMA)},adapterVersion:{canonical_json(DEVICE_MATCH_ADAPTER_VERSION)},dryRun:true,identityBefore:__before,identityAfter:__after,items:__items,limits:__options}};",
            ],
        )

    def run(
        self,
        spec: DeviceMatchSpec,
        evidence_root: str | Path,
        *,
        output_path: str | Path | None = None,
        identity: Mapping[str, Any] | None = None,
        window_id: str | None = None,
        allow_window_rebind: bool = False,
    ) -> DeviceMatchResult:
        value = spec.normalized()
        published = _validate_output(output_path)
        evidence_directory = create_evidence_directory(evidence_root, "device-match-dry-run")
        report_path = evidence_directory / "device-match-report.json"
        started_at = utc_now()
        code = self.build_code(value, identity)
        request = {
            "schemaVersion": "easyeda.gateway.device-match-request.v1",
            "adapterVersion": DEVICE_MATCH_ADAPTER_VERSION,
            "registry": self.registry.identity,
            "expectedIdentity": dict(identity or {}),
            "spec": value.as_dict(),
            "generatedCodeSha256": hashlib.sha256(code.encode("utf-8")).hexdigest(),
            "methods": list(METHOD_IDS),
            "source": DEVICE_MATCH_SOURCE,
            "risk": "READ",
            "save": False,
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
            response = self.client.execute_code(code, target_window)
            health_after = self.client.health()
            bridge_result = response.get("result")
            if not isinstance(bridge_result, Mapping) or bridge_result.get("schemaVersion") != DEVICE_MATCH_RESULT_SCHEMA:
                raise BridgeError("Device match dry-run returned an invalid result envelope")
            if bridge_result.get("adapterVersion") != DEVICE_MATCH_ADAPTER_VERSION or bridge_result.get("dryRun") is not True:
                raise BridgeError("Device match dry-run adapter identity mismatch")
            before = identity_subset(bridge_result.get("identityBefore"))
            after = identity_subset(bridge_result.get("identityAfter"))
            if before != after or before.get("documentType") != 1:
                raise BridgeError("EasyEDA identity changed or is not a schematic during device matching")
            items = bridge_result.get("items")
            if not isinstance(items, list) or len(items) > value.max_components:
                raise BridgeError("Device match dry-run returned an invalid component list")
            scored_items = [_score_item(item, value.max_candidates) for item in items]
            review_count = sum(
                1
                for item in scored_items
                if not item["candidates"] or item["candidates"][0]["score"] < 85
            )
            search_error_count = sum(len(item["searchErrors"]) for item in scored_items)
            status = "REVIEW_REQUIRED" if review_count or search_error_count else "PASS"
            report = {
                "schemaVersion": "easyeda.gateway.device-match-report.v1",
                "status": status,
                "dryRun": True,
                "generatedAt": utc_now(),
                "identity": before,
                "source": DEVICE_MATCH_SOURCE,
                "scoring": {
                    "model": "official-default-calcMatchScore",
                    "rules": ["exact target/name = 100", "contains target/name = 85", "otherwise = 60"],
                    "targetPriority": ["manufacturerId", "value", "name"],
                },
                "summary": {
                    "componentCount": len(scored_items),
                    "reviewCount": review_count,
                    "searchErrorCount": search_error_count,
                    "designWriteCalls": 0,
                    "designSaveCalls": 0,
                },
                "items": scored_items,
            }
            atomic_write_json(report_path, report)
            report_sha256 = sha256_file(report_path)
            published_output = None
            if published is not None:
                publish_copy_no_overwrite(report_path, published)
                if sha256_file(published) != report_sha256:
                    raise BridgeError("Published device match report digest mismatch")
                published_output = published
            result_record = {
                "bridgeResponse": response,
                "bridgeResponseSha256": sha256_json(response),
                "report": {"path": str(report_path), "sha256": report_sha256},
                "publishedOutput": str(published_output) if published_output else None,
            }
            atomic_write_json(evidence_directory / "result.json", result_record)
            envelope = {
                "schemaVersion": DEVICE_MATCH_EVIDENCE_SCHEMA,
                "status": status,
                "risk": "READ",
                "startedAt": started_at,
                "finishedAt": utc_now(),
                "gatewayVersion": GATEWAY_VERSION,
                "adapterVersion": DEVICE_MATCH_ADAPTER_VERSION,
                "registry": self.registry.identity,
                "identity": before,
                "source": DEVICE_MATCH_SOURCE,
                "bridge": {
                    "service": health_before.get("service"),
                    "url": self.client.base_url,
                    "windowId": target_window,
                    "healthBefore": health_before,
                    "healthAfter": health_after,
                    "windowsBefore": windows_before,
                    "windowResolution": resolution.as_dict(),
                },
                "writeBoundary": {"designWriteCalls": 0, "designSaveCalls": 0},
                "files": {
                    "request.json": sha256_file(evidence_directory / "request.json"),
                    "result.json": sha256_file(evidence_directory / "result.json"),
                    report_path.name: report_sha256,
                },
            }
            if published_output is not None:
                envelope["publishedOutput"] = {"path": str(published_output), "sha256": report_sha256}
            atomic_write_json(evidence_directory / "envelope.json", envelope)
            return DeviceMatchResult(
                bridge_url=self.client.base_url,
                window_id=target_window,
                identity=before,
                report_path=report_path,
                report_sha256=report_sha256,
                component_count=len(scored_items),
                status=status,
                evidence_path=evidence_directory / "envelope.json",
                published_output=published_output,
            )
        except Exception as exc:
            _record_failure(evidence_directory, self.registry.identity, value, identity, started_at, exc)
            raise


def calculate_official_default_score(component: Mapping[str, Any], candidate: Mapping[str, Any]) -> int:
    """Reproduce the official plugin's default calcMatchScore rule."""

    target = _first_text(component.get("manufacturerId"), component.get("value"), component.get("name")).upper()
    device_name = _first_text(candidate.get("name")).upper()
    if not target:
        return 60
    if device_name == target:
        return 100
    if target in device_name or device_name in target:
        return 85
    return 60


def _score_item(item: Any, max_candidates: int) -> dict[str, Any]:
    if not isinstance(item, Mapping) or not isinstance(item.get("component"), Mapping):
        raise BridgeError("Device match result item has no component object")
    component = dict(item["component"])
    raw_candidates = item.get("candidates")
    if not isinstance(raw_candidates, list):
        raise BridgeError(f"Device match candidates are invalid for {component.get('designator')}")
    scored: list[dict[str, Any]] = []
    for raw in raw_candidates:
        if not isinstance(raw, Mapping):
            continue
        candidate = dict(raw)
        score = calculate_official_default_score(component, candidate)
        reasons = _match_reasons(component, candidate)
        scored.append({**candidate, "score": score, "reasons": reasons})
    scored.sort(
        key=lambda candidate: (
            -candidate["score"],
            str(candidate.get("name") or "").casefold(),
            str(candidate.get("supplierId") or "").casefold(),
        ),
    )
    errors = item.get("searchErrors")
    if not isinstance(errors, list):
        errors = []
    queries = item.get("queries") if isinstance(item.get("queries"), list) else []
    return {
        "component": component,
        "queries": [str(query) for query in queries],
        "candidates": scored[:max_candidates],
        "searchErrors": errors,
        "recommendedAction": (
            "REVIEW_AND_BIND_MANUALLY"
            if not scored or scored[0]["score"] < 85
            else "REVIEW_TOP_CANDIDATE"
        ),
    }


def _match_reasons(component: Mapping[str, Any], candidate: Mapping[str, Any]) -> list[str]:
    reasons: list[str] = []
    pairs = (
        ("manufacturer-part", component.get("manufacturerId"), candidate.get("manufacturerId")),
        ("supplier-part", component.get("supplierId"), candidate.get("supplierId")),
        ("footprint", (component.get("footprint") or {}).get("name") if isinstance(component.get("footprint"), Mapping) else None, candidate.get("footprintName")),
        ("manufacturer", component.get("manufacturer"), candidate.get("manufacturer")),
    )
    for label, left, right in pairs:
        left_text = _first_text(left).casefold()
        right_text = _first_text(right).casefold()
        if left_text and right_text and left_text == right_text:
            reasons.append(f"exact-{label}")
    target = _first_text(component.get("manufacturerId"), component.get("value"), component.get("name")).casefold()
    name = _first_text(candidate.get("name")).casefold()
    if target and name:
        if target == name:
            reasons.append("official-exact-target-name")
        elif target in name or name in target:
            reasons.append("official-contains-target-name")
    return reasons


def _first_text(*values: Any) -> str:
    for value in values:
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def _validate_output(output_path: str | Path | None) -> Path | None:
    if output_path is None:
        return None
    target = Path(output_path).resolve()
    if target.suffix.casefold() != ".json":
        raise ContractError("Published device match dry-run report must use .json")
    if target.exists():
        raise ContractError(f"Published device match report already exists: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    return target


def _record_failure(
    evidence_directory: Path,
    registry: dict[str, Any],
    spec: DeviceMatchSpec,
    identity: Mapping[str, Any] | None,
    started_at: str,
    error: Exception,
) -> None:
    try:
        failure = {
            "schemaVersion": "easyeda.gateway.device-match-failure.v1",
            "status": "FAIL",
            "startedAt": started_at,
            "finishedAt": utc_now(),
            "gatewayVersion": GATEWAY_VERSION,
            "adapterVersion": DEVICE_MATCH_ADAPTER_VERSION,
            "registry": registry,
            "expectedIdentity": dict(identity or {}),
            "spec": spec.as_dict(),
            "error": {"type": type(error).__name__, "message": str(error)},
            "writeBoundary": {"designWriteCalls": 0, "designSaveCalls": 0},
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
                "schemaVersion": DEVICE_MATCH_EVIDENCE_SCHEMA,
                "status": "FAIL",
                "risk": "READ",
                "startedAt": started_at,
                "finishedAt": failure["finishedAt"],
                "gatewayVersion": GATEWAY_VERSION,
                "adapterVersion": DEVICE_MATCH_ADAPTER_VERSION,
                "registry": registry,
                "expectedIdentity": dict(identity or {}),
                "spec": spec.as_dict(),
                "error": failure["error"],
                "writeBoundary": failure["writeBoundary"],
                "files": files,
            },
        )
    except OSError:
        pass
