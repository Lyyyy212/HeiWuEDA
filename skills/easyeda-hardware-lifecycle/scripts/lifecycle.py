#!/usr/bin/env python3
"""Manage the durable stage state for an EasyEDA hardware lifecycle project."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from hwlifecycle.io_utils import load_json, write_json_atomic
from hwlifecycle.state import (
    advance,
    invalidate,
    mark_gate,
    new_state,
    record_artifact,
    validate_state,
)


def _print(value: object) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    init_parser = commands.add_parser("init", help="create a new project state")
    init_parser.add_argument("--state", required=True, type=Path)
    init_parser.add_argument("--project-name", required=True)
    init_parser.add_argument("--project-id")
    init_parser.add_argument("--force", action="store_true")

    validate_parser = commands.add_parser("validate", help="validate a project state")
    validate_parser.add_argument("--state", required=True, type=Path)

    status_parser = commands.add_parser("status", help="show current stage and gates")
    status_parser.add_argument("--state", required=True, type=Path)

    artifact_parser = commands.add_parser("artifact", help="record a current-stage artifact")
    artifact_parser.add_argument("--state", required=True, type=Path)
    artifact_parser.add_argument("--stage", required=True)
    artifact_parser.add_argument("--path", required=True)
    artifact_parser.add_argument("--sha256", required=True)
    artifact_parser.add_argument("--type", required=True, dest="artifact_type")

    gate_parser = commands.add_parser("gate", help="record current-stage gate result")
    gate_parser.add_argument("--state", required=True, type=Path)
    gate_parser.add_argument("--stage", required=True)
    gate_parser.add_argument("--status", required=True, choices=("passed", "blocked"))
    gate_parser.add_argument("--evidence", action="append", default=[])
    gate_parser.add_argument("--output-digest")
    gate_parser.add_argument("--note")

    advance_parser = commands.add_parser("advance", help="advance exactly one stage")
    advance_parser.add_argument("--state", required=True, type=Path)
    advance_parser.add_argument("--to", required=True)

    invalidate_parser = commands.add_parser(
        "invalidate", help="invalidate a stage and all downstream stages"
    )
    invalidate_parser.add_argument("--state", required=True, type=Path)
    invalidate_parser.add_argument("--from-stage", required=True)
    invalidate_parser.add_argument("--reason", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "init":
            state = new_state(args.project_name, args.project_id)
            write_json_atomic(args.state, state, overwrite=args.force is True)
            _print({"ok": True, "state": str(args.state), "currentStage": state["currentStage"]})
            return 0

        state = load_json(args.state)
        if args.command == "validate":
            errors = validate_state(state)
            _print({"valid": not errors, "errors": errors, "revision": state.get("revision")})
            return 0 if not errors else 2
        if args.command == "status":
            errors = validate_state(state)
            _print(
                {
                    "valid": not errors,
                    "errors": errors,
                    "revision": state.get("revision"),
                    "currentStage": state.get("currentStage"),
                    "stages": state.get("stages"),
                }
            )
            return 0 if not errors else 2
        if args.command == "artifact":
            updated = record_artifact(
                state,
                args.stage,
                path=args.path,
                sha256=args.sha256,
                artifact_type=args.artifact_type,
            )
        elif args.command == "gate":
            updated = mark_gate(
                state,
                args.stage,
                args.status,
                evidence=args.evidence,
                output_digest=args.output_digest,
                note=args.note,
            )
        elif args.command == "advance":
            updated = advance(state, args.to)
        elif args.command == "invalidate":
            updated = invalidate(state, args.from_stage, args.reason)
        else:
            raise ValueError(f"unsupported command: {args.command}")
        write_json_atomic(args.state, updated)
        _print(
            {
                "ok": True,
                "state": str(args.state),
                "revision": updated["revision"],
                "currentStage": updated["currentStage"],
            }
        )
        return 0
    except (OSError, ValueError) as error:
        _print({"ok": False, "error": str(error)})
        return 2


if __name__ == "__main__":
    sys.exit(main())
