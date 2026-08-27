"""Cross-field validators for learning-canvas JSON contracts."""

from __future__ import annotations

from typing import Any

from ..io_utils import is_sha256


INTENTS = {
    "explain-selection",
    "trace-signal",
    "explain-component",
    "power-path",
    "review-concept",
    "compare-options",
}
LEARNING_LEVELS = {"beginner", "intermediate", "advanced"}
ANNOTATION_KINDS = {"note", "highlight", "rectangle", "arrow"}
FORBIDDEN_ANNOTATION_KEYS = {"image", "imageUrl", "assetUrl", "html", "embed", "video", "slides"}


def _bounds_errors(bounds: Any, path: str) -> list[str]:
    if not isinstance(bounds, dict):
        return [f"{path} must be an object"]
    errors: list[str] = []
    for key in ("x", "y", "width", "height"):
        if not isinstance(bounds.get(key), (int, float)):
            errors.append(f"{path}.{key} must be numeric")
    if isinstance(bounds.get("width"), (int, float)) and bounds["width"] <= 0:
        errors.append(f"{path}.width must be positive")
    if isinstance(bounds.get("height"), (int, float)) and bounds["height"] <= 0:
        errors.append(f"{path}.height must be positive")
    if bounds.get("coordinateSpace") not in {"hardware-learning-page", "asset-pixel", "easyeda-schematic"}:
        errors.append(f"{path}.coordinateSpace is invalid")
    return errors


def validate_selection(selection: Any) -> list[str]:
    if not isinstance(selection, dict):
        return ["selection must be an object"]
    errors: list[str] = []
    if selection.get("version") != 1:
        errors.append("selection.version must be 1")
    if not selection.get("canvasPageId"):
        errors.append("selection.canvasPageId is required")
    selected = selection.get("selectedShapeIds")
    shapes = selection.get("shapes")
    if not isinstance(selected, list) or not selected or len(set(selected)) != len(selected):
        errors.append("selection.selectedShapeIds must be non-empty and unique")
        selected = []
    if not isinstance(shapes, list) or not shapes:
        errors.append("selection.shapes must be non-empty")
        shapes = []
    known_ids: set[str] = set()
    image_count = 0
    envelope_frame_numbers: set[int] = set()
    for index, shape in enumerate(shapes):
        if not isinstance(shape, dict) or not shape.get("shapeId") or not shape.get("shapeType"):
            errors.append(f"selection.shapes[{index}] requires shapeId and shapeType")
            continue
        known_ids.add(shape["shapeId"])
        errors.extend(_bounds_errors(shape.get("pageBounds"), f"selection.shapes[{index}].pageBounds"))
        if shape.get("role") == "source-image":
            image_count += 1
        if shape.get("role") == "selection-frame" and shape.get("learningFrameNumber") is not None:
            frame_number = shape.get("learningFrameNumber")
            if not isinstance(frame_number, int) or isinstance(frame_number, bool) or frame_number <= 0:
                errors.append(f"selection.shapes[{index}].learningFrameNumber must be a positive integer")
            elif frame_number in envelope_frame_numbers:
                errors.append(f"duplicate learningFrameNumber: {frame_number}")
            else:
                envelope_frame_numbers.add(frame_number)
    missing = sorted(set(selected) - known_ids)
    if missing:
        errors.append("selected shapes missing from envelope: " + ", ".join(missing))
    if image_count > 4:
        errors.append("selection may contain at most four source images")
    if not any(shape.get("role") in {"source-image", "selection-frame", "question-note"} for shape in shapes if isinstance(shape, dict)):
        errors.append("selection contains no meaningful hardware-learning shape")
    errors.extend(_bounds_errors(selection.get("unionBounds"), "selection.unionBounds"))
    if not is_sha256(selection.get("canvasSnapshotSha256")):
        errors.append("selection.canvasSnapshotSha256 must be SHA-256")
    screenshot = selection.get("selectionScreenshotSha256")
    if screenshot is not None and not is_sha256(screenshot):
        errors.append("selection.selectionScreenshotSha256 must be SHA-256 or null")
    selected_frame_numbers = selection.get("selectedFrameNumbers")
    if selected_frame_numbers is not None:
        if (
            not isinstance(selected_frame_numbers, list)
            or any(not isinstance(number, int) or isinstance(number, bool) or number <= 0 for number in selected_frame_numbers)
            or len(set(selected_frame_numbers)) != len(selected_frame_numbers)
        ):
            errors.append("selection.selectedFrameNumbers must contain unique positive integers")
        elif set(selected_frame_numbers) != envelope_frame_numbers:
            errors.append("selection.selectedFrameNumbers must match numbered selection-frame envelopes")
    referenced_frame_numbers = selection.get("referencedFrameNumbers")
    if referenced_frame_numbers is not None:
        if (
            not isinstance(referenced_frame_numbers, list)
            or any(not isinstance(number, int) or isinstance(number, bool) or number <= 0 for number in referenced_frame_numbers)
            or len(set(referenced_frame_numbers)) != len(referenced_frame_numbers)
        ):
            errors.append("selection.referencedFrameNumbers must contain unique positive integers")
        elif selected_frame_numbers is None or not set(referenced_frame_numbers).issubset(set(selected_frame_numbers)):
            errors.append("selection.referencedFrameNumbers must be a subset of selectedFrameNumbers")
    return errors


def validate_question(question: Any) -> list[str]:
    if not isinstance(question, dict):
        return ["question must be an object"]
    errors = validate_selection(question.get("selection"))
    if question.get("schemaVersion") != "learning.question.v1":
        errors.append("question schemaVersion is invalid")
    if not str(question.get("questionId", "")).startswith("question:"):
        errors.append("questionId must start with question:")
    if not str(question.get("sessionId", "")).startswith("learning:"):
        errors.append("sessionId must start with learning:")
    if question.get("intent") not in INTENTS:
        errors.append("question intent is invalid")
    text = question.get("userQuestion")
    if not isinstance(text, str) or not text.strip() or len(text) > 4000:
        errors.append("userQuestion must contain 1..4000 characters")
    if question.get("learningLevel") not in LEARNING_LEVELS:
        errors.append("learningLevel is invalid")
    context = question.get("easyedaContext")
    if not isinstance(context, dict) or context.get("mode") not in {"live-verified", "offline-artifact"}:
        errors.append("easyedaContext mode is invalid")
    elif context.get("mode") == "live-verified":
        for field in ("projectUuid", "documentUuid", "documentType", "schematicPageUuid"):
            if not context.get(field):
                errors.append(f"live easyedaContext requires {field}")
    return errors


def validate_evidence_bundle(bundle: Any) -> list[str]:
    if not isinstance(bundle, dict):
        return ["evidence bundle must be an object"]
    errors: list[str] = []
    if bundle.get("schemaVersion") != "learning.evidence-bundle.v1":
        errors.append("evidence bundle schemaVersion is invalid")
    if bundle.get("status") not in {"verified", "partial", "stale", "offline"}:
        errors.append("evidence bundle status is invalid")
    items = bundle.get("items")
    if not isinstance(items, list) or not items:
        errors.append("evidence bundle requires at least one item")
        items = []
    ids: set[str] = set()
    for index, item in enumerate(items):
        if not isinstance(item, dict) or not str(item.get("evidenceId", "")).startswith("evidence:"):
            errors.append(f"items[{index}] has invalid evidenceId")
            continue
        if item["evidenceId"] in ids:
            errors.append(f"duplicate evidenceId: {item['evidenceId']}")
        ids.add(item["evidenceId"])
        if not is_sha256(item.get("sha256")):
            errors.append(f"items[{index}].sha256 is invalid")
    before, after = bundle.get("identityBefore"), bundle.get("identityAfter")
    if bundle.get("status") == "verified" and (not isinstance(before, dict) or not isinstance(after, dict)):
        errors.append("verified bundle requires before/after identity")
    if isinstance(before, dict) and isinstance(after, dict):
        drift = any(before.get(key) != after.get(key) for key in ("projectUuid", "documentUuid", "documentType"))
        if drift and bundle.get("status") != "stale":
            errors.append("identity drift requires stale status")
    return errors


def validate_annotation(command: Any, *, page_id: str | None = None) -> list[str]:
    if not isinstance(command, dict):
        return ["annotation command must be an object"]
    errors: list[str] = []
    if command.get("kind") not in ANNOTATION_KINDS:
        errors.append("annotation kind is not whitelisted")
    forbidden = sorted(FORBIDDEN_ANNOTATION_KEYS.intersection(command))
    if forbidden:
        errors.append("annotation contains generated/embed fields: " + ", ".join(forbidden))
    if not str(command.get("commandId", "")).startswith("annotation-command:"):
        errors.append("annotation commandId is invalid")
    if not str(command.get("operationId", "")).startswith("operation:"):
        errors.append("annotation operationId is invalid")
    if page_id is not None and command.get("pageId") != page_id:
        errors.append("annotation page differs from the learning selection page")
    if not command.get("anchorShapeId"):
        errors.append("annotation anchorShapeId is required")
    if command.get("bounds") is not None:
        errors.extend(_bounds_errors(command["bounds"], "annotation.bounds"))
    return errors


def validate_answer(answer: Any, evidence_bundle: dict[str, Any] | None = None) -> list[str]:
    if not isinstance(answer, dict):
        return ["answer must be an object"]
    errors: list[str] = []
    if answer.get("schemaVersion") != "learning.tutor-answer.v1":
        errors.append("answer schemaVersion is invalid")
    for field in ("summary", "explanation"):
        if not isinstance(answer.get(field), str) or not answer[field].strip():
            errors.append(f"answer {field} is required")
    evidence_ids = {
        item.get("evidenceId") for item in (evidence_bundle or {}).get("items", []) if isinstance(item, dict)
    }
    for claim in answer.get("claims", []):
        refs = claim.get("evidenceIds", []) if isinstance(claim, dict) else []
        if not refs or (evidence_bundle is not None and not set(refs).issubset(evidence_ids)):
            errors.append("every claim must bind existing evidence IDs")
    for command in answer.get("canvasAnnotations", []):
        errors.extend(validate_annotation(command))
    return errors
