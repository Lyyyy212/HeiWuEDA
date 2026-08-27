"""Build a local, Feishu-ready learning notebook from JLC Hardware Learning and dialogue records."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from ..io_utils import load_json, sha256_file, sha256_json, utc_now
from .session_store import LearningSessionStore


NOTE_PACKAGE_SCHEMA = "learning.note-package.v1"
LARK_PLAN_SCHEMA = "learning.lark-note-plan.v1"
MODULE_INDEX_BOARD_PROFILE = "learning.module-index-board.v1"
DEFAULT_LEARNING_FRAME_MARKER_STYLE = {
    "colorOpacityPercent": 70,
    "numberOpacityPercent": 70,
    "borderWidthScale": 0.5,
    "preserveBounds": True,
    "numberBadgeStyle": {
        "shape": "round_rect",
        "width": 29.2544002532959,
        "height": 28.414939880371094,
        "fontSize": 12,
        "anchor": "frame-top-left",
        "offsetX": -23.912109375,
        "offsetY": -22.4390869140625,
        "colorMode": "follow-frame",
    },
}


def _number(value: Any, fallback: float = 0.0) -> float:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else fallback


def _shape_bounds(shape: dict[str, Any]) -> dict[str, Any]:
    props = shape.get("props") if isinstance(shape.get("props"), dict) else {}
    meta = shape.get("meta") if isinstance(shape.get("meta"), dict) else {}
    saved = meta.get("hardwareLearningBounds")
    if not isinstance(saved, dict):
        saved = meta.get("cowartLearningBounds") if isinstance(meta.get("cowartLearningBounds"), dict) else {}
    width = _number(props.get("w"), _number(saved.get("w")))
    height = _number(props.get("h"), _number(saved.get("h")))
    if width <= 0 or height <= 0:
        raise ValueError(f"JLC Hardware Learning shape {shape.get('id')} has invalid bounds")
    return {
        "x": _number(shape.get("x")),
        "y": _number(shape.get("y")),
        "width": width,
        "height": height,
        "rotation": _number(shape.get("rotation")),
        "coordinateSpace": "hardware-learning-page",
    }


def _intersects(left: dict[str, Any], right: dict[str, Any]) -> bool:
    return not (
        left["x"] + left["width"] <= right["x"]
        or right["x"] + right["width"] <= left["x"]
        or left["y"] + left["height"] <= right["y"]
        or right["y"] + right["height"] <= left["y"]
    )


def _style(shape: dict[str, Any]) -> dict[str, Any]:
    props = shape.get("props") if isinstance(shape.get("props"), dict) else {}
    return {
        key: props.get(key)
        for key in ("color", "labelColor", "fill", "dash", "size", "font", "align", "verticalAlign")
        if props.get(key) is not None
    } | {"opacity": _number(shape.get("opacity"), 1.0)}


class HardwareLearningNotebookReader:
    """Normalize one saved JLC Hardware Learning page without calling the Widget or EasyEDA."""

    def __init__(self, project_root: str | Path):
        self.project_root = Path(project_root).resolve()

    def _relative(self, path: Path) -> str | None:
        try:
            return path.resolve().relative_to(self.project_root).as_posix()
        except ValueError:
            return None

    def _asset_path(self, canvas_path: Path, asset: dict[str, Any]) -> Path | None:
        props = asset.get("props") if isinstance(asset.get("props"), dict) else {}
        name = props.get("name")
        local = canvas_path.parent / "assets" / str(name) if name else None
        if local and local.is_file():
            return local.resolve()
        meta = asset.get("meta") if isinstance(asset.get("meta"), dict) else {}
        visual = meta.get("visualPath")
        if isinstance(visual, str) and Path(visual).is_file():
            return Path(visual).resolve()
        return None

    def read(self, *, canvas_path: str | Path, page_id: str) -> dict[str, Any]:
        path = Path(canvas_path).resolve()
        snapshot = load_json(path)
        if not isinstance(snapshot.get("store"), dict):
            raise ValueError("JLC Hardware Learning canvas snapshot store is missing")
        store = snapshot["store"]
        page = store.get(page_id)
        if not isinstance(page, dict) or page.get("typeName") != "page":
            raise ValueError(f"JLC Hardware Learning page does not exist: {page_id}")

        shapes = [
            deepcopy(record)
            for record in store.values()
            if isinstance(record, dict)
            and record.get("typeName") == "shape"
            and record.get("parentId") == page_id
        ]
        assets = {
            record["id"]: record
            for record in store.values()
            if isinstance(record, dict) and record.get("typeName") == "asset" and record.get("id")
        }

        source_images: list[dict[str, Any]] = []
        for shape in shapes:
            if shape.get("type") != "image":
                continue
            shape_meta = shape.get("meta") if isinstance(shape.get("meta"), dict) else {}
            props = shape.get("props") if isinstance(shape.get("props"), dict) else {}
            asset = assets.get(props.get("assetId"), {})
            asset_meta = asset.get("meta") if isinstance(asset.get("meta"), dict) else {}
            evidence_source = shape_meta.get("evidenceSource") or asset_meta.get("evidenceSource")
            visual_source = shape_meta.get("visualSource") or asset_meta.get("visualSource")
            hardware_evidence = bool(
                shape_meta.get("hardwareLearningEvidence")
                or shape_meta.get("cowartHardwareEvidence")
            )
            if hardware_evidence and (
                evidence_source != "official-easyeda-export" or visual_source != "native-easyeda-png"
            ):
                raise ValueError(
                    f"JLC Hardware Learning hardware evidence image {shape.get('id')} is not an official native EasyEDA PNG"
                )
            asset_path = self._asset_path(path, asset)
            actual_sha256 = sha256_file(asset_path) if asset_path else None
            declared_sha256 = (
                shape_meta.get("evidenceSha256")
                or asset_meta.get("visualSha256")
            )
            if declared_sha256 and actual_sha256 and str(declared_sha256).lower() != actual_sha256.lower():
                raise ValueError(f"JLC Hardware Learning source image digest mismatch: {shape.get('id')}")
            source_images.append({
                "shapeId": shape["id"],
                "assetId": props.get("assetId"),
                "bounds": _shape_bounds(shape),
                "altText": props.get("altText"),
                "locked": bool(shape.get("isLocked")),
                "evidenceSource": evidence_source,
                "visualSource": visual_source,
                "admittedForLearningSync": (
                    evidence_source == "official-easyeda-export"
                    and visual_source == "native-easyeda-png"
                ),
                "assetPath": self._relative(asset_path) if asset_path else None,
                "assetSha256": actual_sha256 or declared_sha256,
                "easyedaIdentity": {
                    "projectUuid": asset_meta.get("projectUuid"),
                    "documentUuid": shape_meta.get("easyedaDocumentUuid") or asset_meta.get("documentUuid"),
                    "documentType": asset_meta.get("documentType"),
                    "capturedAt": asset_meta.get("capturedAt"),
                    "nativeBundlePageIndex": (
                        shape_meta.get("nativeBundlePageIndex") or asset_meta.get("nativeBundlePageIndex")
                    ),
                    "nativeBundleEntryName": asset_meta.get("nativeBundleEntryName"),
                },
            })

        frames: list[dict[str, Any]] = []
        frame_numbers: set[int] = set()
        for shape in shapes:
            meta = shape.get("meta") if isinstance(shape.get("meta"), dict) else {}
            is_frame = meta.get("hardwareLearningFrame") is True or meta.get("cowartLearningFrame") is True
            if not is_frame:
                continue
            number = meta.get("hardwareLearningFrameNumber", meta.get("cowartLearningFrameNumber"))
            if not isinstance(number, int) or isinstance(number, bool) or number <= 0:
                raise ValueError(f"JLC Hardware Learning learning frame {shape.get('id')} has no positive number")
            if number in frame_numbers:
                raise ValueError(f"duplicate JLC Hardware Learning learning frame number on {page_id}: {number}")
            frame_numbers.add(number)
            bounds = _shape_bounds(shape)
            frames.append({
                "frameId": shape["id"],
                "frameNumber": number,
                "title": f"模块{number}",
                "bounds": bounds,
                "style": _style(shape),
                "sourceImageIds": [
                    image["shapeId"] for image in source_images if _intersects(bounds, image["bounds"])
                ],
                "dialogueTurnIds": [],
            })
        frames.sort(key=lambda item: item["frameNumber"])

        annotations: list[dict[str, Any]] = []
        for shape in shapes:
            meta = shape.get("meta") if isinstance(shape.get("meta"), dict) else {}
            is_frame = meta.get("hardwareLearningFrame") is True or meta.get("cowartLearningFrame") is True
            if is_frame or shape.get("type") == "image":
                continue
            is_annotation = (
                meta.get("hardwareLearningAnnotation") is True
                or meta.get("cowartHardwareAnnotation") is True
            )
            if not is_annotation:
                continue
            annotations.append({
                "shapeId": shape["id"],
                "kind": meta.get("hardwareLearningKind") or meta.get("cowartLearningKind") or shape.get("type"),
                "text": meta.get("hardwareLearningText", meta.get("cowartLearningText")),
                "bounds": _shape_bounds(shape),
                "style": _style(shape),
            })

        return {
            "page": {
                "canvasPageId": page_id,
                "name": page.get("name") or page_id,
                "nextFrameNumber": (
                    (page.get("meta") or {}).get("hardwareLearningNextFrameNumber")
                    or (page.get("meta") or {}).get("cowartLearningNextFrameNumber")
                ),
            },
            "canvasSnapshot": {
                "path": self._relative(path),
                "sha256": sha256_file(path),
                "schemaVersion": (snapshot.get("schema") or {}).get("schemaVersion"),
            },
            "sourceImages": source_images,
            "frames": frames,
            "annotations": annotations,
        }


class LearningNotePackageBuilder:
    """Join JLC Hardware Learning frames with durable normal-conversation learning turns."""

    def __init__(self, project_root: str | Path):
        self.project_root = Path(project_root).resolve()
        self.store = LearningSessionStore(self.project_root)

    def _dialogue(self, *, page_id: str, frames: list[dict[str, Any]]) -> dict[str, Any]:
        frames_by_number = {frame["frameNumber"]: frame for frame in frames}
        sessions: list[dict[str, Any]] = []
        turns: list[dict[str, Any]] = []
        for session in self.store.list_sessions(canvas_page_id=page_id):
            history = self.store.resume_session(session["sessionId"])
            sessions.append(history["session"])
            for sequence, turn in enumerate(history["turns"], start=1):
                question = turn["question"]
                selection = question["selection"]
                selected = selection.get("selectedFrameNumbers") or []
                referenced = selection.get("referencedFrameNumbers") or []
                linked_numbers = selected
                missing = sorted(set(linked_numbers) - set(frames_by_number))
                if missing:
                    raise ValueError(
                        f"dialogue question {question['questionId']} references missing frame(s) on {page_id}: "
                        + ", ".join(str(value) for value in missing)
                    )
                response = turn.get("dialogueResponse")
                durable_answer = turn.get("answer")
                turn_id = f"turn:{question['questionId'].split(':', 1)[-1]}"
                frame_links = [{
                    "frameNumber": number,
                    "frameId": frames_by_number[number]["frameId"],
                    "linkSource": "explicit-number" if number in referenced else "canvas-selection",
                } for number in linked_numbers]
                for link in frame_links:
                    frames_by_number[link["frameNumber"]]["dialogueTurnIds"].append(turn_id)
                turns.append({
                    "turnId": turn_id,
                    "sessionId": question["sessionId"],
                    "sequence": sequence,
                    "questionId": question["questionId"],
                    "askedAt": question.get("requestedAt"),
                    "userQuestion": question["userQuestion"],
                    "intent": question["intent"],
                    "learningLevel": question["learningLevel"],
                    "frameLinks": frame_links,
                    "selectedFrameNumbers": selected,
                    "referencedFrameNumbers": referenced,
                    "responseSource": "conversation" if response else ("tutor-baseline" if durable_answer else None),
                    "assistantResponse": (
                        response.get("assistantResponse") if response else (
                            durable_answer.get("explanation") if durable_answer else None
                        )
                    ),
                    "answerSummary": durable_answer.get("summary") if durable_answer else None,
                    "evidenceStatus": (turn.get("evidence") or {}).get("status"),
                    "unknowns": durable_answer.get("unknowns", []) if durable_answer else [],
                })
        return {
            "sessions": sessions,
            "turns": turns,
            "unlinkedTurnIds": [turn["turnId"] for turn in turns if not turn["frameLinks"]],
        }

    @staticmethod
    def _lark_plan(core: dict[str, Any]) -> dict[str, Any]:
        images = [
            {
                "nodeKey": f"image:{item['shapeId']}",
                "kind": "image",
                "assetPath": item["assetPath"],
                "assetSha256": item["assetSha256"],
                "bounds": item["bounds"],
                "locked": True,
            }
            for item in core["sourceImages"]
            if item["admittedForLearningSync"] and item["assetPath"]
        ]
        frames = [
            {
                "nodeKey": f"frame:{item['frameId']}",
                "kind": "learning-frame",
                "label": str(item["frameNumber"]),
                "bounds": item["bounds"],
                "style": item["style"],
            }
            for item in core["frames"]
        ]
        annotations = [
            {
                "nodeKey": f"annotation:{item['shapeId']}",
                "kind": item["kind"],
                "text": item["text"],
                "bounds": item["bounds"],
                "style": item["style"],
            }
            for item in core["annotations"]
        ]
        return {
            "schemaVersion": LARK_PLAN_SCHEMA,
            "mode": "PLAN_ONLY_NO_CLOUD_WRITE",
            "direction": "hardware-learning-to-lark",
            "documentOutline": [
                "工程与图页信息",
                "原理图学习画板",
                "模块索引",
                "提问与解答",
                "模块间关系",
                "待验证项",
                "同步记录",
            ],
            "whiteboard": {
                "strategy": "whiteboard-cli-dsl-with-local-image-assets",
                "sceneFormat": "learning-note-scene.v1",
                "renderedInputFormat": "raw",
                "ownership": "tool-managed-synchronized-board",
                "overwriteRequiresExplicitConfirmation": True,
                "learningFrameMarkerStyleTargets": [
                    "synchronized-learning-board",
                    "module-index-board",
                ],
                "learningFrameMarkerStyle": deepcopy(DEFAULT_LEARNING_FRAME_MARKER_STYLE),
                "moduleIndexBoard": {
                    "profile": MODULE_INDEX_BOARD_PROFILE,
                    "placement": "after-module-index-heading",
                    "contentScope": "source-page-images-and-learning-frames",
                    "nativeZoomAndAnnotation": True,
                    "learningFrameMarkerStyle": deepcopy(DEFAULT_LEARNING_FRAME_MARKER_STYLE),
                },
                "nodes": images + frames + annotations,
            },
            "dialogueIndex": [{
                "turnId": turn["turnId"],
                "questionId": turn["questionId"],
                "frameNumbers": [link["frameNumber"] for link in turn["frameLinks"]],
            } for turn in core["dialogue"]["turns"]],
        }

    def build(self, *, canvas_path: str | Path, page_id: str) -> dict[str, Any]:
        core = HardwareLearningNotebookReader(self.project_root).read(canvas_path=canvas_path, page_id=page_id)
        core["dialogue"] = self._dialogue(page_id=page_id, frames=core["frames"])
        content_sha256 = sha256_json(core)
        package = {
            "schemaVersion": NOTE_PACKAGE_SCHEMA,
            "packageId": f"learning-note:{content_sha256[:32]}",
            "generatedAt": utc_now(),
            "contentSha256": content_sha256,
            **core,
        }
        package["larkPlan"] = self._lark_plan(core)
        return package


def render_learning_note_markdown(package: dict[str, Any]) -> str:
    page = package["page"]
    lines = [
        "# 硬件学习笔记",
        "",
        f"- JLC Hardware Learning 图页：`{page['canvasPageId']}`（{page['name']}）",
        f"- 画板摘要：`{package['canvasSnapshot']['sha256']}`",
        f"- 学习框数量：{len(package['frames'])}",
        f"- 对话回合数量：{len(package['dialogue']['turns'])}",
        "",
        "## 原理图学习画板",
        "",
        "此位置由飞书适配器嵌入原生画板；本地包仅保存经过验证的节点计划，不执行云端写入。",
        "",
        "## 模块索引",
        "",
    ]
    turns_by_id = {turn["turnId"]: turn for turn in package["dialogue"]["turns"]}
    for frame in package["frames"]:
        lines.extend([
            f"### 模块{frame['frameNumber']}",
            "",
            f"- 学习框：`{frame['frameId']}`",
            f"- 关联原理图：{len(frame['sourceImageIds'])} 张",
            f"- 关联对话：{len(frame['dialogueTurnIds'])} 条",
            "",
        ])
        for turn_id in frame["dialogueTurnIds"]:
            turn = turns_by_id[turn_id]
            lines.extend([
                f"#### 问题：{turn['userQuestion']}",
                "",
                turn.get("assistantResponse") or "尚未记录助手回答。",
                "",
            ])
    if package["dialogue"]["unlinkedTurnIds"]:
        lines.extend(["## 未关联学习框的对话", ""])
        for turn_id in package["dialogue"]["unlinkedTurnIds"]:
            turn = turns_by_id[turn_id]
            lines.extend([f"- {turn['userQuestion']}（`{turn_id}`）", ""])
    lines.extend([
        "## 同步记录",
        "",
        f"- 学习笔记内容摘要：`{package['contentSha256']}`",
        f"- 当前模式：`{package['larkPlan']['mode']}`",
        "",
    ])
    return "\n".join(lines)
