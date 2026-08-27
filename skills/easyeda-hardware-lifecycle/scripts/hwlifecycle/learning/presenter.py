"""Whitelist-only JLC Hardware Learning annotation presenter with idempotent replay."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .contracts import validate_annotation
from .session_store import LearningSessionStore


class CanvasAnswerPresenter:
    def apply(
        self,
        *,
        page_id: str,
        commands: list[dict[str, Any]],
        store: LearningSessionStore,
        apply_callback: Callable[[list[dict[str, Any]]], Any],
    ) -> dict[str, Any]:
        if not commands:
            return {"status": "NO_OP", "applied": 0}
        errors: list[str] = []
        operation_ids = {command.get("operationId") for command in commands if isinstance(command, dict)}
        if len(operation_ids) != 1:
            errors.append("all annotation commands in one presentation must share operationId")
        for command in commands:
            errors.extend(validate_annotation(command, page_id=page_id))
        if errors:
            raise ValueError("annotation presentation blocked: " + "; ".join(errors))
        operation_id = next(iter(operation_ids))
        existing = store.operation(operation_id)
        if existing:
            return {"status": "REPLAYED", "applied": 0, "operation": existing}
        result = apply_callback(commands)
        record = store.record_operation(operation_id, commands, result)
        return {"status": "APPLIED", "applied": len(commands), "operation": record}

