#!/usr/bin/env python3
"""Unified offline CLI for lifecycle artifacts, gates, and learning sessions."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from hwlifecycle.artifact_store import ArtifactStore
from hwlifecycle.api_registry import registry_identity
from hwlifecycle.bom_sync_adapter import JlcBomSyncAdapter
from hwlifecycle.io_utils import load_json, sha256_json, utc_now, write_json_atomic
from hwlifecycle.learning import (
    HardwareTutorEngine,
    CanvasNativeVisualImportBuilder,
    CanvasPdfVisualImportBuilder,
    LearningCanvasAdapter,
    LearningNotePackageBuilder,
    LearningQuestionWorkflow,
    LearningSessionStore,
    OfficialEasyedaEvidenceProvider,
    resolve_visual_import_route,
    render_learning_note_markdown,
)
from hwlifecycle.orchestrator import LifecycleOrchestrator
from hwlifecycle.state import advance, new_state, record_artifact, validate_state
from hwlifecycle.templates import stage_templates


CANONICAL_PATHS = {
    "requirements": "design/requirements.json",
    "system-architecture": "design/system-architecture.json",
    "verification-strategy": "design/verification-strategy.json",
    "module-profile": "design/modules/module-template.json",
    "interfaces": "design/interfaces.json",
    "electrical-constraints": "design/electrical-constraints.json",
    "schematic-snapshot": "evidence/schematic-snapshot.json",
    "review-report": "reviews/current/review-report.json",
    "review-actions": "reviews/current/review-actions.json",
    "release-gate": "reviews/current/release-gate.json",
    "bom-requirements": "bom/requirements.json",
    "bom-candidates": "bom/candidates.json",
    "final-bom": "bom/final-bom.json",
    "final-bom-digest": "bom/final-bom.digest.json",
    "write-plan": "writeback/current/api-plan.json",
    "acceptance-report": "writeback/current/acceptance-report.json",
    "fresh-write-plan": "writeback/current/fresh-api-plan.json",
    "apply-journal": "writeback/current/apply-journal.json",
    "post-save-readback": "writeback/current/post-save-readback.json",
}


def _print(value: object) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    init_parser = commands.add_parser("init", help="initialize a lifecycle project")
    init_parser.add_argument("--project", required=True, type=Path)
    init_parser.add_argument("--name", required=True)
    init_parser.add_argument("--project-id")

    scaffold = commands.add_parser("scaffold", help="write non-destructive stage templates")
    scaffold.add_argument("--project", required=True, type=Path)
    scaffold.add_argument("--stage", required=True)

    add = commands.add_parser("artifact-add", help="store and register a JSON artifact")
    add.add_argument("--project", required=True, type=Path)
    add.add_argument("--type", required=True, dest="artifact_type")
    add.add_argument("--input", required=True, type=Path)
    add.add_argument("--path")
    add.add_argument("--producer", required=True)
    add.add_argument("--replace", action="store_true")

    evaluate = commands.add_parser("evaluate", help="evaluate and optionally record current gate")
    evaluate.add_argument("--project", required=True, type=Path)
    evaluate.add_argument("--record", action="store_true")

    advance_parser = commands.add_parser("advance", help="advance one passed stage")
    advance_parser.add_argument("--project", required=True, type=Path)
    advance_parser.add_argument("--to", required=True)

    status = commands.add_parser("status", help="show validated lifecycle state")
    status.add_argument("--project", required=True, type=Path)

    learning_session = commands.add_parser("learning-session", help="create a local JLC Hardware Learning learning session")
    learning_session.add_argument("--project", required=True, type=Path)
    learning_session.add_argument("--page-id", required=True)
    learning_session.add_argument("--level", choices=("beginner", "intermediate", "advanced"), default="intermediate")

    learning_ask = commands.add_parser("learning-ask-offline", help="run a saved offline selection through the tutor contracts")
    learning_ask.add_argument("--project", required=True, type=Path)
    learning_ask.add_argument("--session-id", required=True)
    learning_ask.add_argument("--shapes", required=True, type=Path)
    learning_ask.add_argument("--question", required=True)
    learning_ask.add_argument("--canvas-sha256", required=True)
    learning_ask.add_argument("--screenshot-url")
    learning_ask.add_argument("--screenshot-sha256")

    learning_plan = commands.add_parser("learning-live-plan", help="create a manifest-bound read-only learning plan")
    learning_plan.add_argument("--project", required=True, type=Path)
    learning_plan.add_argument("--question", required=True, type=Path)
    learning_plan.add_argument("--manifest", required=True, type=Path)
    learning_plan.add_argument("--gateway-version", default="0.2.0")
    learning_plan.add_argument("--output", required=True, type=Path)

    learning_answer = commands.add_parser(
        "learning-answer-saved",
        help="ingest and idempotently answer a JLC Hardware Learning-saved offline learning question",
    )
    learning_answer.add_argument("--project", required=True, type=Path)
    learning_answer.add_argument("--question-id", required=True)

    learning_resume = commands.add_parser("learning-resume", help="load durable learning-session history")
    learning_resume.add_argument("--project", required=True, type=Path)
    learning_resume.add_argument("--session-id", required=True)

    learning_response = commands.add_parser(
        "learning-dialogue-record",
        help="bind the assistant's normal-conversation response to a saved learning question",
    )
    learning_response.add_argument("--project", required=True, type=Path)
    learning_response.add_argument("--question-id", required=True)
    response_source = learning_response.add_mutually_exclusive_group(required=True)
    response_source.add_argument("--response")
    response_source.add_argument("--response-file", type=Path)

    learning_note = commands.add_parser(
        "learning-note-package",
        help="build a local JLC Hardware Learning/frame/dialogue package and a plan-only Feishu notebook scene",
    )
    learning_note.add_argument("--project", required=True, type=Path)
    learning_note.add_argument("--canvas", required=True, type=Path)
    learning_note.add_argument("--page-id", required=True)
    learning_note.add_argument("--output", required=True, type=Path)
    learning_note.add_argument("--markdown-output", type=Path)

    learning_import = commands.add_parser(
        "learning-page-import-manifest",
        help="disabled by policy: EPRO-derived page images are no longer admitted",
    )
    learning_import.add_argument("--project", required=True, type=Path)
    learning_import.add_argument("--canvas-page-id", required=True)
    learning_import.add_argument("--identity-before", required=True, type=Path)
    learning_import.add_argument("--source-execution", required=True, type=Path)
    learning_import.add_argument("--render-execution", required=True, type=Path)
    learning_import.add_argument("--identity-after", required=True, type=Path)
    learning_import.add_argument("--output", required=True, type=Path)

    learning_project_import = commands.add_parser(
        "learning-project-import-manifest",
        help="disabled by policy: EPRO-derived all-page images are no longer admitted",
    )
    learning_project_import.add_argument("--project", required=True, type=Path)
    learning_project_import.add_argument("--canvas-page-id", required=True)
    learning_project_import.add_argument("--identity-before", required=True, type=Path)
    learning_project_import.add_argument("--source-execution", required=True, type=Path)
    learning_project_import.add_argument("--render-execution", required=True, type=Path)
    learning_project_import.add_argument("--identity-after", required=True, type=Path)
    learning_project_import.add_argument("--output", required=True, type=Path)

    learning_native_visual_import = commands.add_parser(
        "learning-native-visual-import-manifest",
        help="validate an official native EasyEDA current-schematic PNG for JLC Hardware Learning import",
    )
    learning_native_visual_import.add_argument("--project", required=True, type=Path)
    learning_native_visual_import.add_argument("--canvas-page-id", required=True)
    learning_native_visual_import.add_argument("--identity-before", required=True, type=Path)
    learning_native_visual_import.add_argument("--visual-execution", required=True, type=Path)
    learning_native_visual_import.add_argument("--identity-after", required=True, type=Path)
    learning_native_visual_import.add_argument(
        "--visual-mode", required=True, choices=("default", "black-white"),
        help="selected import appearance; default maps to EasyEDA Default, black-white to Black on White",
    )
    learning_native_visual_import.add_argument("--output", required=True, type=Path)

    learning_pdf_visual_import = commands.add_parser(
        "learning-pdf-visual-import-manifest",
        help="validate locally rendered official EasyEDA PDF pages for JLC Hardware Learning import",
    )
    learning_pdf_visual_import.add_argument("--project", required=True, type=Path)
    learning_pdf_visual_import.add_argument("--canvas-page-id", required=True)
    learning_pdf_visual_import.add_argument("--identity-before", required=True, type=Path)
    learning_pdf_visual_import.add_argument("--render-execution", required=True, type=Path)
    learning_pdf_visual_import.add_argument("--identity-after", required=True, type=Path)
    learning_pdf_visual_import.add_argument(
        "--visual-mode", required=True, choices=("default", "black-white"),
        help="selected import appearance; default maps to EasyEDA Default, black-white to Black on White",
    )
    learning_pdf_visual_import.add_argument("--output", required=True, type=Path)

    learning_visual_route = commands.add_parser(
        "learning-visual-import-route",
        help="resolve the default PDF import route or an explicit native-PNG override",
    )
    learning_visual_route.add_argument("--project", required=True, type=Path)
    learning_visual_route.add_argument(
        "--requested-route", choices=("pdf", "png"),
        help="explicit transport override; omit to use the maintained PDF high-resolution default",
    )

    bom_command = commands.add_parser("bom-sync-command", help="render a guarded jlc-bom-sync phase command")
    bom_command.add_argument("--project", required=True, type=Path)
    bom_command.add_argument("--phase", required=True, choices=("freeze", "plan", "acceptance", "apply"))
    bom_command.add_argument("--bom", type=Path)
    bom_command.add_argument("--sheet")
    bom_command.add_argument("--plan", type=Path)
    bom_command.add_argument("--acceptance-report", type=Path)
    bom_command.add_argument("--output", type=Path)
    bom_command.add_argument("--evidence-dir", type=Path)
    bom_command.add_argument("--authorize-save", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        root = args.project.resolve()
        state_path = root / ".hardware-lifecycle" / "project-state.json"
        if args.command == "init":
            state = new_state(args.name, args.project_id)
            write_json_atomic(state_path, state, overwrite=False)
            _print({"ok": True, "state": str(state_path), "projectId": state["project"]["projectId"]})
            return 0

        if args.command == "learning-session":
            session = LearningSessionStore(root).create_session(
                canvas_page_id=args.page_id, learning_level=args.level,
            )
            _print({"ok": True, "session": session})
            return 0
        if args.command == "learning-ask-offline":
            store = LearningSessionStore(root)
            session = store.load_session(args.session_id)
            raw_shapes = json.loads(args.shapes.read_text(encoding="utf-8"))
            shapes = raw_shapes.get("shapes") if isinstance(raw_shapes, dict) else raw_shapes
            if not isinstance(shapes, list):
                raise ValueError("shapes file must be an array or an object with shapes")
            question = LearningCanvasAdapter().build_question(
                session_id=session["sessionId"], canvas_page_id=session["canvasPageId"],
                shapes=shapes, user_question=args.question, learning_level=session["learningLevel"],
                canvas_snapshot_sha256=args.canvas_sha256,
                screenshot_asset_url=args.screenshot_url, screenshot_sha256=args.screenshot_sha256,
            )
            store.save_question(question)
            bundle = OfficialEasyedaEvidenceProvider().offline_bundle(question)
            store.save_evidence(bundle)
            answer = HardwareTutorEngine().answer(question, bundle)
            store.save_answer(answer, bundle)
            run = {
                "schemaVersion": "learning.question-run.v1",
                "runId": f"run:{question['questionId'].split(':', 1)[1]}",
                "questionId": question["questionId"],
                "sessionId": question["sessionId"],
                "canvasPageId": question["selection"]["canvasPageId"],
                "mode": "offline-artifact",
                "questionSha256": sha256_json(question),
                "bundleId": bundle["bundleId"],
                "bundleSha256": sha256_json(bundle),
                "answerId": answer["answerId"],
                "answerSha256": sha256_json(answer),
                "completedAt": utc_now(),
            }
            store.save_question_run(question["questionId"], run)
            _print({"ok": True, "question": question, "evidence": bundle, "answer": answer, "run": run})
            return 0
        if args.command == "learning-live-plan":
            question = load_json(args.question)
            manifest = load_json(args.manifest)
            plan = OfficialEasyedaEvidenceProvider().build_read_plan(
                question, registry_identity=registry_identity(manifest), gateway_version=args.gateway_version,
            )
            write_json_atomic(args.output, plan, overwrite=False)
            _print({"ok": True, "plan": str(args.output.resolve()), "planDigest": plan["planDigest"]})
            return 0
        if args.command == "learning-answer-saved":
            result = LearningQuestionWorkflow(root).answer_saved_offline(args.question_id)
            _print(result)
            return 0
        if args.command == "learning-resume":
            history = LearningSessionStore(root).resume_session(args.session_id)
            _print({"ok": True, "history": history})
            return 0
        if args.command == "learning-dialogue-record":
            response = (
                args.response_file.read_text(encoding="utf-8")
                if args.response_file is not None
                else args.response
            )
            result = LearningSessionStore(root).save_dialogue_response(
                question_id=args.question_id,
                assistant_response=response,
            )
            _print({"ok": True, **result})
            return 0
        if args.command == "learning-note-package":
            package = LearningNotePackageBuilder(root).build(
                canvas_path=args.canvas,
                page_id=args.page_id,
            )
            write_json_atomic(args.output, package)
            markdown_path = None
            if args.markdown_output is not None:
                args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
                args.markdown_output.write_text(
                    render_learning_note_markdown(package),
                    encoding="utf-8",
                    newline="\n",
                )
                markdown_path = str(args.markdown_output.resolve())
            _print({
                "ok": True,
                "package": str(args.output.resolve()),
                "markdown": markdown_path,
                "packageId": package["packageId"],
                "contentSha256": package["contentSha256"],
                "frameCount": len(package["frames"]),
                "dialogueTurnCount": len(package["dialogue"]["turns"]),
                "cloudWriteCount": 0,
            })
            return 0
        if args.command == "learning-page-import-manifest":
            raise ValueError(
                "DISABLED_BY_POLICY: EPRO-derived canvas images are disabled; "
                "use learning-native-visual-import-manifest with an official EasyEDA PNG",
            )
        if args.command == "learning-project-import-manifest":
            raise ValueError(
                "DISABLED_BY_POLICY: EPRO-derived all-page canvas images are disabled; "
                "use an official EasyEDA PNG/PDF visual source",
            )
        if args.command == "learning-native-visual-import-manifest":
            manifest = CanvasNativeVisualImportBuilder().build(
                project_dir=root,
                canvas_page_id=args.canvas_page_id,
                identity_before=load_json(args.identity_before),
                visual_execution=load_json(args.visual_execution),
                identity_after=load_json(args.identity_after),
                visual_mode=args.visual_mode,
            )
            write_json_atomic(args.output, manifest, overwrite=False)
            response = {
                "ok": True,
                "manifest": str(args.output.resolve()),
                "manifestSha256": manifest["manifestSha256"],
            }
            if "operations" in manifest:
                response["pageCount"] = len(manifest["operations"])
                response["operations"] = manifest["operations"]
            else:
                response["tool"] = manifest["tool"]
                response["toolArgs"] = manifest["toolArgs"]
            _print(response)
            return 0
        if args.command == "learning-pdf-visual-import-manifest":
            manifest = CanvasPdfVisualImportBuilder().build(
                project_dir=root,
                canvas_page_id=args.canvas_page_id,
                identity_before=load_json(args.identity_before),
                render_execution=load_json(args.render_execution),
                identity_after=load_json(args.identity_after),
                visual_mode=args.visual_mode,
            )
            write_json_atomic(args.output, manifest, overwrite=False)
            _print({
                "ok": True,
                "manifest": str(args.output.resolve()),
                "manifestSha256": manifest["manifestSha256"],
                "pageCount": len(manifest["operations"]),
                "operations": manifest["operations"],
            })
            return 0
        if args.command == "learning-visual-import-route":
            _print({"ok": True, **resolve_visual_import_route(args.requested_route)})
            return 0
        if args.command == "bom-sync-command":
            adapter = JlcBomSyncAdapter()
            if args.phase == "freeze":
                if not args.bom or not args.sheet or not args.output:
                    raise ValueError("BOM freeze phase requires --bom, --sheet, and --output")
                argv = adapter.freeze(bom=args.bom, sheet=args.sheet, output=args.output)
            elif args.phase == "plan":
                if not args.bom or not args.sheet or not args.output or not args.evidence_dir:
                    raise ValueError("BOM plan phase requires --bom, --sheet, --output, and --evidence-dir")
                argv = adapter.plan(bom=args.bom, sheet=args.sheet, output=args.output, evidence_dir=args.evidence_dir)
            elif args.phase == "acceptance":
                if not args.plan or not args.evidence_dir:
                    raise ValueError("acceptance phase requires --plan and --evidence-dir")
                argv = adapter.acceptance(plan=args.plan, evidence_dir=args.evidence_dir)
            else:
                if not args.plan or not args.acceptance_report or not args.evidence_dir:
                    raise ValueError("apply phase requires --plan, --acceptance-report, and --evidence-dir")
                argv = adapter.apply(
                    plan=args.plan, acceptance_report=args.acceptance_report,
                    evidence_dir=args.evidence_dir, explicit_save_authorization=args.authorize_save,
                )
            _print({"ok": True, "phase": args.phase, "argv": argv, "powershell": adapter.render_powershell(argv)})
            return 0

        state = load_json(state_path)
        errors = validate_state(state)
        if errors:
            raise ValueError("invalid lifecycle state: " + "; ".join(errors))
        if args.command == "scaffold":
            created: list[str] = []
            for artifact_type, template in stage_templates(args.stage).items():
                relative = CANONICAL_PATHS[artifact_type]
                target = root / relative
                if not target.exists():
                    write_json_atomic(target, template, overwrite=False)
                    created.append(relative)
            _print({"ok": True, "stage": args.stage, "created": created})
            return 0
        if args.command == "artifact-add":
            if args.artifact_type not in CANONICAL_PATHS and not args.path:
                raise ValueError("unknown artifact type requires explicit --path")
            payload = load_json(args.input)
            stored = ArtifactStore(root).put_json(
                project_id=state["project"]["projectId"],
                artifact_type=args.artifact_type,
                relative_path=args.path or CANONICAL_PATHS[args.artifact_type],
                payload=payload,
                producer_module=args.producer,
                replace=args.replace,
            )
            updated = record_artifact(
                state,
                state["currentStage"],
                path=stored.payload_path,
                sha256=stored.sha256,
                artifact_type=stored.artifact_type,
            )
            updated["stages"][state["currentStage"]]["artifacts"][-1]["envelope"] = stored.envelope_path
            write_json_atomic(state_path, updated)
            _print({"ok": True, "artifact": stored.state_record()})
            return 0
        if args.command == "evaluate":
            result = LifecycleOrchestrator(root).evaluate(record=args.record)
            _print(result.as_dict())
            return 0 if result.passed else 2
        if args.command == "advance":
            updated = advance(state, args.to)
            write_json_atomic(state_path, updated)
            _print({"ok": True, "currentStage": updated["currentStage"], "revision": updated["revision"]})
            return 0
        if args.command == "status":
            _print({"valid": True, "currentStage": state["currentStage"], "revision": state["revision"], "stages": state["stages"]})
            return 0
        raise ValueError(f"unsupported command: {args.command}")
    except (OSError, ValueError) as exc:
        _print({"ok": False, "error": str(exc)})
        return 2


if __name__ == "__main__":
    sys.exit(main())
