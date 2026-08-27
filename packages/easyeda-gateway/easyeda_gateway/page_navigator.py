"""Identity-guarded schematic-page navigation through official EasyEDA APIs."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
from typing import Any, Mapping

from .artifact_io import (
    atomic_write_json,
    create_evidence_directory,
    identity_subset,
    sha256_file,
    sha256_json,
    utc_now,
)
from .client import BridgeClient
from .contract import ApiRegistry, canonical_json
from .errors import BridgeError, BridgeTimeoutError, ContractError
from .version import GATEWAY_VERSION
from .window_guard import resolve_window


PAGE_NAVIGATION_RESULT_SCHEMA = "easyeda.gateway.schematic-page-navigation-result.v1"
PAGE_NAVIGATION_EVIDENCE_SCHEMA = "easyeda.gateway.schematic-page-navigation-evidence.v1"
PAGE_NAVIGATOR_ADAPTER_VERSION = "1.0.0"
PAGE_NAVIGATION_ACTIONS = frozenset({"list", "activate", "traverse"})
METHOD_IDS = (
    "DMT_Project.getCurrentProjectInfo#1",
    "DMT_SelectControl.getCurrentDocumentInfo#1",
    "DMT_EditorControl.openDocument#1",
    "DMT_EditorControl.activateDocument#1",
)


@dataclass(frozen=True)
class SchematicPageNavigationSpec:
    """One fixed page-navigation operation.

    ``activate`` intentionally leaves the requested page active. ``traverse``
    always attempts to restore the page that was active before traversal.
    """

    action: str = "list"
    target_page_uuid: str | None = None

    def normalized(self) -> "SchematicPageNavigationSpec":
        action = str(self.action).strip().lower()
        if action not in PAGE_NAVIGATION_ACTIONS:
            raise ContractError(
                f"Unsupported page-navigation action: {self.action!r}; "
                f"expected one of {sorted(PAGE_NAVIGATION_ACTIONS)}"
            )
        target = str(self.target_page_uuid).strip() if self.target_page_uuid else None
        if action == "activate" and not target:
            raise ContractError("activate requires target_page_uuid")
        if action != "activate" and target is not None:
            raise ContractError(f"{action} does not accept target_page_uuid")
        return SchematicPageNavigationSpec(action=action, target_page_uuid=target)


@dataclass(frozen=True)
class SchematicPageNavigationResult:
    bridge_url: str
    window_id: str
    action: str
    identity_before: dict[str, Any]
    identity_after: dict[str, Any]
    schematic: dict[str, Any]
    visited_pages: list[dict[str, Any]]
    restoration: dict[str, Any]
    evidence_path: Path

    def as_dict(self) -> dict[str, Any]:
        return {
            "schemaVersion": "easyeda.gateway.schematic-page-navigation-execution.v1",
            "adapterVersion": PAGE_NAVIGATOR_ADAPTER_VERSION,
            "bridgeUrl": self.bridge_url,
            "windowId": self.window_id,
            "action": self.action,
            "identityBefore": self.identity_before,
            "identityAfter": self.identity_after,
            "schematic": self.schematic,
            "visitedPages": self.visited_pages,
            "restoration": self.restoration,
            "evidencePath": str(self.evidence_path),
        }


class EasyedaPageNavigator:
    """Fixed adapter for same-schematic tab navigation without save or mutation."""

    def __init__(self, registry: ApiRegistry, client: BridgeClient):
        self.registry = registry
        self.client = client
        for method_id in METHOD_IDS:
            descriptor = registry.resolve_method(method_id)
            if descriptor.deprecated:
                raise ContractError(
                    f"Page navigator references deprecated method: {method_id}"
                )

    def build_code(
        self,
        spec: SchematicPageNavigationSpec,
        identity: Mapping[str, Any] | None = None,
    ) -> str:
        normalized = spec.normalized()
        expected = {
            "projectUuid": (identity or {}).get("projectUuid"),
            "documentUuid": (identity or {}).get("documentUuid"),
            "documentType": 1,
        }
        if normalized.action != "list":
            for key in ("projectUuid", "documentUuid"):
                value = expected.get(key)
                if not isinstance(value, str) or not value.strip():
                    raise ContractError(
                        f"{normalized.action} requires an exact expected {key}"
                    )

        statements = [
            f"const __expected={canonical_json(expected)}",
            f"const __action={canonical_json(normalized.action)}",
            f"const __target={canonical_json(normalized.target_page_uuid)}",
            "const __read=async()=>{const project=await eda.dmt_Project.getCurrentProjectInfo();const document=await eda.dmt_SelectControl.getCurrentDocumentInfo();return {project,document,identity:{projectUuid:project?.uuid??document?.parentProjectUuid??null,documentUuid:document?.uuid??null,documentType:document?.documentType??null,tabId:document?.tabId??null}}}",
            "const __assertExpected=(actual)=>{for(const key of ['projectUuid','documentUuid','documentType']){if(__expected[key]!==null&&__expected[key]!==actual[key]){throw new Error(`EasyEDA identity mismatch for ${key}: expected ${String(__expected[key])}, got ${String(actual[key])}`)}}}",
            "const __beforeContext=await __read()",
            "const __before=__beforeContext.identity",
            "__assertExpected(__before)",
            "if(__before.documentType!==1){throw new Error('Active EasyEDA document is not a schematic page')}",
            "const __items=Array.isArray(__beforeContext.project?.data)?__beforeContext.project.data:[]",
            "const __schematics=__items.map(item=>item?.schematic??item).filter(item=>Array.isArray(item?.page))",
            "const __matches=__schematics.filter(item=>item.page.some(page=>page?.uuid===__before.documentUuid))",
            "if(__matches.length!==1){throw new Error(`Could not resolve exactly one owning schematic for active page; found ${__matches.length}`)}",
            "const __schematic=__matches[0]",
            "const __pages=__schematic.page.map((page,index)=>({uuid:String(page?.uuid??''),name:String(page?.name??''),parentSchematicUuid:String(page?.parentSchematicUuid??__schematic.uuid??''),index})).filter(page=>page.uuid)",
            "if(__pages.length===0){throw new Error('Current schematic has no navigable pages')}",
            "if(new Set(__pages.map(page=>page.uuid)).size!==__pages.length){throw new Error('Current schematic page UUIDs are not unique')}",
            "const __pageByUuid=new Map(__pages.map(page=>[page.uuid,page]))",
            "const __readVerified=async expectedPageUuid=>{const context=await __read();const actual=context.identity;if(actual.projectUuid!==__before.projectUuid||actual.documentType!==1||actual.documentUuid!==expectedPageUuid){throw new Error(`Activated page identity mismatch: expected ${expectedPageUuid}, got ${String(actual.documentUuid)}`)}return actual}",
            "const __activate=async pageUuid=>{const tabId=await eda.dmt_EditorControl.openDocument(pageUuid);if(!tabId){throw new Error(`Could not open schematic page ${pageUuid}`)}const activated=await eda.dmt_EditorControl.activateDocument(tabId);if(!activated){throw new Error(`Could not activate schematic page ${pageUuid}`)}const identity=await __readVerified(pageUuid);return {pageUuid,tabId,identity}}",
            "const __restore=async()=>{const result={attempted:true,succeeded:false,pageUuid:__before.documentUuid,tabId:__before.tabId,identity:null,error:null};try{if(!__before.tabId){throw new Error('Original schematic tab ID is unavailable')}const activated=await eda.dmt_EditorControl.activateDocument(__before.tabId);if(!activated){throw new Error('Could not reactivate original schematic tab')}result.identity=await __readVerified(__before.documentUuid);result.succeeded=true}catch(error){result.error=String(error?.message??error)}return result}",
            "let __visited=[]",
            "let __restoration={attempted:false,succeeded:null,pageUuid:__before.documentUuid,tabId:__before.tabId,identity:null,error:null}",
            "let __failure=null",
            "let __after=__before",
            "if(__action==='list'){const context=await __read();__after=context.identity;if(__after.projectUuid!==__before.projectUuid||__after.documentUuid!==__before.documentUuid||__after.documentType!==__before.documentType){throw new Error('EasyEDA identity changed while listing schematic pages')}}else if(__action==='activate'){if(!__pageByUuid.has(__target)){throw new Error(`Target page is not in the current schematic: ${String(__target)}`)}if(__target===__before.documentUuid){__visited.push({pageUuid:__target,tabId:__before.tabId,alreadyActive:true,identity:__before});__after=__before}else{try{const activated=await __activate(__target);__visited.push({...activated,alreadyActive:false});__after=activated.identity}catch(error){__failure=String(error?.message??error);__restoration=await __restore();__after=__restoration.identity??(await __read()).identity}}}else if(__action==='traverse'){try{for(const page of __pages){if(page.uuid===__before.documentUuid){__visited.push({pageUuid:page.uuid,tabId:__before.tabId,alreadyActive:true,identity:__before})}else{const activated=await __activate(page.uuid);__visited.push({...activated,alreadyActive:false})}}}catch(error){__failure=String(error?.message??error)}__restoration=await __restore();__after=__restoration.identity??(await __read()).identity;if(!__restoration.succeeded&&!__failure){__failure=__restoration.error??'Original schematic page restoration failed'}}",
            "const __status=__failure===null?'PASS':'FAILED'",
            f"return {{schemaVersion:'{PAGE_NAVIGATION_RESULT_SCHEMA}',adapterVersion:'{PAGE_NAVIGATOR_ADAPTER_VERSION}',status:__status,action:__action,identityBefore:__before,identityAfter:__after,schematic:{{uuid:String(__schematic.uuid??''),name:String(__schematic.name??''),pages:__pages}},targetPageUuid:__target,visitedPages:__visited,restoration:__restoration,failure:__failure,saveCalled:false,documentContentMutation:false}}",
        ]
        code = ";".join(statements) + ";"
        if "//" in code or "/*" in code:
            raise ContractError("Page-navigation compilation produced a JavaScript comment")
        return code

    def execute(
        self,
        spec: SchematicPageNavigationSpec,
        evidence_root: str | Path,
        *,
        identity: Mapping[str, Any] | None = None,
        window_id: str | None = None,
        allow_window_rebind: bool = False,
    ) -> SchematicPageNavigationResult:
        normalized = spec.normalized()
        evidence_directory = create_evidence_directory(
            evidence_root,
            f"schematic-page-{normalized.action}",
        )
        evidence_path = evidence_directory / "envelope.json"
        started_at = utc_now()
        code = self.build_code(normalized, identity)
        request = {
            "schemaVersion": "easyeda.gateway.schematic-page-navigation-request.v1",
            "adapterVersion": PAGE_NAVIGATOR_ADAPTER_VERSION,
            "registry": self.registry.identity,
            "expectedIdentity": dict(identity or {}),
            "action": normalized.action,
            "targetPageUuid": normalized.target_page_uuid,
            "risk": "READ" if normalized.action == "list" else "EPHEMERAL_NAVIGATION",
            "methods": list(METHOD_IDS),
            "generatedCodeSha256": hashlib.sha256(code.encode("utf-8")).hexdigest(),
            "save": False,
            "automaticRetry": False,
        }
        atomic_write_json(evidence_directory / "request.json", request)
        result_value: Mapping[str, Any] | None = None
        try:
            health_before = self.client.health()
            windows_before = self.client.windows()
            window_resolution = resolve_window(
                windows_before,
                requested_window_id=window_id,
                identity=identity,
                allow_rebind=allow_window_rebind,
            )
            target_window = window_resolution.resolved_window_id
            response = self.client.execute_code(code, target_window)
            health_after = self.client.health()
            result = response.get("result")
            if not isinstance(result, Mapping):
                raise BridgeError("Page navigation returned a non-object result")
            result_value = result
            if result.get("schemaVersion") != PAGE_NAVIGATION_RESULT_SCHEMA:
                raise BridgeError("Page navigation result schema mismatch")
            if result.get("adapterVersion") != PAGE_NAVIGATOR_ADAPTER_VERSION:
                raise BridgeError("Page navigation adapter identity mismatch")
            before = _identity_with_tab(result.get("identityBefore"))
            after = _identity_with_tab(result.get("identityAfter"))
            if before.get("documentType") != 1 or after.get("documentType") != 1:
                raise BridgeError("Page navigation did not remain on schematic pages")
            if before.get("projectUuid") != after.get("projectUuid"):
                raise BridgeError("EasyEDA project identity changed during page navigation")
            if result.get("saveCalled") is not False:
                raise BridgeError("Page navigation did not prove saveCalled=false")
            if result.get("documentContentMutation") is not False:
                raise BridgeError("Page navigation reported a document-content mutation")
            if normalized.action in {"list", "traverse"} and (
                before.get("documentUuid") != after.get("documentUuid")
            ):
                raise BridgeError(
                    f"{normalized.action} did not restore/preserve the original schematic page"
                )
            if normalized.action == "activate" and result.get("status") == "PASS":
                if after.get("documentUuid") != normalized.target_page_uuid:
                    raise BridgeError("Page activation selected the wrong target page")
            schematic = result.get("schematic")
            visited = result.get("visitedPages")
            restoration = result.get("restoration")
            if not isinstance(schematic, Mapping) or not isinstance(visited, list):
                raise BridgeError("Page navigation result is missing schematic/page evidence")
            if not isinstance(restoration, Mapping):
                raise BridgeError("Page navigation result is missing restoration evidence")
            pages = schematic.get("pages")
            if not isinstance(pages, list) or not pages:
                raise BridgeError("Page navigation returned no ordered schematic pages")
            page_uuids = [
                str(item.get("uuid") or "") if isinstance(item, Mapping) else ""
                for item in pages
            ]
            if any(not page_uuid for page_uuid in page_uuids):
                raise BridgeError("Page navigation returned an empty page UUID")
            if len(set(page_uuids)) != len(page_uuids):
                raise BridgeError("Page navigation returned duplicate page UUIDs")
            if before.get("documentUuid") not in page_uuids:
                raise BridgeError("Origin page is absent from the owning schematic page list")
            visited_page_uuids = [
                str(item.get("pageUuid") or "") if isinstance(item, Mapping) else ""
                for item in visited
            ]
            if result.get("status") == "PASS" and normalized.action == "activate":
                if normalized.target_page_uuid not in page_uuids:
                    raise BridgeError("Activated target is absent from the schematic page list")
                if visited_page_uuids != [normalized.target_page_uuid]:
                    raise BridgeError("Activation evidence does not contain exactly the target page")
            if result.get("status") == "PASS" and normalized.action == "traverse":
                if visited_page_uuids != page_uuids:
                    raise BridgeError("Traversal evidence does not match the ordered schematic pages")
                if restoration.get("attempted") is not True or restoration.get("succeeded") is not True:
                    raise BridgeError("Traversal did not prove original-page restoration")
            result_record = {
                "bridgeResponse": response,
                "bridgeResponseSha256": sha256_json(response),
                "navigation": dict(result),
            }
            atomic_write_json(evidence_directory / "result.json", result_record)
            status = "PASS" if result.get("status") == "PASS" else "FAILED"
            envelope = {
                "schemaVersion": PAGE_NAVIGATION_EVIDENCE_SCHEMA,
                "status": status,
                "risk": request["risk"],
                "startedAt": started_at,
                "finishedAt": utc_now(),
                "gatewayVersion": GATEWAY_VERSION,
                "adapterVersion": PAGE_NAVIGATOR_ADAPTER_VERSION,
                "registry": self.registry.identity,
                "identityBefore": before,
                "identityAfter": after,
                "action": normalized.action,
                "targetPageUuid": normalized.target_page_uuid,
                "bridge": {
                    "service": health_before.get("service"),
                    "url": self.client.base_url,
                    "windowId": target_window,
                    "healthBefore": health_before,
                    "healthAfter": health_after,
                    "windowsBefore": windows_before,
                    "windowResolution": window_resolution.as_dict(),
                },
                "safety": {
                    "saveCalled": False,
                    "documentContentMutation": False,
                    "automaticRetry": False,
                    "restoration": result.get("restoration"),
                },
                "files": {
                    "request.json": sha256_file(evidence_directory / "request.json"),
                    "result.json": sha256_file(evidence_directory / "result.json"),
                },
            }
            atomic_write_json(evidence_path, envelope)
            if status != "PASS":
                raise BridgeError(
                    "EasyEDA page navigation failed after guarded restoration attempt: "
                    f"{result.get('failure')}; evidence: {evidence_path}"
                )
            return SchematicPageNavigationResult(
                bridge_url=self.client.base_url,
                window_id=target_window,
                action=normalized.action,
                identity_before=before,
                identity_after=after,
                schematic=dict(schematic),
                visited_pages=[dict(item) for item in visited if isinstance(item, Mapping)],
                restoration=dict(restoration),
                evidence_path=evidence_path,
            )
        except Exception as exc:
            if not evidence_path.exists():
                try:
                    _record_failure(
                        evidence_directory,
                        self.registry.identity,
                        normalized,
                        identity,
                        started_at,
                        exc,
                        result_value,
                    )
                except OSError:
                    pass
            raise


def _identity_with_tab(value: Any) -> dict[str, Any]:
    identity = identity_subset(value)
    item = dict(value) if isinstance(value, Mapping) else {}
    identity["tabId"] = item.get("tabId")
    return identity


def _record_failure(
    evidence_directory: Path,
    registry_identity: Mapping[str, Any],
    spec: SchematicPageNavigationSpec,
    identity: Mapping[str, Any] | None,
    started_at: str,
    error: Exception,
    result: Mapping[str, Any] | None,
) -> None:
    timeout = isinstance(error, BridgeTimeoutError)
    failure = {
        "schemaVersion": "easyeda.gateway.schematic-page-navigation-failure.v1",
        "errorType": type(error).__name__,
        "error": str(error),
        "action": spec.action,
        "targetPageUuid": spec.target_page_uuid,
        "expectedIdentity": dict(identity or {}),
        "bridgeTimedOut": timeout,
        "activePageState": "UNKNOWN_REPROBE_REQUIRED" if timeout else "UNCONFIRMED",
        "automaticRetry": False,
        "partialResult": dict(result) if isinstance(result, Mapping) else None,
    }
    atomic_write_json(evidence_directory / "failure.json", failure)
    files = {
        path.name: sha256_file(path)
        for path in (evidence_directory / "request.json", evidence_directory / "failure.json")
        if path.is_file()
    }
    atomic_write_json(
        evidence_directory / "envelope.json",
        {
            "schemaVersion": PAGE_NAVIGATION_EVIDENCE_SCHEMA,
            "status": "FAILED",
            "risk": "READ" if spec.action == "list" else "EPHEMERAL_NAVIGATION",
            "startedAt": started_at,
            "finishedAt": utc_now(),
            "gatewayVersion": GATEWAY_VERSION,
            "adapterVersion": PAGE_NAVIGATOR_ADAPTER_VERSION,
            "registry": dict(registry_identity),
            "expectedIdentity": dict(identity or {}),
            "action": spec.action,
            "targetPageUuid": spec.target_page_uuid,
            "safety": {
                "saveCalled": False,
                "documentContentMutation": False,
                "automaticRetry": False,
                "activePageState": failure["activePageState"],
            },
            "error": failure,
            "files": files,
        },
    )
