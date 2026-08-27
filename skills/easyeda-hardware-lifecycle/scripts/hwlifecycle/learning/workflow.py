"""Idempotent bridge from JLC Hardware Learning-saved questions to durable tutor artifacts."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..io_utils import sha256_json, utc_now
from .evidence_provider import OfficialEasyedaEvidenceProvider
from .session_store import LearningSessionStore
from .tutor import HardwareTutorEngine


class LearningQuestionWorkflow:
    def __init__(self, project_root: str | Path):
        self.store = LearningSessionStore(project_root)

    def answer_saved_offline(self, question_id: str) -> dict[str, Any]:
        loaded = self.store.load_widget_question_record(question_id)
        record = loaded["record"]
        question = loaded["question"]
        record_sha256 = sha256_json(record)
        question_sha256 = sha256_json(question)
        existing_run = self.store.question_run(question_id)
        if existing_run:
            if existing_run.get("sourceWidgetRecordSha256") != record_sha256:
                raise ValueError("saved widget question changed after it was answered")
            if existing_run.get("questionSha256") != question_sha256:
                raise ValueError("canonical learning question changed after it was answered")
            return self._result(existing_run, replayed=True)

        self.store.save_question(question)
        stable = question_sha256[:32]
        created_at = question.get("requestedAt") or utc_now()
        bundle = OfficialEasyedaEvidenceProvider().offline_bundle(
            question,
            bundle_id=f"bundle:offline:{stable}",
            created_at=created_at,
        )
        self.store.save_evidence(bundle)
        answer = HardwareTutorEngine().answer(
            question,
            bundle,
            answer_id=f"answer:offline:{stable}",
            operation_id=f"operation:learning:{stable}",
            created_at=created_at,
        )
        self.store.save_answer(answer, bundle)
        run = {
            "schemaVersion": "learning.question-run.v1",
            "runId": f"run:offline:{stable}",
            "questionId": question_id,
            "sessionId": question["sessionId"],
            "canvasPageId": question["selection"]["canvasPageId"],
            "mode": "offline-artifact",
            "sourceWidgetRecordPath": loaded["path"],
            "sourceWidgetRecordSha256": record_sha256,
            "questionSha256": question_sha256,
            "bundleId": bundle["bundleId"],
            "bundleSha256": sha256_json(bundle),
            "answerId": answer["answerId"],
            "answerSha256": sha256_json(answer),
            "completedAt": utc_now(),
        }
        self.store.save_question_run(question_id, run)
        return self._result(run, replayed=False)

    def _result(self, run: dict[str, Any], *, replayed: bool) -> dict[str, Any]:
        question = self.store.load_question(run["questionId"])
        evidence = self.store.load_evidence(run["bundleId"])
        answer = self.store.load_answer(run["answerId"])
        if sha256_json(question) != run["questionSha256"]:
            raise ValueError("saved learning question digest mismatch")
        if sha256_json(evidence) != run["bundleSha256"]:
            raise ValueError("saved learning evidence digest mismatch")
        if sha256_json(answer) != run["answerSha256"]:
            raise ValueError("saved tutor answer digest mismatch")
        commands = answer.get("canvasAnnotations", [])
        annotation_request = None
        if commands:
            annotation_request = {
                "action": "insert",
                "operationId": commands[0]["operationId"],
                "pageId": run["canvasPageId"],
                "commands": commands,
            }
        return {
            "ok": True,
            "replayed": replayed,
            "run": run,
            "question": question,
            "evidence": evidence,
            "answer": answer,
            "annotationRequest": annotation_request,
        }
