"""Document identity capture and drift protection for read-only operations."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping

from .bridge import BridgeError, OfficialBridgeClient
from .io_utils import utc_now


IDENTITY_CODE = (
    "const document=await eda.dmt_SelectControl.getCurrentDocumentInfo();"
    "const project=await eda.dmt_Project.getCurrentProjectInfo();"
    "return {document,project};"
)


@dataclass(frozen=True)
class DocumentIdentity:
    projectUuid: str
    documentUuid: str
    documentType: str
    capturedAt: str
    bridge: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _normalize_document_type(value: Any) -> str:
    text = str(value or "")
    if text in {"1", "SCHEMATIC_PAGE"}:
        return "SCHEMATIC_PAGE"
    if text in {"3", "PCB"}:
        return "PCB"
    return text


def decode_identity(
    raw: Any,
    *,
    base_url: str,
    window_id: str,
    health: Mapping[str, Any] | None = None,
) -> DocumentIdentity:
    envelope = _mapping(raw)
    document = _mapping(envelope.get("document"))
    project = _mapping(envelope.get("project"))
    project_uuid = str(document.get("parentProjectUuid") or project.get("uuid") or "")
    document_uuid = str(document.get("uuid") or "")
    document_type = _normalize_document_type(document.get("documentType"))
    if not project_uuid or not document_uuid:
        raise BridgeError("official API did not return active project/document UUIDs")
    if not document_type:
        raise BridgeError("official API did not return an active document type")
    return DocumentIdentity(
        projectUuid=project_uuid,
        documentUuid=document_uuid,
        documentType=document_type,
        capturedAt=utc_now(),
        bridge={
            "service": "easyeda-bridge",
            "baseUrl": base_url,
            "windowId": window_id,
            "edaConnected": None if health is None else health.get("edaConnected"),
        },
    )


def capture_identity(client: OfficialBridgeClient, *, window_id: str) -> DocumentIdentity:
    health = client.health()
    raw = client.execute(IDENTITY_CODE, window_id=window_id)
    return decode_identity(
        raw, base_url=client.base_url, window_id=window_id, health=health
    )


def assert_identity(
    expected: DocumentIdentity,
    actual: DocumentIdentity,
    *,
    require_schematic: bool = False,
) -> None:
    mismatches = []
    for field in ("projectUuid", "documentUuid", "documentType"):
        if getattr(expected, field) != getattr(actual, field):
            mismatches.append(
                f"{field}: {getattr(expected, field)!r} != {getattr(actual, field)!r}"
            )
    if expected.bridge.get("windowId") != actual.bridge.get("windowId"):
        mismatches.append("EasyEDA windowId changed")
    if require_schematic and actual.documentType != "SCHEMATIC_PAGE":
        mismatches.append(f"active document is not a schematic page: {actual.documentType}")
    if mismatches:
        raise BridgeError("EasyEDA identity drift: " + "; ".join(mismatches))
