"""Identity-guarded navigation between board-associated EasyEDA documents."""

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


BOARD_NAVIGATION_RESULT_SCHEMA = "easyeda.gateway.board-document-navigation-result.v1"
BOARD_NAVIGATION_EVIDENCE_SCHEMA = "easyeda.gateway.board-document-navigation-evidence.v1"
BOARD_NAVIGATOR_ADAPTER_VERSION = "1.0.0"
BOARD_NAVIGATION_ACTIONS = frozenset({"list", "activate"})
SUPPORTED_DOCUMENT_TYPES = frozenset({1, 3})
METHOD_IDS = (
    "DMT_Project.getCurrentProjectInfo#1",
    "DMT_SelectControl.getCurrentDocumentInfo#1",
    "DMT_Board.getAllBoardsInfo#1",
    "DMT_EditorControl.openDocument#1",
    "DMT_EditorControl.activateDocument#1",
)


@dataclass(frozen=True)
class BoardDocumentNavigationSpec:
    """List or activate a schematic page/PCB belonging to a current-project board."""

    action: str = "list"
    target_document_uuid: str | None = None
    target_document_type: int | None = None

    def normalized(self) -> "BoardDocumentNavigationSpec":
        action = str(self.action).strip().lower()
        if action not in BOARD_NAVIGATION_ACTIONS:
            raise ContractError(
                f"Unsupported board-navigation action: {self.action!r}; "
                f"expected one of {sorted(BOARD_NAVIGATION_ACTIONS)}"
            )
        target_uuid = (
            str(self.target_document_uuid).strip()
            if self.target_document_uuid
            else None
        )
        target_type = (
            int(self.target_document_type)
            if self.target_document_type is not None
            else None
        )
        if action == "activate":
            if not target_uuid:
                raise ContractError("activate requires target_document_uuid")
            if target_type not in SUPPORTED_DOCUMENT_TYPES:
                raise ContractError(
                    "activate target_document_type must be 1 (schematic page) or 3 (PCB)"
                )
        elif target_uuid is not None or target_type is not None:
            raise ContractError("list does not accept a target document")
        return BoardDocumentNavigationSpec(action, target_uuid, target_type)


@dataclass(frozen=True)
class BoardDocumentNavigationResult:
    bridge_url: str
    window_id: str
    action: str
    identity_before: dict[str, Any]
    identity_after: dict[str, Any]
    boards: list[dict[str, Any]]
    documents: list[dict[str, Any]]
    visited_document: dict[str, Any] | None
    restoration: dict[str, Any]
    evidence_path: Path

    def as_dict(self) -> dict[str, Any]:
        return {
            "schemaVersion": "easyeda.gateway.board-document-navigation-execution.v1",
            "adapterVersion": BOARD_NAVIGATOR_ADAPTER_VERSION,
            "bridgeUrl": self.bridge_url,
            "windowId": self.window_id,
            "action": self.action,
            "identityBefore": self.identity_before,
            "identityAfter": self.identity_after,
            "boards": self.boards,
            "documents": self.documents,
            "visitedDocument": self.visited_document,
            "restoration": self.restoration,
            "evidencePath": str(self.evidence_path),
        }


class EasyedaBoardDocumentNavigator:
    """Fixed same-project navigator for board schematic pages and PCBs."""

    def __init__(self, registry: ApiRegistry, client: BridgeClient):
        self.registry = registry
        self.client = client
        for method_id in METHOD_IDS:
            descriptor = registry.resolve_method(method_id)
            if descriptor.deprecated:
                raise ContractError(
                    f"Board document navigator references deprecated method: {method_id}"
                )

    def build_code(
        self,
        spec: BoardDocumentNavigationSpec,
        identity: Mapping[str, Any] | None = None,
    ) -> str:
        normalized = spec.normalized()
        expected = {
            "projectUuid": (identity or {}).get("projectUuid"),
            "documentUuid": (identity or {}).get("documentUuid"),
            "documentType": (identity or {}).get("documentType"),
        }
        if normalized.action == "activate":
            for key in ("projectUuid", "documentUuid"):
                value = expected.get(key)
                if value is None or (isinstance(value, str) and not value.strip()):
                    raise ContractError(f"activate requires an exact expected {key}")

        statements = [
            f"const __expected={canonical_json(expected)}",
            f"const __action={canonical_json(normalized.action)}",
            f"const __targetUuid={canonical_json(normalized.target_document_uuid)}",
            f"const __targetType={canonical_json(normalized.target_document_type)}",
            "const __read=async()=>{const project=await eda.dmt_Project.getCurrentProjectInfo();const document=await eda.dmt_SelectControl.getCurrentDocumentInfo();return {project,document,identity:{projectUuid:project?.uuid??document?.parentProjectUuid??null,documentUuid:document?.uuid??null,documentType:document?.documentType??null,tabId:document?.tabId??null}}}",
            "const __assertExpected=actual=>{for(const key of ['projectUuid','documentUuid','documentType']){if(__expected[key]!==null&&__expected[key]!==actual[key]){throw new Error(`EasyEDA identity mismatch for ${key}: expected ${String(__expected[key])}, got ${String(actual[key])}`)}}}",
            "const __beforeContext=await __read()",
            "const __before=__beforeContext.identity",
            "__assertExpected(__before)",
            "if(![1,3].includes(__before.documentType)){throw new Error('Active document is not a board schematic page or PCB')}",
            "const __rawBoards=await eda.dmt_Board.getAllBoardsInfo()",
            "if(!Array.isArray(__rawBoards)){throw new Error('Board inventory is unavailable')}",
            "const __boards=__rawBoards.map((board,index)=>{const schematic=board?.schematic??null;const pcb=board?.pcb??null;const pages=Array.isArray(schematic?.page)?schematic.page.map((page,pageIndex)=>({uuid:String(page?.uuid??''),name:String(page?.name??''),documentType:1,parentSchematicUuid:String(page?.parentSchematicUuid??schematic?.uuid??''),parentProjectUuid:String(schematic?.parentProjectUuid??board?.parentProjectUuid??''),boardName:String(board?.name??''),boardIndex:index,pageIndex})).filter(page=>page.uuid):[];return {name:String(board?.name??''),index,parentProjectUuid:String(board?.parentProjectUuid??schematic?.parentProjectUuid??pcb?.parentProjectUuid??''),schematic:schematic?{uuid:String(schematic?.uuid??''),name:String(schematic?.name??''),pages}:null,pcb:pcb?{uuid:String(pcb?.uuid??''),name:String(pcb?.name??''),documentType:3,parentProjectUuid:String(pcb?.parentProjectUuid??board?.parentProjectUuid??''),boardName:String(board?.name??''),boardIndex:index}:null}})",
            "const __documents=__boards.flatMap(board=>[...(board.schematic?.pages??[]),...(board.pcb?.uuid?[board.pcb]:[])])",
            "if(__documents.length===0){throw new Error('Current project has no board-associated schematic pages or PCBs')}",
            "if(__boards.some(board=>board.parentProjectUuid&&board.parentProjectUuid!==__before.projectUuid)||__documents.some(document=>document.parentProjectUuid&&document.parentProjectUuid!==__before.projectUuid)){throw new Error('Board inventory escaped the active project')}",
            "if(new Set(__documents.map(document=>`${document.documentType}:${document.uuid}`)).size!==__documents.length){throw new Error('Board document identities are not unique')}",
            "const __readVerified=async(expectedUuid,expectedType)=>{const context=await __read();const actual=context.identity;if(actual.projectUuid!==__before.projectUuid||actual.documentUuid!==expectedUuid||actual.documentType!==expectedType){throw new Error(`Activated document identity mismatch: expected ${expectedType}:${expectedUuid}, got ${String(actual.documentType)}:${String(actual.documentUuid)}`)}return actual}",
            "const __restore=async()=>{const result={attempted:true,succeeded:false,documentUuid:__before.documentUuid,documentType:__before.documentType,tabId:__before.tabId,identity:null,error:null};try{if(!__before.tabId){throw new Error('Original document tab ID is unavailable')}const activated=await eda.dmt_EditorControl.activateDocument(__before.tabId);if(!activated){throw new Error('Could not reactivate original document tab')}result.identity=await __readVerified(__before.documentUuid,__before.documentType);result.succeeded=true}catch(error){result.error=String(error?.message??error)}return result}",
            "let __visited=null",
            "let __restoration={attempted:false,succeeded:null,documentUuid:__before.documentUuid,documentType:__before.documentType,tabId:__before.tabId,identity:null,error:null}",
            "let __failure=null",
            "let __after=__before",
            "if(__action==='list'){const context=await __read();__after=context.identity;if(__after.projectUuid!==__before.projectUuid||__after.documentUuid!==__before.documentUuid||__after.documentType!==__before.documentType){throw new Error('EasyEDA identity changed while listing board documents')}}else{const matches=__documents.filter(document=>document.uuid===__targetUuid&&document.documentType===__targetType);if(matches.length!==1){throw new Error(`Target board document was not resolved exactly once: ${String(__targetType)}:${String(__targetUuid)}`)}if(__targetUuid===__before.documentUuid&&__targetType===__before.documentType){__visited={...matches[0],tabId:__before.tabId,alreadyActive:true,identity:__before}}else{try{const tabId=await eda.dmt_EditorControl.openDocument(__targetUuid);if(!tabId){throw new Error(`Could not open board document ${__targetUuid}`)}const activated=await eda.dmt_EditorControl.activateDocument(tabId);if(!activated){throw new Error(`Could not activate board document ${__targetUuid}`)}const identity=await __readVerified(__targetUuid,__targetType);__visited={...matches[0],tabId,alreadyActive:false,identity};__after=identity}catch(error){__failure=String(error?.message??error);__restoration=await __restore();__after=__restoration.identity??(await __read()).identity}}}",
            "const __status=__failure===null?'PASS':'FAILED'",
            f"return {{schemaVersion:'{BOARD_NAVIGATION_RESULT_SCHEMA}',adapterVersion:'{BOARD_NAVIGATOR_ADAPTER_VERSION}',status:__status,action:__action,identityBefore:__before,identityAfter:__after,boards:__boards,documents:__documents,targetDocumentUuid:__targetUuid,targetDocumentType:__targetType,visitedDocument:__visited,restoration:__restoration,failure:__failure,saveCalled:false,documentContentMutation:false}}",
        ]
        code = ";".join(statements) + ";"
        if "//" in code or "/*" in code:
            raise ContractError("Board-navigation compilation produced a JavaScript comment")
        return code

    def execute(
        self,
        spec: BoardDocumentNavigationSpec,
        evidence_root: str | Path,
        *,
        identity: Mapping[str, Any] | None = None,
        window_id: str | None = None,
        allow_window_rebind: bool = False,
    ) -> BoardDocumentNavigationResult:
        normalized = spec.normalized()
        evidence_directory = create_evidence_directory(
            evidence_root, f"board-document-{normalized.action}"
        )
        evidence_path = evidence_directory / "envelope.json"
        started_at = utc_now()
        code = self.build_code(normalized, identity)
        request = {
            "schemaVersion": "easyeda.gateway.board-document-navigation-request.v1",
            "adapterVersion": BOARD_NAVIGATOR_ADAPTER_VERSION,
            "registry": self.registry.identity,
            "expectedIdentity": dict(identity or {}),
            "action": normalized.action,
            "targetDocumentUuid": normalized.target_document_uuid,
            "targetDocumentType": normalized.target_document_type,
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
            resolution = resolve_window(
                windows_before,
                requested_window_id=window_id,
                identity=identity,
                allow_rebind=allow_window_rebind,
            )
            target_window = resolution.resolved_window_id
            response = self.client.execute_code(code, target_window)
            health_after = self.client.health()
            result = response.get("result")
            if not isinstance(result, Mapping):
                raise BridgeError("Board document navigation returned a non-object result")
            result_value = result
            if result.get("schemaVersion") != BOARD_NAVIGATION_RESULT_SCHEMA:
                raise BridgeError("Board document navigation result schema mismatch")
            if result.get("adapterVersion") != BOARD_NAVIGATOR_ADAPTER_VERSION:
                raise BridgeError("Board document navigation adapter identity mismatch")
            before = _identity_with_tab(result.get("identityBefore"))
            after = _identity_with_tab(result.get("identityAfter"))
            if before.get("documentType") not in SUPPORTED_DOCUMENT_TYPES:
                raise BridgeError("Board navigation started outside a schematic page or PCB")
            if before.get("projectUuid") != after.get("projectUuid"):
                raise BridgeError("EasyEDA project identity changed during board navigation")
            if result.get("saveCalled") is not False:
                raise BridgeError("Board navigation did not prove saveCalled=false")
            if result.get("documentContentMutation") is not False:
                raise BridgeError("Board navigation reported a document-content mutation")
            boards = result.get("boards")
            documents = result.get("documents")
            restoration = result.get("restoration")
            visited = result.get("visitedDocument")
            if not isinstance(boards, list) or not boards:
                raise BridgeError("Board navigation returned no board inventory")
            if not isinstance(documents, list) or not documents:
                raise BridgeError("Board navigation returned no document inventory")
            if not isinstance(restoration, Mapping):
                raise BridgeError("Board navigation result is missing restoration evidence")
            keys = []
            for item in documents:
                if not isinstance(item, Mapping):
                    raise BridgeError("Board navigation returned an invalid document record")
                key = (item.get("documentType"), str(item.get("uuid") or ""))
                if key[0] not in SUPPORTED_DOCUMENT_TYPES or not key[1]:
                    raise BridgeError("Board navigation returned an invalid document identity")
                keys.append(key)
            if len(set(keys)) != len(keys):
                raise BridgeError("Board navigation returned duplicate document identities")
            if normalized.action == "list":
                if before != after:
                    raise BridgeError("Board document list changed active identity")
            elif result.get("status") == "PASS":
                expected_key = (
                    normalized.target_document_type,
                    normalized.target_document_uuid,
                )
                if (after.get("documentType"), after.get("documentUuid")) != expected_key:
                    raise BridgeError("Board activation selected the wrong target document")
                if expected_key not in keys or not isinstance(visited, Mapping):
                    raise BridgeError("Board activation lacks exact target inventory evidence")
            result_record = {
                "bridgeResponse": response,
                "bridgeResponseSha256": sha256_json(response),
                "navigation": dict(result),
            }
            atomic_write_json(evidence_directory / "result.json", result_record)
            status = "PASS" if result.get("status") == "PASS" else "FAILED"
            envelope = {
                "schemaVersion": BOARD_NAVIGATION_EVIDENCE_SCHEMA,
                "status": status,
                "risk": request["risk"],
                "startedAt": started_at,
                "finishedAt": utc_now(),
                "gatewayVersion": GATEWAY_VERSION,
                "adapterVersion": BOARD_NAVIGATOR_ADAPTER_VERSION,
                "registry": self.registry.identity,
                "identityBefore": before,
                "identityAfter": after,
                "action": normalized.action,
                "targetDocumentUuid": normalized.target_document_uuid,
                "targetDocumentType": normalized.target_document_type,
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
                    "saveCalled": False,
                    "documentContentMutation": False,
                    "automaticRetry": False,
                    "restoration": dict(restoration),
                },
                "files": {
                    "request.json": sha256_file(evidence_directory / "request.json"),
                    "result.json": sha256_file(evidence_directory / "result.json"),
                },
            }
            atomic_write_json(evidence_path, envelope)
            if status != "PASS":
                raise BridgeError(
                    "EasyEDA board document navigation failed after guarded restoration: "
                    f"{result.get('failure')}; evidence: {evidence_path}"
                )
            return BoardDocumentNavigationResult(
                bridge_url=self.client.base_url,
                window_id=target_window,
                action=normalized.action,
                identity_before=before,
                identity_after=after,
                boards=[dict(item) for item in boards if isinstance(item, Mapping)],
                documents=[dict(item) for item in documents if isinstance(item, Mapping)],
                visited_document=dict(visited) if isinstance(visited, Mapping) else None,
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
    spec: BoardDocumentNavigationSpec,
    identity: Mapping[str, Any] | None,
    started_at: str,
    error: Exception,
    result: Mapping[str, Any] | None,
) -> None:
    timeout = isinstance(error, BridgeTimeoutError)
    failure = {
        "schemaVersion": "easyeda.gateway.board-document-navigation-failure.v1",
        "errorType": type(error).__name__,
        "error": str(error),
        "action": spec.action,
        "targetDocumentUuid": spec.target_document_uuid,
        "targetDocumentType": spec.target_document_type,
        "expectedIdentity": dict(identity or {}),
        "bridgeTimedOut": timeout,
        "activePageState": "UNKNOWN_REPROBE_REQUIRED" if timeout else "UNCONFIRMED",
        "automaticRetry": False,
        "partialResult": dict(result) if isinstance(result, Mapping) else None,
    }
    atomic_write_json(evidence_directory / "failure.json", failure)
    files = {
        path.name: sha256_file(path)
        for path in (
            evidence_directory / "request.json",
            evidence_directory / "failure.json",
        )
        if path.is_file()
    }
    atomic_write_json(
        evidence_directory / "envelope.json",
        {
            "schemaVersion": BOARD_NAVIGATION_EVIDENCE_SCHEMA,
            "status": "FAILED",
            "risk": "READ" if spec.action == "list" else "EPHEMERAL_NAVIGATION",
            "startedAt": started_at,
            "finishedAt": utc_now(),
            "gatewayVersion": GATEWAY_VERSION,
            "adapterVersion": BOARD_NAVIGATOR_ADAPTER_VERSION,
            "registry": dict(registry_identity),
            "expectedIdentity": dict(identity or {}),
            "action": spec.action,
            "targetDocumentUuid": spec.target_document_uuid,
            "targetDocumentType": spec.target_document_type,
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
