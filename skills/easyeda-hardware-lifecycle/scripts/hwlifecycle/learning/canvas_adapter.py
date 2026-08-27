"""Normalize a JLC Hardware Learning selection into a versioned hardware-learning question."""

from __future__ import annotations

from copy import deepcopy
from typing import Any
from uuid import uuid4

from ..io_utils import utc_now
from .contracts import INTENTS, LEARNING_LEVELS, validate_question


def _normalize_bounds(value: dict[str, Any]) -> dict[str, Any]:
    return {
        "x": float(value["x"]),
        "y": float(value["y"]),
        "width": float(value["width"]),
        "height": float(value["height"]),
        "rotation": float(value.get("rotation", 0)),
        "coordinateSpace": value.get("coordinateSpace", "hardware-learning-page"),
    }


def _union(shapes: list[dict[str, Any]]) -> dict[str, Any]:
    focus = [shape for shape in shapes if shape.get("role") != "source-image"] or shapes
    bounds = [shape["pageBounds"] for shape in focus]
    left = min(item["x"] for item in bounds)
    top = min(item["y"] for item in bounds)
    right = max(item["x"] + item["width"] for item in bounds)
    bottom = max(item["y"] + item["height"] for item in bounds)
    return {"x": left, "y": top, "width": right - left, "height": bottom - top, "rotation": 0.0, "coordinateSpace": "hardware-learning-page"}


class LearningCanvasAdapter:
    @staticmethod
    def infer_intent(question: str) -> str:
        lowered = question.lower()
        routes = (
            ("compare-options", ("对比", "比较", "选哪个", "compare", "versus", " vs ")),
            ("power-path", ("电源", "供电", "压降", "power", "supply", "rail")),
            ("trace-signal", ("信号", "走向", "链路", "网络", "网表", "trace", "signal", "net")),
            ("explain-component", ("器件", "芯片", "电阻", "电容", "component", "part")),
            ("review-concept", ("检查", "风险", "合理", "review", "risk")),
        )
        for intent, terms in routes:
            if any(term in lowered for term in terms):
                return intent
        return "explain-selection"

    def build_question(
        self,
        *,
        session_id: str,
        canvas_page_id: str,
        shapes: list[dict[str, Any]],
        user_question: str,
        learning_level: str = "intermediate",
        intent: str | None = None,
        canvas_snapshot_sha256: str,
        screenshot_asset_url: str | None = None,
        screenshot_sha256: str | None = None,
        easyeda_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if learning_level not in LEARNING_LEVELS:
            raise ValueError("learning level must be beginner, intermediate, or advanced")
        selected_intent = intent or self.infer_intent(user_question)
        if selected_intent not in INTENTS:
            raise ValueError(f"unsupported learning intent: {selected_intent}")
        normalized: list[dict[str, Any]] = []
        for shape in shapes:
            item = deepcopy(shape)
            item["pageBounds"] = _normalize_bounds(item["pageBounds"])
            item.setdefault("role", "other")
            item.setdefault("parentShapeId", canvas_page_id)
            item.setdefault("assetUrl", None)
            item.setdefault("text", None)
            item.setdefault("meta", {})
            normalized.append(item)
        now = utc_now()
        context = deepcopy(easyeda_context) if easyeda_context else {
            "mode": "offline-artifact",
            "projectUuid": None,
            "documentUuid": None,
            "documentType": None,
            "schematicPageUuid": None,
            "windowId": None,
            "capturedAt": now,
            "artifactSha256": screenshot_sha256 or canvas_snapshot_sha256,
        }
        context.setdefault("capturedAt", now)
        question = {
            "schemaVersion": "learning.question.v1",
            "questionId": f"question:{uuid4()}",
            "sessionId": session_id,
            "intent": selected_intent,
            "userQuestion": user_question.strip(),
            "learningLevel": learning_level,
            "selection": {
                "version": 1,
                "canvasPageId": canvas_page_id,
                "selectedShapeIds": [shape["shapeId"] for shape in normalized],
                "shapes": normalized,
                "unionBounds": _union(normalized),
                "selectionScreenshotAssetUrl": screenshot_asset_url,
                "selectionScreenshotSha256": screenshot_sha256,
                "capturedAt": now,
                "canvasSnapshotSha256": canvas_snapshot_sha256,
            },
            "easyedaContext": context,
            "requestedAt": now,
        }
        errors = validate_question(question)
        if errors:
            raise ValueError("invalid learning question: " + "; ".join(errors))
        return question
