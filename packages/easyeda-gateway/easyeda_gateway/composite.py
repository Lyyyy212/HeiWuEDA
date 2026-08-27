"""Fixed composite reads migrated from audited official EasyEDA extensions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Callable, Mapping
from uuid import uuid4

from .client import BridgeClient
from .contract import ApiRegistry, canonical_json, classify_method_effect, sha256_json
from .errors import BridgeError, ContractError
from .version import GATEWAY_VERSION
from .window_guard import resolve_window


COMPOSITE_RESULT_SCHEMA = "easyeda.gateway.composite-read-result.v1"
COMPOSITE_EVIDENCE_SCHEMA = "easyeda.gateway.composite-read-evidence.v1"


@dataclass(frozen=True)
class TrustedReadTemplate:
    template_id: str
    version: str
    document_type: int
    method_ids: tuple[str, ...]
    body: str
    source_repository: str
    source_commit: str
    source_paths: tuple[str, ...]
    additional_sources: tuple[dict[str, Any], ...] = ()

    @property
    def digest(self) -> str:
        return sha256_json(
            {
                "templateId": self.template_id,
                "version": self.version,
                "documentType": self.document_type,
                "methodIds": self.method_ids,
                "body": self.body,
                "sourceRepository": self.source_repository,
                "sourceCommit": self.source_commit,
                "sourcePaths": self.source_paths,
                "additionalSources": self.additional_sources,
            },
        )


@dataclass(frozen=True)
class CompositeReadResult:
    template_id: str
    template_digest: str
    bridge_url: str
    window_id: str
    identity: dict[str, Any]
    payload: Any
    derived: Any
    evidence_path: Path

    def as_dict(self) -> dict[str, Any]:
        return {
            "schemaVersion": "easyeda.gateway.composite-read-execution.v1",
            "templateId": self.template_id,
            "templateDigest": self.template_digest,
            "bridgeUrl": self.bridge_url,
            "windowId": self.window_id,
            "identity": self.identity,
            "payload": self.payload,
            "derived": self.derived,
            "evidencePath": str(self.evidence_path),
        }


class CompositeReadExecutor:
    """Execute only named, source-pinned read templates; arbitrary code is never accepted."""

    def __init__(self, registry: ApiRegistry, client: BridgeClient):
        self.registry = registry
        self.client = client

    def template(self, template_id: str) -> TrustedReadTemplate:
        try:
            template = TRUSTED_READ_TEMPLATES[template_id]
        except KeyError as exc:
            raise ContractError(f"Unknown trusted read template: {template_id}") from exc
        for method_id in template.method_ids:
            descriptor = self.registry.resolve_method(method_id)
            if descriptor.deprecated:
                raise ContractError(f"Trusted template references deprecated method: {method_id}")
            if classify_method_effect(descriptor.method_name) != "READ":
                raise ContractError(f"Trusted read template references a non-read method: {method_id}")
        return template

    def build_code(self, template_id: str, identity: Mapping[str, Any] | None = None) -> str:
        template = self.template(template_id)
        expected = {
            "projectUuid": (identity or {}).get("projectUuid"),
            "documentUuid": (identity or {}).get("documentUuid"),
            "documentType": template.document_type,
        }
        statements = [
            "const __readIdentity=async()=>{const project=await eda.dmt_Project.getCurrentProjectInfo();const document=await eda.dmt_SelectControl.getCurrentDocumentInfo();return {projectUuid:project?.uuid??document?.parentProjectUuid??null,documentUuid:document?.uuid??null,documentType:document?.documentType??null,project,document}}",
            f"const __expected={canonical_json(expected)}",
            "const __before=await __readIdentity()",
            "for(const key of ['projectUuid','documentUuid','documentType']){if(__expected[key]!==null&&__expected[key]!==__before[key]){throw new Error(`EasyEDA identity mismatch for ${key}: expected ${String(__expected[key])}, got ${String(__before[key])}`)}}",
            template.body,
            "const __after=await __readIdentity()",
            "for(const key of ['projectUuid','documentUuid','documentType']){if(__before[key]!==__after[key]){throw new Error(`EasyEDA identity changed during composite read for ${key}`)}}",
            f"return {{schemaVersion:'{COMPOSITE_RESULT_SCHEMA}',templateId:'{template.template_id}',templateVersion:'{template.version}',identityBefore:__before,identityAfter:__after,payload:__payload}}",
        ]
        code = ";".join(statements) + ";"
        if "//" in code or "/*" in code:
            raise ContractError("Trusted template compilation produced a JavaScript comment")
        return code

    def execute(
        self,
        template_id: str,
        evidence_root: str | Path,
        *,
        identity: Mapping[str, Any] | None = None,
        window_id: str | None = None,
        postprocess: Callable[[Any], Any] | None = None,
        allow_window_rebind: bool = False,
    ) -> CompositeReadResult:
        template = self.template(template_id)
        code = self.build_code(template_id, identity)
        health_before = self.client.health()
        windows_before = self.client.windows()
        window_resolution = resolve_window(
            windows_before,
            requested_window_id=window_id,
            identity=identity,
            allow_rebind=allow_window_rebind,
        )
        target_window = window_resolution.resolved_window_id
        started_at = _utc_now()
        response = self.client.execute_code(code, str(target_window))
        finished_at = _utc_now()
        health_after = self.client.health()
        result = response.get("result")
        if not isinstance(result, Mapping) or result.get("schemaVersion") != COMPOSITE_RESULT_SCHEMA:
            raise BridgeError("Trusted composite read returned an invalid result envelope")
        if result.get("templateId") != template.template_id or result.get("templateVersion") != template.version:
            raise BridgeError("Trusted composite read template identity mismatch")
        before = _identity_subset(result.get("identityBefore"))
        after = _identity_subset(result.get("identityAfter"))
        if before != after:
            raise BridgeError("EasyEDA identity drifted during trusted composite read")
        if before.get("documentType") != template.document_type:
            raise BridgeError(
                f"Template {template.template_id} requires documentType={template.document_type}, got {before.get('documentType')!r}",
            )
        payload = result.get("payload")
        derived = postprocess(payload) if postprocess else None
        evidence = self._record_evidence(
            evidence_root=Path(evidence_root),
            template=template,
            identity=dict(identity or {}),
            code=code,
            response=response,
            derived=derived,
            health_before=health_before,
            health_after=health_after,
            windows_before=windows_before,
            target_window=str(target_window),
            started_at=started_at,
            finished_at=finished_at,
            window_resolution=window_resolution.as_dict(),
        )
        return CompositeReadResult(
            template_id=template.template_id,
            template_digest=template.digest,
            bridge_url=self.client.base_url,
            window_id=str(target_window),
            identity=before,
            payload=payload,
            derived=derived,
            evidence_path=evidence,
        )

    def _record_evidence(
        self,
        *,
        evidence_root: Path,
        template: TrustedReadTemplate,
        identity: dict[str, Any],
        code: str,
        response: dict[str, Any],
        derived: Any,
        health_before: dict[str, Any],
        health_after: dict[str, Any],
        windows_before: dict[str, Any],
        target_window: str,
        started_at: str,
        finished_at: str,
        window_resolution: dict[str, Any],
    ) -> Path:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
        directory = evidence_root.resolve() / f"{stamp}-{template.template_id.replace('.', '-')}-{uuid4().hex[:8]}"
        directory.mkdir(parents=True, exist_ok=False)
        request = {
            "template": {
                "templateId": template.template_id,
                "version": template.version,
                "digest": template.digest,
                "documentType": template.document_type,
                "methodIds": template.method_ids,
                "sourceRepository": template.source_repository,
                "sourceCommit": template.source_commit,
                "sourcePaths": template.source_paths,
                "additionalSources": template.additional_sources,
            },
            "registry": self.registry.identity,
            "expectedIdentity": identity,
            "generatedCodeSha256": hashlib.sha256(code.encode("utf-8")).hexdigest(),
        }
        result = {"bridgeResponse": response, "bridgeResponseSha256": sha256_json(response), "derived": derived}
        _atomic_write_json(directory / "request.json", request)
        _atomic_write_json(directory / "result.json", result)
        envelope = {
            "schemaVersion": COMPOSITE_EVIDENCE_SCHEMA,
            "templateId": template.template_id,
            "templateDigest": template.digest,
            "risk": "READ",
            "startedAt": started_at,
            "finishedAt": finished_at,
            "gatewayVersion": GATEWAY_VERSION,
            "registry": self.registry.identity,
            "bridge": {
                "service": health_before.get("service"),
                "url": self.client.base_url,
                "windowId": target_window,
                "healthBefore": health_before,
                "healthAfter": health_after,
                "windowsBefore": windows_before,
                "windowResolution": window_resolution,
            },
            "files": {
                "request.json": _sha256_file(directory / "request.json"),
                "result.json": _sha256_file(directory / "result.json"),
            },
        }
        _atomic_write_json(directory / "envelope.json", envelope)
        return directory / "envelope.json"


def _identity_subset(value: Any) -> dict[str, Any]:
    item = dict(value) if isinstance(value, Mapping) else {}
    return {key: item.get(key) for key in ("projectUuid", "documentUuid", "documentType")}


def _atomic_write_json(path: Path, value: Any) -> None:
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


_SCHEMATIC_METHODS = (
    "DMT_Project.getCurrentProjectInfo#1",
    "DMT_SelectControl.getCurrentDocumentInfo#1",
    "SCH_ManufactureData.getNetlistFile#1",
    "SCH_PrimitiveComponent.getAll#1",
    "SCH_PrimitiveComponent.getAllPinsByPrimitiveId#1",
)

_SCHEMATIC_BODY = """const __get=(o,n,f=null)=>{try{if(o&&typeof o[n]==='function')return o[n]();return f}catch(e){return f}};const __relation=v=>v?{uuid:v.uuid??null,libraryUuid:v.libraryUuid??null,name:v.name??null}:null;let __netlist=null;let __netlistError=null;try{const file=await eda.sch_ManufactureData.getNetlistFile();if(!file){__netlistError='EasyEDA did not return a schematic netlist file'}else{const text=await file.text();try{__netlist=JSON.parse(text)}catch(e){__netlistError='EasyEDA schematic netlist is not valid JSON'}}}catch(e){__netlistError=String(e?.message||e)}let __componentObjects=[];let __componentError=null;try{__componentObjects=await eda.sch_PrimitiveComponent.getAll(undefined,false)}catch(e){__componentError=String(e?.message||e)}const __componentPins=[];const __pinErrors=[];let __noConnectedPins=0;for(const item of __componentObjects||[]){const primitiveId=String(__get(item,'getState_PrimitiveId',item?.primitiveId??''));if(!primitiveId)continue;let pinObjects=[];try{pinObjects=await eda.sch_PrimitiveComponent.getAllPinsByPrimitiveId(primitiveId)}catch(e){__pinErrors.push({primitiveId,error:String(e?.message||e)})}const pins=[];for(const pin of pinObjects||[]){const noConnected=__get(pin,'getState_NoConnected',pin?.noConnected??false)===true;if(noConnected)__noConnectedPins++;pins.push({number:String(__get(pin,'getState_PinNumber',pin?.pinNumber??'')),name:String(__get(pin,'getState_PinName',pin?.pinName??'')),noConnected})}pins.sort((a,b)=>a.number.localeCompare(b.number,undefined,{numeric:true}));__componentPins.push({primitiveId,designator:String(__get(item,'getState_Designator',item?.designator??'')),name:String(__get(item,'getState_Name',item?.name??'')),footprint:__relation(__get(item,'getState_Footprint',item?.footprint??null)),procurement:{manufacturer:__get(item,'getState_Manufacturer',item?.manufacturer??null),manufacturerPart:__get(item,'getState_ManufacturerId',item?.manufacturerId??null),supplier:__get(item,'getState_Supplier',item?.supplier??null),supplierPart:__get(item,'getState_SupplierId',item?.supplierId??null)},pins})}__componentPins.sort((a,b)=>a.designator.localeCompare(b.designator,undefined,{numeric:true}));const __payload={schemaVersion:'easyeda.gateway.schematic-snapshot.v1',project:{uuid:__before.project?.uuid??__before.projectUuid??null,friendlyName:__before.project?.friendlyName??null,name:__before.project?.name??null},document:{uuid:__before.document?.uuid??__before.documentUuid??null,documentType:__before.documentType},netlistStatus:__netlist?'available':'unavailable',netlistError:__netlistError,netlist:__netlist,componentStatus:__componentError?'unavailable':'available',componentError:__componentError,pinErrors:__pinErrors,componentPins:__componentPins,noConnectedPins:__noConnectedPins}"""


_PCB_METHODS = (
    "DMT_Project.getCurrentProjectInfo#1",
    "DMT_SelectControl.getCurrentDocumentInfo#1",
    "PCB_PrimitiveComponent.getAll#1",
    "PCB_PrimitivePad.getAll#1",
    "PCB_PrimitiveLine.getAll#1",
    "PCB_PrimitiveArc.getAll#1",
    "PCB_PrimitivePolyline.getAll#1",
    "PCB_PrimitiveVia.getAll#1",
    "PCB_PrimitiveString.getAll#1",
    "PCB_Net.getAllNetsName#1",
    "PCB_Net.getNetLength#1",
    "PCB_Drc.getAllNetClasses#1",
    "PCB_Drc.getAllDifferentialPairs#1",
    "PCB_Drc.getAllEqualLengthNetGroups#1",
    "PCB_Drc.getAllPadPairGroups#1",
    "PCB_Drc.getPadPairGroupMinWireLength#1",
)

_PCB_BODY = """const __get=(o,n,f=null)=>{try{if(o&&typeof o[n]==='function')return o[n]();return f}catch(e){return f}};const __plain=v=>{try{return JSON.parse(JSON.stringify(v))}catch(e){return null}};const __relation=v=>v?{uuid:v.uuid??null,libraryUuid:v.libraryUuid??null,name:v.name??null}:null;const [__componentsRaw,__padsRaw,__linesRaw,__arcsRaw,__polylinesRaw,__viasRaw,__stringsRaw,__nets,__netClasses,__differentialPairs,__equalLengthGroups,__padPairGroups]=await Promise.all([eda.pcb_PrimitiveComponent.getAll(),eda.pcb_PrimitivePad.getAll(),eda.pcb_PrimitiveLine.getAll(),eda.pcb_PrimitiveArc.getAll(),eda.pcb_PrimitivePolyline.getAll(),eda.pcb_PrimitiveVia.getAll(),eda.pcb_PrimitiveString.getAll(),eda.pcb_Net.getAllNetsName(),eda.pcb_Drc.getAllNetClasses(),eda.pcb_Drc.getAllDifferentialPairs(),eda.pcb_Drc.getAllEqualLengthNetGroups(),eda.pcb_Drc.getAllPadPairGroups()]);const __components=(__componentsRaw||[]).map(item=>({primitiveId:String(__get(item,'getState_PrimitiveId',item?.primitiveId??'')),designator:String(__get(item,'getState_Designator',item?.designator??'')),name:String(__get(item,'getState_Name',item?.name??'')),footprint:__relation(__get(item,'getState_Footprint',item?.footprint??null)),x:__get(item,'getState_X',item?.x??null),y:__get(item,'getState_Y',item?.y??null),rotation:__get(item,'getState_Rotation',item?.rotation??null),layer:__get(item,'getState_Layer',item?.layer??null),addIntoBom:__get(item,'getState_AddIntoBom',item?.addIntoBom??null),otherProperty:__plain(__get(item,'getState_OtherProperty',item?.otherProperty??{}))||{},procurement:{manufacturer:__get(item,'getState_Manufacturer',item?.manufacturer??null),manufacturerPart:__get(item,'getState_ManufacturerId',item?.manufacturerId??null),supplier:__get(item,'getState_Supplier',item?.supplier??null),supplierPart:__get(item,'getState_SupplierId',item?.supplierId??null)}}));const __pads=(__padsRaw||[]).map(item=>({primitiveId:String(__get(item,'getState_PrimitiveId',item?.primitiveId??'')),layer:__get(item,'getState_Layer',item?.layer??null),padNumber:String(__get(item,'getState_PadNumber',item?.padNumber??'')),x:__get(item,'getState_X',item?.x??null),y:__get(item,'getState_Y',item?.y??null),rotation:__get(item,'getState_Rotation',item?.rotation??null),pad:__plain(__get(item,'getState_Pad',item?.pad??null)),net:String(__get(item,'getState_Net',item?.net??'')),hole:__plain(__get(item,'getState_Hole',item?.hole??null))}));const __lines=(__linesRaw||[]).map(item=>({primitiveId:String(__get(item,'getState_PrimitiveId',item?.primitiveId??'')),net:String(__get(item,'getState_Net',item?.net??'')),layer:__get(item,'getState_Layer',item?.layer??null),startX:__get(item,'getState_StartX',item?.startX??null),startY:__get(item,'getState_StartY',item?.startY??null),endX:__get(item,'getState_EndX',item?.endX??null),endY:__get(item,'getState_EndY',item?.endY??null),lineWidth:__get(item,'getState_LineWidth',item?.lineWidth??null)}));const __arcs=(__arcsRaw||[]).map(item=>({primitiveId:String(__get(item,'getState_PrimitiveId',item?.primitiveId??'')),net:String(__get(item,'getState_Net',item?.net??'')),layer:__get(item,'getState_Layer',item?.layer??null),startX:__get(item,'getState_StartX',item?.startX??null),startY:__get(item,'getState_StartY',item?.startY??null),endX:__get(item,'getState_EndX',item?.endX??null),endY:__get(item,'getState_EndY',item?.endY??null),arcAngle:__get(item,'getState_ArcAngle',item?.arcAngle??null),lineWidth:__get(item,'getState_LineWidth',item?.lineWidth??null)}));const __polylines=(__polylinesRaw||[]).map(item=>({primitiveId:String(__get(item,'getState_PrimitiveId',item?.primitiveId??'')),net:String(__get(item,'getState_Net',item?.net??'')),layer:__get(item,'getState_Layer',item?.layer??null),polygon:__plain(__get(item,'getState_Polygon',item?.polygon??null)),lineWidth:__get(item,'getState_LineWidth',item?.lineWidth??null)}));const __vias=(__viasRaw||[]).map(item=>({primitiveId:String(__get(item,'getState_PrimitiveId',item?.primitiveId??'')),net:String(__get(item,'getState_Net',item?.net??'')),x:__get(item,'getState_X',item?.x??null),y:__get(item,'getState_Y',item?.y??null),holeDiameter:__get(item,'getState_HoleDiameter',item?.holeDiameter??null),diameter:__get(item,'getState_Diameter',item?.diameter??null)}));const __texts=(__stringsRaw||[]).map(item=>({primitiveId:String(__get(item,'getState_PrimitiveId',item?.primitiveId??'')),layer:__get(item,'getState_Layer',item?.layer??null),x:__get(item,'getState_X',item?.x??null),y:__get(item,'getState_Y',item?.y??null),text:String(__get(item,'getState_Text',item?.text??'')),fontSize:__get(item,'getState_FontSize',item?.fontSize??null),lineWidth:__get(item,'getState_LineWidth',item?.lineWidth??null),alignMode:__get(item,'getState_AlignMode',item?.alignMode??null),rotation:__get(item,'getState_Rotation',item?.rotation??null)}));const __netLengths=await Promise.all((__nets||[]).map(async net=>({net:String(net),lengthMil:(await eda.pcb_Net.getNetLength(String(net)))??0})));const __padPairs=[];for(const group of __padPairGroups||[]){let lengths=[];try{lengths=await eda.pcb_Drc.getPadPairGroupMinWireLength(group.name)}catch(e){}__padPairs.push({...(__plain(group)||{}),minWireLengths:__plain(lengths)||[]})}const __payload={schemaVersion:'easyeda.gateway.pcb-snapshot.v1',project:{uuid:__before.project?.uuid??__before.projectUuid??null,friendlyName:__before.project?.friendlyName??null,name:__before.project?.name??null},document:{uuid:__before.document?.uuid??__before.documentUuid??null,documentType:__before.documentType},components:__components,pads:__pads,lines:__lines,arcs:__arcs,polylines:__polylines,vias:__vias,texts:__texts,netLengths:__netLengths,netClasses:__plain(__netClasses)||[],differentialPairs:__plain(__differentialPairs)||[],equalLengthGroups:__plain(__equalLengthGroups)||[],padPairGroups:__padPairs}"""


TRUSTED_READ_TEMPLATES = {
    "schematic.snapshot.v1": TrustedReadTemplate(
        template_id="schematic.snapshot.v1",
        version="1.0.0",
        document_type=1,
        method_ids=_SCHEMATIC_METHODS,
        body=_SCHEMATIC_BODY,
        source_repository="https://github.com/easyeda/eext-netlist-explorer",
        source_commit="6661961fc8780e13b97a9450a96afbaaf2960bf7",
        source_paths=("src/index.ts", "iframe/netlist.html"),
    ),
    "pcb.snapshot.v1": TrustedReadTemplate(
        template_id="pcb.snapshot.v1",
        version="1.0.0",
        document_type=3,
        method_ids=_PCB_METHODS,
        body=_PCB_BODY,
        source_repository="https://github.com/easyeda/eext-export-design-report",
        source_commit="31a8cfec95bcae13e981b912c6bc86025062dca0",
        source_paths=("src/index.ts",),
        additional_sources=(
            {
                "repository": "https://github.com/easyeda/eext-interactive-html-bom",
                "commit": "430ea9d06a1c975ed3d2c6da83a6686a1f737084",
                "paths": ("iframe/index.html",),
            },
        ),
    ),
}
