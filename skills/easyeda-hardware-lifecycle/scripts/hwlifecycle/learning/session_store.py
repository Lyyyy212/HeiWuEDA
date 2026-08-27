"""Atomic, local-only learning history with idempotent operation records."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import re
from typing import Any
from uuid import uuid4

from ..io_utils import is_sha256, load_json, sha256_file, sha256_json, utc_now, write_json_atomic
from .contracts import LEARNING_LEVELS, validate_answer, validate_evidence_bundle, validate_question


LEGACY_WIDGET_RECORD_SCHEMA = "cowart.learning-question-record.v1"
CANONICAL_WIDGET_RECORD_SCHEMA = "jlc.hardware-learning-question-record.v1"


def _normalize_legacy_question(value: dict[str, Any]) -> dict[str, Any]:
    """Return a canonical question while leaving the saved legacy record untouched."""
    question = deepcopy(value)
    selection = question.get("selection")
    if isinstance(selection, dict):
        if not selection.get("canvasPageId") and selection.get("cowartPageId"):
            selection["canvasPageId"] = selection.pop("cowartPageId")
        for bounds_key in ("unionBounds",):
            bounds = selection.get(bounds_key)
            if isinstance(bounds, dict) and bounds.get("coordinateSpace") == "cowart-page":
                bounds["coordinateSpace"] = "hardware-learning-page"
        for shape in selection.get("shapes", []):
            if not isinstance(shape, dict):
                continue
            bounds = shape.get("pageBounds")
            if isinstance(bounds, dict) and bounds.get("coordinateSpace") == "cowart-page":
                bounds["coordinateSpace"] = "hardware-learning-page"
    return question


def _normalize_legacy_session(value: dict[str, Any]) -> dict[str, Any]:
    session = deepcopy(value)
    if not session.get("canvasPageId") and session.get("cowartPageId"):
        session["canvasPageId"] = session.pop("cowartPageId")
    return session


class LearningSessionStore:
    def __init__(self, project_root: str | Path):
        self.root = Path(project_root).resolve() / ".easyeda-hardware-workbench" / "learning"
        for name in (
            "sessions", "questions", "evidence", "answers", "responses",
            "operations", "runs", "assets", "notes", "lark",
        ):
            (self.root / name).mkdir(parents=True, exist_ok=True)
        schema = self.root / "schema-version.json"
        if not schema.exists():
            write_json_atomic(schema, {"schemaVersion": "learning.storage.v1"}, overwrite=False)

    @staticmethod
    def _id_filename(identifier: str) -> str:
        if not isinstance(identifier, str) or not identifier.strip():
            raise ValueError("learning record identifier must be a non-empty string")
        safe = re.sub(r"[^A-Za-z0-9._-]+", "--", identifier.strip()).strip("-")[:220]
        if not safe:
            raise ValueError("learning record identifier has no safe filename characters")
        return safe + ".json"

    @staticmethod
    def _widget_id_filename(identifier: str) -> str:
        if not isinstance(identifier, str) or not identifier.startswith("question:"):
            raise ValueError("widget questionId must start with question:")
        safe = re.sub(r"[^A-Za-z0-9._-]+", "-", identifier.strip())[:180]
        return safe + ".json"

    def _path(self, category: str, identifier: str) -> Path:
        return self.root / category / self._id_filename(identifier)

    def _save_once(self, category: str, identifier: str, value: dict[str, Any]) -> Path:
        path = self._path(category, identifier)
        if path.exists():
            existing = load_json(path)
            if sha256_json(existing) != sha256_json(value):
                raise ValueError(f"immutable learning record already exists with different content: {identifier}")
            return path
        write_json_atomic(path, value, overwrite=False)
        return path

    def create_session(
        self,
        *,
        canvas_page_id: str,
        learning_level: str,
        project_uuid: str | None = None,
        document_uuid: str | None = None,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        if learning_level not in LEARNING_LEVELS:
            raise ValueError("invalid learning level")
        now = utc_now()
        session = {
            "schemaVersion": "learning.session.v1",
            "sessionId": session_id or f"learning:{uuid4()}",
            "canvasPageId": canvas_page_id,
            "learningLevel": learning_level,
            "projectUuid": project_uuid,
            "documentUuid": document_uuid,
            "questionIds": [],
            "createdAt": now,
            "updatedAt": now,
        }
        write_json_atomic(self._path("sessions", session["sessionId"]), session, overwrite=False)
        return session

    def load_session(self, session_id: str) -> dict[str, Any]:
        return _normalize_legacy_session(load_json(self._path("sessions", session_id)))

    def list_sessions(self, *, canvas_page_id: str | None = None) -> list[dict[str, Any]]:
        sessions: list[dict[str, Any]] = []
        for path in sorted((self.root / "sessions").glob("*.json")):
            session = _normalize_legacy_session(load_json(path))
            if session.get("schemaVersion") != "learning.session.v1":
                raise ValueError(f"invalid learning session record: {path}")
            if canvas_page_id is not None and session.get("canvasPageId") != canvas_page_id:
                continue
            sessions.append(session)
        sessions.sort(key=lambda item: (str(item.get("createdAt", "")), str(item.get("sessionId", ""))))
        return sessions

    def ensure_session_for_question(self, question: dict[str, Any]) -> dict[str, Any]:
        errors = validate_question(question)
        if errors:
            raise ValueError("invalid learning question: " + "; ".join(errors))
        session_id = question["sessionId"]
        session_path = self._path("sessions", session_id)
        context = question["easyedaContext"]
        if not session_path.exists():
            return self.create_session(
                canvas_page_id=question["selection"]["canvasPageId"],
                learning_level=question["learningLevel"],
                project_uuid=context.get("projectUuid"),
                document_uuid=context.get("documentUuid"),
                session_id=session_id,
            )
        session = _normalize_legacy_session(load_json(session_path))
        if session.get("canvasPageId") != question["selection"]["canvasPageId"]:
            raise ValueError("learning session cannot merge questions from different JLC Hardware Learning pages")
        changed = False
        for session_key, context_key in (("projectUuid", "projectUuid"), ("documentUuid", "documentUuid")):
            existing = session.get(session_key)
            incoming = context.get(context_key)
            if existing and incoming and existing != incoming:
                raise ValueError(f"learning session {session_key} drift detected")
            if existing is None and incoming is not None:
                session[session_key] = incoming
                changed = True
        if changed:
            session["updatedAt"] = utc_now()
            write_json_atomic(session_path, session)
        return session

    def load_widget_question_record(self, question_id: str) -> dict[str, Any]:
        path = self.root / "questions" / self._widget_id_filename(question_id)
        record = load_json(path)
        if record.get("schemaVersion") not in {CANONICAL_WIDGET_RECORD_SCHEMA, LEGACY_WIDGET_RECORD_SCHEMA}:
            raise ValueError("widget question record schemaVersion is invalid")
        raw_question = record.get("question")
        if not isinstance(raw_question, dict) or raw_question.get("questionId") != question_id:
            raise ValueError("widget question record identity mismatch")
        question = _normalize_legacy_question(raw_question)
        screenshot = record.get("screenshot")
        if screenshot is not None:
            if not isinstance(screenshot, dict) or not screenshot.get("path") or not screenshot.get("sha256"):
                raise ValueError("widget question screenshot record is invalid")
            screenshot_path = Path(screenshot["path"]).resolve()
            assets_root = (self.root / "assets").resolve()
            if screenshot_path.parent != assets_root:
                raise ValueError("widget question screenshot must stay in the local learning assets directory")
            if not screenshot_path.is_file():
                raise ValueError("widget question screenshot file is missing")
            actual_sha256 = sha256_file(screenshot_path)
            if actual_sha256.lower() != str(screenshot["sha256"]).lower():
                raise ValueError("widget question screenshot digest mismatch")
            selection = question.get("selection")
            if not isinstance(selection, dict):
                raise ValueError("widget question selection is invalid")
            declared = selection.get("selectionScreenshotSha256")
            if declared and str(declared).lower() != actual_sha256.lower():
                raise ValueError("widget selection screenshot digest differs from saved asset")
            selection["selectionScreenshotAssetUrl"] = str(screenshot_path)
            selection["selectionScreenshotSha256"] = actual_sha256
        errors = validate_question(question)
        if errors:
            raise ValueError("invalid widget learning question: " + "; ".join(errors))
        return {"path": str(path), "record": record, "question": question}

    def save_question(self, question: dict[str, Any]) -> Path:
        errors = validate_question(question)
        if errors:
            raise ValueError("invalid learning question: " + "; ".join(errors))
        self.ensure_session_for_question(question)
        path = self._save_once("questions", question["questionId"], question)
        session = self.load_session(question["sessionId"])
        if question["questionId"] not in session["questionIds"]:
            session["questionIds"].append(question["questionId"])
            session["updatedAt"] = utc_now()
            write_json_atomic(self._path("sessions", session["sessionId"]), session)
        return path

    def load_question(self, question_id: str) -> dict[str, Any]:
        return load_json(self._path("questions", question_id))

    def save_evidence(self, bundle: dict[str, Any]) -> Path:
        errors = validate_evidence_bundle(bundle)
        if errors:
            raise ValueError("invalid evidence bundle: " + "; ".join(errors))
        return self._save_once("evidence", bundle["bundleId"], bundle)

    def save_answer(self, answer: dict[str, Any], bundle: dict[str, Any] | None = None) -> Path:
        errors = validate_answer(answer, bundle)
        if errors:
            raise ValueError("invalid tutor answer: " + "; ".join(errors))
        return self._save_once("answers", answer["answerId"], answer)

    def load_evidence(self, bundle_id: str) -> dict[str, Any]:
        return load_json(self._path("evidence", bundle_id))

    def load_answer(self, answer_id: str) -> dict[str, Any]:
        return load_json(self._path("answers", answer_id))

    def dialogue_response(self, question_id: str) -> dict[str, Any] | None:
        path = self._path("responses", question_id)
        return load_json(path) if path.exists() else None

    def save_dialogue_response(
        self,
        *,
        question_id: str,
        assistant_response: str,
        created_at: str | None = None,
    ) -> dict[str, Any]:
        if not isinstance(assistant_response, str) or not assistant_response.strip():
            raise ValueError("assistant response must be non-empty")
        if len(assistant_response) > 20000:
            raise ValueError("assistant response must contain at most 20000 characters")
        question = self.load_question(question_id)
        run = self.question_run(question_id)
        if run is None:
            raise ValueError("learning question must be answered before recording the conversation response")
        existing = self.dialogue_response(question_id)
        if existing:
            if (
                existing.get("assistantResponse") == assistant_response
                and existing.get("sourceTutorAnswerId") == run.get("answerId")
                and existing.get("sourceTutorAnswerSha256") == run.get("answerSha256")
            ):
                return {"path": str(self._path("responses", question_id)), "response": existing}
            raise ValueError(f"immutable learning record already exists with different content: {question_id}")
        selection = question["selection"]
        record = {
            "schemaVersion": "learning.dialogue-response.v1",
            "responseId": f"response:{sha256_json({'questionId': question_id, 'text': assistant_response})[:32]}",
            "questionId": question_id,
            "sessionId": question["sessionId"],
            "canvasPageId": selection["canvasPageId"],
            "frameNumbers": selection.get("selectedFrameNumbers") or [],
            "referencedFrameNumbers": selection.get("referencedFrameNumbers") or [],
            "assistantResponse": assistant_response,
            "sourceTutorAnswerId": run["answerId"],
            "sourceTutorAnswerSha256": run["answerSha256"],
            "createdAt": created_at or utc_now(),
        }
        path = self._save_once("responses", question_id, record)
        return {"path": str(path), "response": record}

    def question_run(self, question_id: str) -> dict[str, Any] | None:
        path = self._path("runs", question_id)
        return load_json(path) if path.exists() else None

    def save_question_run(self, question_id: str, run: dict[str, Any]) -> Path:
        if run.get("schemaVersion") != "learning.question-run.v1" or run.get("questionId") != question_id:
            raise ValueError("invalid learning question run")
        if not str(run.get("sessionId", "")).startswith("learning:"):
            raise ValueError("learning question run sessionId is invalid")
        if not str(run.get("bundleId", "")).startswith("bundle:") or not str(run.get("answerId", "")).startswith("answer:"):
            raise ValueError("learning question run artifact IDs are invalid")
        for field in ("questionSha256", "bundleSha256", "answerSha256"):
            if not is_sha256(run.get(field)):
                raise ValueError(f"learning question run {field} is invalid")
        return self._save_once("runs", question_id, run)

    def resume_session(self, session_id: str) -> dict[str, Any]:
        session = self.load_session(session_id)
        turns: list[dict[str, Any]] = []
        for question_id in session.get("questionIds", []):
            question = load_json(self._path("questions", question_id))
            run = self.question_run(question_id)
            turn: dict[str, Any] = {"question": question, "run": run}
            if run:
                evidence = self.load_evidence(run["bundleId"])
                answer = self.load_answer(run["answerId"])
                if sha256_json(question) != run.get("questionSha256"):
                    raise ValueError("saved learning question digest mismatch")
                if sha256_json(evidence) != run.get("bundleSha256"):
                    raise ValueError("saved learning evidence digest mismatch")
                if sha256_json(answer) != run.get("answerSha256"):
                    raise ValueError("saved tutor answer digest mismatch")
                turn["evidence"] = evidence
                turn["answer"] = answer
            response = self.dialogue_response(question_id)
            if response:
                if response.get("questionId") != question_id or response.get("sessionId") != session_id:
                    raise ValueError("saved learning dialogue response identity mismatch")
                if response.get("canvasPageId") != session.get("canvasPageId"):
                    raise ValueError("saved learning dialogue response page mismatch")
                if run and (
                    response.get("sourceTutorAnswerId") != run.get("answerId")
                    or response.get("sourceTutorAnswerSha256") != run.get("answerSha256")
                ):
                    raise ValueError("saved learning dialogue response tutor-answer binding mismatch")
                turn["dialogueResponse"] = response
            turns.append(turn)
        return {
            "schemaVersion": "learning.session-history.v1",
            "session": session,
            "turns": turns,
        }

    def operation(self, operation_id: str) -> dict[str, Any] | None:
        path = self._path("operations", operation_id)
        return load_json(path) if path.exists() else None

    def record_operation(self, operation_id: str, commands: list[dict[str, Any]], result: Any) -> dict[str, Any]:
        record = {
            "schemaVersion": "learning.operation.v1",
            "operationId": operation_id,
            "commandsSha256": sha256_json(commands),
            "status": "APPLIED",
            "result": result,
            "appliedAt": utc_now(),
        }
        existing = self.operation(operation_id)
        if existing:
            if existing.get("commandsSha256") != record["commandsSha256"]:
                raise ValueError("operationId was already used for different annotation commands")
            return existing
        write_json_atomic(self._path("operations", operation_id), record, overwrite=False)
        return record
