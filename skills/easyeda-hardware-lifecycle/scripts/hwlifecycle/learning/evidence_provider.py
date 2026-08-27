"""Official-API read plan builder and offline/live learning evidence normalizer."""

from __future__ import annotations

from copy import deepcopy
from typing import Any
from uuid import uuid4

from ..io_utils import sha256_json, utc_now
from .contracts import validate_evidence_bundle, validate_question


LIVE_READ_METHODS = (
    ("DMT_Project.getCurrentProjectInfo#1", [], "project", "read current project identity"),
    ("DMT_SelectControl.getCurrentDocumentInfo#1", [], "document", "read current page identity"),
    ("SCH_PrimitiveComponent.getAll#1", [{"$undefined": True}, False], "components", "read components on the active schematic page"),
    ("SCH_PrimitiveWire.getAll#1", [], "wires", "read wires on the active schematic page"),
    ("SCH_Net.getAllNets#1", [], "nets", "read structured nets on the active schematic page"),
)


def _identity(context: dict[str, Any], gateway_version: str) -> dict[str, Any]:
    return {
        "projectUuid": context.get("projectUuid"),
        "documentUuid": context.get("documentUuid"),
        "documentType": context.get("documentType"),
        "capturedAt": context.get("capturedAt") or utc_now(),
        "bridgeService": "easyeda-bridge",
        "windowId": context.get("windowId"),
        "gatewayVersion": gateway_version,
        "bridgeScriptSha256": None,
    }


def _scope(question: dict[str, Any], identity: dict[str, Any]) -> dict[str, Any]:
    return {
        "projectUuid": identity.get("projectUuid"),
        "documentUuid": identity.get("documentUuid"),
        "primitiveIds": [],
        "netNames": [],
        "shapeIds": question["selection"]["selectedShapeIds"],
    }


def _document_type(value: Any) -> str | None:
    if value in (1, "1", "SCHEMATIC_PAGE"):
        return "SCHEMATIC_PAGE"
    if value is None:
        return None
    return str(value)


def _item(
    question: dict[str, Any],
    identity: dict[str, Any],
    kind: str,
    source: str,
    payload: Any,
    *,
    warnings: list[str] | None = None,
    captured_at: str | None = None,
) -> dict[str, Any]:
    digest = sha256_json(payload)
    return {
        "evidenceId": f"evidence:{kind}:{digest[:16]}",
        "kind": kind,
        "source": source,
        "scope": _scope(question, identity),
        "payload": payload,
        "sha256": digest,
        "capturedAt": captured_at or utc_now(),
        "confidence": 1.0 if source == "easyeda-official-api" else 0.7,
        "warnings": warnings or [],
    }


class OfficialEasyedaEvidenceProvider:
    def build_read_plan(
        self,
        question: dict[str, Any],
        *,
        registry_identity: dict[str, Any],
        gateway_version: str,
    ) -> dict[str, Any]:
        errors = validate_question(question)
        if errors:
            raise ValueError("invalid learning question: " + "; ".join(errors))
        context = question["easyedaContext"]
        if context.get("mode") != "live-verified":
            raise ValueError("live read plan requires live-verified EasyEDA context")
        plan = {
            "schemaVersion": "easyeda.hardware-lifecycle.api-plan.v1",
            "planId": f"plan:learning:{question['questionId'].split(':', 1)[1]}",
            "risk": "READ",
            "registry": deepcopy(registry_identity),
            "identity": _identity(context, gateway_version),
            "calls": [
                {"methodId": method, "effect": "READ", "purpose": purpose, "args": args, "resultKey": key}
                for method, args, key, purpose in LIVE_READ_METHODS
            ],
            "save": False,
        }
        plan["planDigest"] = sha256_json({key: value for key, value in plan.items() if key != "planDigest"})
        return plan

    def offline_bundle(
        self,
        question: dict[str, Any],
        *,
        bundle_id: str | None = None,
        created_at: str | None = None,
    ) -> dict[str, Any]:
        errors = validate_question(question)
        if errors:
            raise ValueError("invalid learning question: " + "; ".join(errors))
        context = question["easyedaContext"]
        identity = {"projectUuid": context.get("projectUuid"), "documentUuid": context.get("documentUuid")}
        stable_time = created_at or utc_now()
        items: list[dict[str, Any]] = []
        screenshot = question["selection"].get("selectionScreenshotAssetUrl")
        if screenshot:
            items.append(_item(question, identity, "schematic-image", "hardware-learning", {
                "assetUrl": screenshot,
                "assetSha256": question["selection"].get("selectionScreenshotSha256"),
            }, captured_at=stable_time))
        for shape in question["selection"]["shapes"]:
            items.append(_item(question, identity, "user-annotation", "hardware-learning", shape, captured_at=stable_time))
        bundle = {
            "schemaVersion": "learning.evidence-bundle.v1",
            "bundleId": bundle_id or f"bundle:{uuid4()}",
            "questionId": question["questionId"],
            "status": "offline",
            "identityBefore": None,
            "identityAfter": None,
            "items": items,
            "warnings": ["离线证据仅能支持图像和用户标注层面的解释，不能证明实际网络连接。"],
            "createdAt": stable_time,
        }
        errors = validate_evidence_bundle(bundle)
        if errors:
            raise ValueError("invalid offline evidence: " + "; ".join(errors))
        return bundle

    def normalize_live_result(self, question: dict[str, Any], execution_result: dict[str, Any]) -> dict[str, Any]:
        raw = execution_result.get("result") if "result" in execution_result else execution_result
        if not isinstance(raw, dict):
            raise ValueError("gateway learning result must be an object")
        before = raw.get("identityBefore")
        after = raw.get("identityAfter")
        results = raw.get("results") or {}
        context = question["easyedaContext"]
        expected = (context.get("projectUuid"), context.get("documentUuid"), _document_type(context.get("documentType")))
        actual_before = ((before or {}).get("projectUuid"), (before or {}).get("documentUuid"), _document_type((before or {}).get("documentType")))
        actual_after = ((after or {}).get("projectUuid"), (after or {}).get("documentUuid"), _document_type((after or {}).get("documentType")))
        stale = actual_before != actual_after or any(value is not None and value != actual_before[index] for index, value in enumerate(expected))
        items: list[dict[str, Any]] = []
        identity = before or {"projectUuid": None, "documentUuid": None}
        mapping = (("components", "component"), ("wires", "wire"), ("nets", "net"))
        for key, kind in mapping:
            payload = results.get(key)
            if payload not in (None, [], {}):
                warnings = ["EasyEDA 异步全局网络刷新期间，wire 自带 net 字段可能短暂过期；网络结论优先使用 SCH_Net 证据。"] if kind == "wire" else []
                items.append(_item(question, identity, kind, "easyeda-official-api", payload, warnings=warnings))
        if not items:
            items.append(_item(question, identity, "schematic-primitive", "easyeda-official-api", {"empty": True}, warnings=["API 未返回可分析的图元。"] ))
        status = "stale" if stale else ("verified" if all(results.get(key) not in (None, []) for key in ("components", "wires", "nets")) else "partial")
        bundle = {
            "schemaVersion": "learning.evidence-bundle.v1",
            "bundleId": f"bundle:{uuid4()}",
            "questionId": question["questionId"],
            "status": status,
            "identityBefore": self._snapshot(before),
            "identityAfter": self._snapshot(after),
            "items": items,
            "warnings": (["EasyEDA 页面身份在读取期间发生变化，本批证据不得用于结论。"] if stale else []),
            "createdAt": utc_now(),
        }
        errors = validate_evidence_bundle(bundle)
        if errors:
            raise ValueError("invalid live evidence: " + "; ".join(errors))
        return bundle

    @staticmethod
    def _snapshot(value: Any) -> dict[str, Any] | None:
        if not isinstance(value, dict):
            return None
        return {
            "projectUuid": str(value.get("projectUuid") or ""),
            "documentUuid": str(value.get("documentUuid") or ""),
            "documentType": _document_type(value.get("documentType")) or "",
            "schematicPageUuid": str(value.get("documentUuid") or "") or None,
            "capturedAt": utc_now(),
        }
