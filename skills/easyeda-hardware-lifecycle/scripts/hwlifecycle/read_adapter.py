"""Deterministic read-only templates backed by canonical EasyEDA method IDs."""

from __future__ import annotations

import json
from typing import Any, Mapping

from .api_registry import plan_digest, registry_identity, validate_api_plan
from .bridge import BridgeError, OfficialBridgeClient
from .io_utils import utc_now
from .session import DocumentIdentity, assert_identity, capture_identity, decode_identity


SNAPSHOT_METHODS = (
    ("DMT_Project.getCurrentProjectInfo#1", "read current project identity"),
    ("DMT_SelectControl.getCurrentDocumentInfo#1", "guard active page identity before and after capture"),
    ("SCH_PrimitiveComponent.getAll#1", "read components on the active schematic page"),
    ("SCH_PrimitiveComponent.getAllPinsByPrimitiveId#1", "read pins for each active-page component"),
    ("ISCH_PrimitiveComponent.getState_PrimitiveId#1", "normalize component primitive ID"),
    ("ISCH_PrimitiveComponent.getState_ComponentType#1", "normalize component type"),
    ("ISCH_PrimitiveComponent.getState_Component#1", "normalize linked device identity"),
    ("ISCH_PrimitiveComponent.getState_Symbol#1", "normalize linked symbol identity"),
    ("ISCH_PrimitiveComponent.getState_Footprint#1", "normalize linked footprint identity"),
    ("ISCH_PrimitiveComponent.getState_Designator#1", "normalize designator"),
    ("ISCH_PrimitiveComponent.getState_Name#1", "normalize displayed value or name"),
    ("ISCH_PrimitiveComponent.getState_UniqueId#1", "normalize unique ID"),
    ("ISCH_PrimitiveComponent.getState_X#1", "capture schematic X coordinate"),
    ("ISCH_PrimitiveComponent.getState_Y#1", "capture schematic Y coordinate"),
    ("ISCH_PrimitiveComponent.getState_Rotation#1", "capture schematic rotation"),
    ("ISCH_PrimitiveComponent.getState_Mirror#1", "capture schematic mirror state"),
    ("ISCH_PrimitiveComponent.getState_AddIntoBom#1", "capture BOM participation"),
    ("ISCH_PrimitiveComponent.getState_AddIntoPcb#1", "capture PCB participation"),
    ("ISCH_PrimitiveComponent.getState_Manufacturer#1", "read Manufacturer"),
    ("ISCH_PrimitiveComponent.getState_ManufacturerId#1", "read Manufacturer Part"),
    ("ISCH_PrimitiveComponent.getState_Supplier#1", "read Supplier"),
    ("ISCH_PrimitiveComponent.getState_SupplierId#1", "read Supplier Part"),
    ("ISCH_PrimitivePin.getState_PinNumber#1", "normalize pin number"),
    ("ISCH_PrimitivePin.getState_PinName#1", "normalize pin name"),
    ("ISCH_PrimitivePin.getState_NoConnected#1", "capture explicit no-connect state"),
)


def _json_literal(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def build_active_schematic_plan(
    identity: DocumentIdentity, manifest: dict[str, Any]
) -> dict[str, Any]:
    return {
        "schemaVersion": "easyeda.hardware-lifecycle.api-plan.v1",
        "planId": f"plan:active-schematic-snapshot:{identity.documentUuid}",
        "template": "active-schematic-snapshot.v1",
        "risk": "READ",
        "registry": registry_identity(manifest),
        "identity": identity.to_dict(),
        "calls": [
            {"methodId": method_id, "effect": "READ", "purpose": purpose}
            for method_id, purpose in SNAPSHOT_METHODS
        ],
        "save": False,
    }


def build_active_schematic_code(identity: DocumentIdentity) -> str:
    expected_project = _json_literal(identity.projectUuid)
    expected_document = _json_literal(identity.documentUuid)
    return (
        "const project=await eda.dmt_Project.getCurrentProjectInfo();"
        "const beforeDocument=await eda.dmt_SelectControl.getCurrentDocumentInfo();"
        "if(!project||!beforeDocument)throw new Error('No active EasyEDA project/document');"
        f"if(String(project.uuid||beforeDocument.parentProjectUuid||'')!=={expected_project})throw new Error('Project identity mismatch');"
        f"if(String(beforeDocument.uuid||'')!=={expected_document})throw new Error('Document identity mismatch');"
        "if(!['1','SCHEMATIC_PAGE'].includes(String(beforeDocument.documentType)))throw new Error('Active document is not a schematic page');"
        "const read=(item,method,fallback)=>typeof item[method]==='function'?item[method]():fallback;"
        "const relation=(value)=>value?{libraryUuid:String(value.libraryUuid||''),uuid:String(value.uuid||''),name:String(value.name||'')}:null;"
        "const items=await eda.sch_PrimitiveComponent.getAll(undefined,false);"
        "const components=[];"
        "for(const item of items||[]){"
        "const primitiveId=String(read(item,'getState_PrimitiveId',item.primitiveId||''));"
        "if(!primitiveId)continue;"
        "const pinItems=await eda.sch_PrimitiveComponent.getAllPinsByPrimitiveId(primitiveId);"
        "const pins=(pinItems||[]).map(pin=>({number:String(read(pin,'getState_PinNumber',pin.pinNumber||'')),name:String(read(pin,'getState_PinName',pin.pinName||'')),noConnected:Boolean(read(pin,'getState_NoConnected',pin.noConnected||false))})).sort((a,b)=>a.number.localeCompare(b.number,undefined,{numeric:true})||a.name.localeCompare(b.name));"
        "components.push({"
        "primitiveId,"
        "componentType:String(read(item,'getState_ComponentType',item.componentType||'')),"
        "designator:String(read(item,'getState_Designator',item.designator||'')),"
        "value:read(item,'getState_Name',item.name??null),"
        "uniqueId:read(item,'getState_UniqueId',item.uniqueId??null),"
        "device:relation(read(item,'getState_Component',item.component)),"
        "symbol:relation(read(item,'getState_Symbol',item.symbol)),"
        "footprint:relation(read(item,'getState_Footprint',item.footprint)),"
        "x:read(item,'getState_X',item.x??null),"
        "y:read(item,'getState_Y',item.y??null),"
        "rotation:read(item,'getState_Rotation',item.rotation??null),"
        "mirror:read(item,'getState_Mirror',item.mirror??null),"
        "addIntoBom:read(item,'getState_AddIntoBom',item.addIntoBom??null),"
        "addIntoPcb:read(item,'getState_AddIntoPcb',item.addIntoPcb??null),"
        "procurement:{'Manufacturer':read(item,'getState_Manufacturer',item.manufacturer??null),'Manufacturer Part':read(item,'getState_ManufacturerId',item.manufacturerId??null),'Supplier':read(item,'getState_Supplier',item.supplier??null),'Supplier Part':read(item,'getState_SupplierId',item.supplierId??null)},"
        "pins});"
        "}"
        "components.sort((a,b)=>a.designator.localeCompare(b.designator,undefined,{numeric:true})||a.primitiveId.localeCompare(b.primitiveId));"
        "const afterDocument=await eda.dmt_SelectControl.getCurrentDocumentInfo();"
        f"if(!afterDocument||String(afterDocument.uuid||'')!=={expected_document})throw new Error('Document identity drift during capture');"
        "return {project,beforeDocument,afterDocument,components};"
    )


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _normalize_component(raw: Any) -> dict[str, Any]:
    component = _mapping(raw)
    primitive_id = str(component.get("primitiveId") or "")
    if not primitive_id:
        raise BridgeError("snapshot component is missing primitiveId")
    pins = component.get("pins")
    if not isinstance(pins, list):
        raise BridgeError(f"snapshot component pins are invalid: {primitive_id}")
    procurement = _mapping(component.get("procurement"))
    normalized_procurement = {}
    for field in ("Manufacturer", "Manufacturer Part", "Supplier", "Supplier Part"):
        value = procurement.get(field)
        normalized_procurement[field] = None if value in (None, "") else str(value)
    return {
        "primitiveId": primitive_id,
        "componentType": str(component.get("componentType") or ""),
        "designator": str(component.get("designator") or ""),
        "value": None if component.get("value") is None else str(component.get("value")),
        "uniqueId": None
        if component.get("uniqueId") is None
        else str(component.get("uniqueId")),
        "device": component.get("device"),
        "symbol": component.get("symbol"),
        "footprint": component.get("footprint"),
        "x": component.get("x"),
        "y": component.get("y"),
        "rotation": component.get("rotation"),
        "mirror": component.get("mirror"),
        "addIntoBom": component.get("addIntoBom"),
        "addIntoPcb": component.get("addIntoPcb"),
        "procurement": normalized_procurement,
        "pins": [
            {
                "number": str(_mapping(pin).get("number") or ""),
                "name": str(_mapping(pin).get("name") or ""),
                "noConnected": _mapping(pin).get("noConnected") is True,
            }
            for pin in pins
        ],
    }


def decode_active_schematic_snapshot(
    raw: Any,
    *,
    expected_identity: DocumentIdentity,
    plan: dict[str, Any],
) -> dict[str, Any]:
    result = _mapping(raw)
    project = _mapping(result.get("project"))
    before = decode_identity(
        {"project": project, "document": _mapping(result.get("beforeDocument"))},
        base_url=str(expected_identity.bridge.get("baseUrl") or ""),
        window_id=str(expected_identity.bridge.get("windowId") or ""),
    )
    after = decode_identity(
        {"project": project, "document": _mapping(result.get("afterDocument"))},
        base_url=str(expected_identity.bridge.get("baseUrl") or ""),
        window_id=str(expected_identity.bridge.get("windowId") or ""),
    )
    assert_identity(expected_identity, before, require_schematic=True)
    assert_identity(expected_identity, after, require_schematic=True)
    raw_components = result.get("components")
    if not isinstance(raw_components, list):
        raise BridgeError("active schematic snapshot did not return a components array")
    components = [_normalize_component(component) for component in raw_components]
    components.sort(key=lambda item: (item["designator"], item["primitiveId"]))
    return {
        "schemaVersion": "easyeda.hardware-lifecycle.active-schematic-snapshot.v1",
        "capturedAt": utc_now(),
        "identity": expected_identity.to_dict(),
        "apiPlanDigest": plan_digest(plan),
        "counts": {
            "components": len(components),
            "pins": sum(len(component["pins"]) for component in components),
        },
        "components": components,
    }


def capture_active_schematic(
    client: OfficialBridgeClient,
    *,
    window_id: str,
    manifest: dict[str, Any],
) -> dict[str, Any]:
    identity = capture_identity(client, window_id=window_id)
    if identity.documentType != "SCHEMATIC_PAGE":
        raise BridgeError(
            f"active EasyEDA document is not a schematic page: {identity.documentType}"
        )
    plan = build_active_schematic_plan(identity, manifest)
    validation = validate_api_plan(plan, manifest)
    if not validation["valid"] or not validation["executable"]:
        raise BridgeError(f"read plan validation failed: {validation}")
    guard_identity = capture_identity(client, window_id=window_id)
    assert_identity(identity, guard_identity, require_schematic=True)
    code = build_active_schematic_code(identity)
    raw = client.execute(code, window_id=window_id)
    snapshot = decode_active_schematic_snapshot(
        raw, expected_identity=identity, plan=plan
    )
    return {
        "identity": identity.to_dict(),
        "plan": plan,
        "validation": validation,
        "snapshot": snapshot,
    }
