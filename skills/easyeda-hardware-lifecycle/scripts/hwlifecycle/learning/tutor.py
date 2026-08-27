"""Evidence-bound, level-aware hardware tutoring answer builder."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from ..io_utils import utc_now
from .contracts import validate_answer, validate_evidence_bundle, validate_question


LEVEL_GUIDANCE = {
    "beginner": "先说明模块在做什么，再解释电流或信号从哪里来、到哪里去，并避免省略基础概念。",
    "intermediate": "说明功能、关键连接和判断依据，同时区分已证实信息与仍需读取的参数。",
    "advanced": "聚焦拓扑、约束、边界条件与失效模式，并给出可验证的下一步。",
}


class HardwareTutorEngine:
    def answer(
        self,
        question: dict[str, Any],
        bundle: dict[str, Any],
        *,
        answer_id: str | None = None,
        operation_id: str | None = None,
        created_at: str | None = None,
    ) -> dict[str, Any]:
        question_errors = validate_question(question)
        evidence_errors = validate_evidence_bundle(bundle)
        if question_errors or evidence_errors:
            raise ValueError("invalid tutor input: " + "; ".join(question_errors + evidence_errors))
        usable = bundle["status"] not in {"stale"}
        evidence_ids = [item["evidenceId"] for item in bundle["items"]]
        stable_answer_id = answer_id or f"answer:{uuid4()}"
        stable_suffix = stable_answer_id.split(":", 1)[-1].replace(":", "-")
        intent = question["intent"]
        frame_numbers = question["selection"].get("selectedFrameNumbers") or []
        selection_name = "模块" + "、".join(str(number) for number in frame_numbers) if frame_numbers else "框选区域"
        intent_text = {
            "explain-selection": f"解释{selection_name}的功能和关键关系",
            "trace-signal": f"梳理{selection_name}中的信号路径",
            "explain-component": f"解释{selection_name}内器件的作用与外围连接",
            "power-path": "梳理供电路径、回流与关键约束",
            "review-concept": "检查概念、风险和仍需验证的条件",
            "compare-options": "按相同约束比较候选实现",
        }[intent]
        if usable:
            summary = f"已基于 {len(evidence_ids)} 项证据准备{intent_text}；结论范围仅限当前选区和当前证据。"
            explanation = LEVEL_GUIDANCE[question["learningLevel"]] + " 当前证据已绑定到本次问题，未从其他页面合并网络结论。"
            claims = [{
                "claimId": f"claim:{stable_suffix}:evidence",
                "text": f"本次回答使用了 {len(evidence_ids)} 项与当前问题绑定的证据。",
                "evidenceIds": evidence_ids,
                "confidence": 1.0 if bundle["status"] == "verified" else 0.7,
            }]
            unknowns = ["具体器件参数、引脚含义或网络方向只有在相应证据出现时才能进一步确认。"]
        else:
            summary = "当前页面身份已变化，证据已标记为过期，不能据此给出硬件连接结论。"
            explanation = "请在 EasyEDA 保持目标原理图页激活后重新读取；旧证据仅保留为审计记录。"
            claims = []
            unknowns = ["需要重新确认当前 projectUuid、documentUuid 和 documentType。"]
        union = question["selection"]["unionBounds"]
        anchor = question["selection"]["selectedShapeIds"][0]
        stable_operation_id = operation_id or f"operation:{uuid4()}"
        annotations = [] if not usable else [{
            "commandId": f"annotation-command:{stable_suffix}:note",
            "operationId": stable_operation_id,
            "kind": "note",
            "pageId": question["selection"]["canvasPageId"],
            "anchorShapeId": anchor,
            "text": summary,
            "bounds": {
                "x": union["x"] + union["width"] + 24,
                "y": union["y"],
                "width": 360,
                "height": 180,
                "rotation": 0,
                "coordinateSpace": "hardware-learning-page",
            },
            "targetShapeIds": question["selection"]["selectedShapeIds"],
            "style": {"color": "blue", "fill": "light-blue", "dash": "solid", "size": "m"},
        }]
        answer = {
            "schemaVersion": "learning.tutor-answer.v1",
            "answerId": stable_answer_id,
            "questionId": question["questionId"],
            "summary": summary,
            "explanation": explanation,
            "claims": claims,
            "assumptions": [f"画板{selection_name}代表用户希望讨论的硬件范围。"],
            "unknowns": unknowns,
            "safetyNotes": ["学习解释不能替代电气规则检查、额定值核对或样机测试。"],
            "nextQuestions": ["是否继续读取器件引脚、网络名称和参数来缩小未知项？"],
            "canvasAnnotations": annotations,
            "createdAt": created_at or utc_now(),
        }
        errors = validate_answer(answer, bundle)
        if errors:
            raise ValueError("generated invalid tutor answer: " + "; ".join(errors))
        return answer
