from __future__ import annotations

from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from _gateway_bootstrap import activate_gateway, find_workbench_root
from hwlifecycle.learning import (
    CanvasNativeVisualImportBuilder,
    CanvasPdfVisualImportBuilder,
    CanvasPageImportBuilder,
    CanvasProjectImportBuilder,
    CanvasAnswerPresenter,
    HardwareTutorEngine,
    LearningCanvasAdapter,
    LearningQuestionWorkflow,
    LearningSessionStore,
    OfficialEasyedaEvidenceProvider,
    resolve_visual_import_route,
)
from hwlifecycle.learning.contracts import validate_answer, validate_evidence_bundle, validate_question
from hwlifecycle.io_utils import sha256_file, write_json_atomic
from workbench import main as workbench_main


WORKBENCH_ROOT = find_workbench_root()
FIXTURES = WORKBENCH_ROOT / "materials" / "fixtures" / "learning" / "learning-fixtures.json"
MANIFEST = WORKBENCH_ROOT / "materials" / "manifests" / "api-manifest.json"
activate_gateway()

from easyeda_gateway.contract import ApiRegistry  # noqa: E402
from easyeda_gateway.version import GATEWAY_VERSION  # noqa: E402


SHA = "a" * 64


def fixture_shape(case: dict) -> list[dict]:
    return [{
        "shapeId": f"shape:{case['id']}",
        "shapeType": "image",
        "role": "source-image",
        "pageBounds": {"x": 100, "y": 80, "width": 900, "height": 600},
        "assetUrl": case["asset"],
        "text": None,
        "meta": {"fixture": case["id"]},
    }, {
        "shapeId": f"shape:{case['id']}:frame",
        "shapeType": "geo",
        "role": "selection-frame",
        "pageBounds": {"x": 250, "y": 180, "width": 400, "height": 260},
        "assetUrl": None,
        "text": None,
        "meta": {"hardwareLearningAnnotation": True},
    }]


class VisualImportRoutePolicyTests(unittest.TestCase):
    def test_defaults_to_pdf_high_resolution_route(self) -> None:
        route = resolve_visual_import_route()
        self.assertEqual("pdf", route["route"])
        self.assertEqual("default-policy", route["selectedBy"])
        self.assertEqual("PDF", route["exportFormat"])
        self.assertEqual(6144, route["maxLongEdge"])
        self.assertFalse(route["requiresExplicitRequest"])
        self.assertEqual("learning-pdf-visual-import-manifest", route["manifestCommand"])

    def test_native_png_requires_explicit_route_request(self) -> None:
        route = resolve_visual_import_route("png")
        self.assertEqual("png", route["route"])
        self.assertEqual("explicit-request", route["selectedBy"])
        self.assertTrue(route["requiresExplicitRequest"])
        self.assertEqual("learning-native-visual-import-manifest", route["manifestCommand"])

    def test_cli_uses_pdf_when_transport_is_omitted(self) -> None:
        with TemporaryDirectory() as temporary:
            output = StringIO()
            with redirect_stdout(output):
                exit_code = workbench_main([
                    "learning-visual-import-route",
                    "--project", temporary,
                ])
            response = json.loads(output.getvalue())
            self.assertEqual(0, exit_code)
            self.assertTrue(response["ok"])
            self.assertEqual("pdf", response["route"])
            self.assertEqual("default-policy", response["selectedBy"])


class LearningFixtureTests(unittest.TestCase):
    def test_six_offline_fixture_flows(self) -> None:
        cases = json.loads(FIXTURES.read_text(encoding="utf-8"))["fixtures"]
        self.assertEqual(6, len(cases))
        with TemporaryDirectory() as temporary:
            store = LearningSessionStore(temporary)
            for case in cases:
                session = store.create_session(canvas_page_id=f"page:{case['id']}", learning_level=case["level"])
                question = LearningCanvasAdapter().build_question(
                    session_id=session["sessionId"], canvas_page_id=session["canvasPageId"],
                    shapes=fixture_shape(case), user_question=case["question"],
                    learning_level=case["level"], canvas_snapshot_sha256=SHA,
                    screenshot_asset_url=case["asset"], screenshot_sha256=SHA,
                )
                self.assertEqual(case["expectedIntent"], question["intent"])
                self.assertEqual([], validate_question(question))
                store.save_question(question)
                bundle = OfficialEasyedaEvidenceProvider().offline_bundle(question)
                self.assertEqual([], validate_evidence_bundle(bundle))
                store.save_evidence(bundle)
                answer = HardwareTutorEngine().answer(question, bundle)
                self.assertEqual([], validate_answer(answer, bundle))
                store.save_answer(answer, bundle)
                self.assertIn(question["questionId"], store.load_session(session["sessionId"])["questionIds"])

    def test_numbered_frames_are_validated_and_named_in_durable_answers(self) -> None:
        shapes = fixture_shape({"id": "numbered", "asset": "fixture://numbered.png"})
        shapes[1]["learningFrameNumber"] = 1
        shapes[1]["meta"] = {
            **shapes[1]["meta"],
            "hardwareLearningFrame": True,
            "hardwareLearningFrameNumber": 1,
        }
        question = LearningCanvasAdapter().build_question(
            session_id="learning:jlc-hardware-learning:numbered",
            canvas_page_id="page:numbered",
            shapes=shapes,
            user_question="模块1是什么？",
            canvas_snapshot_sha256=SHA,
        )
        question["selection"]["canvasSelectionVersion"] = 2
        question["selection"]["selectedFrameNumbers"] = [1]
        question["selection"]["referencedFrameNumbers"] = [1]
        self.assertEqual([], validate_question(question))
        bundle = OfficialEasyedaEvidenceProvider().offline_bundle(question)
        answer = HardwareTutorEngine().answer(question, bundle)
        self.assertIn("模块1", answer["summary"])

        question["selection"]["referencedFrameNumbers"] = [2]
        self.assertIn(
            "selection.referencedFrameNumbers must be a subset of selectedFrameNumbers",
            validate_question(question),
        )


class LiveEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.registry = ApiRegistry.from_file(MANIFEST)

    def live_question(self) -> dict:
        return LearningCanvasAdapter().build_question(
            session_id="learning:live", canvas_page_id="page:live",
            shapes=fixture_shape({"id": "live", "asset": "fixture://live.png"}),
            user_question="追踪这个信号", canvas_snapshot_sha256=SHA,
            easyeda_context={
                "mode": "live-verified", "projectUuid": "project-1", "documentUuid": "page-1",
                "documentType": "SCHEMATIC_PAGE", "schematicPageUuid": "page-1", "windowId": "window-1",
                "capturedAt": "2026-08-24T00:00:00Z", "artifactSha256": SHA,
            },
        )

    def test_live_read_plan_is_manifest_valid_and_read_only(self) -> None:
        plan = OfficialEasyedaEvidenceProvider().build_read_plan(
            self.live_question(), registry_identity=self.registry.identity, gateway_version=GATEWAY_VERSION,
        )
        report = self.registry.validate_plan(plan)
        self.assertTrue(report.valid, report.as_dict())
        self.assertTrue(report.executable)
        self.assertEqual({"READ"}, {call["effect"] for call in plan["calls"]})
        self.assertFalse(plan["save"])

    def test_page_switch_marks_bundle_stale(self) -> None:
        raw = {
            "identityBefore": {"projectUuid": "project-1", "documentUuid": "page-1", "documentType": 1},
            "identityAfter": {"projectUuid": "project-1", "documentUuid": "page-2", "documentType": 1},
            "results": {"components": [{"designator": "U1"}], "wires": [], "nets": []},
        }
        bundle = OfficialEasyedaEvidenceProvider().normalize_live_result(self.live_question(), raw)
        self.assertEqual("stale", bundle["status"])
        answer = HardwareTutorEngine().answer(self.live_question(), bundle)
        self.assertEqual([], answer["claims"])
        self.assertEqual([], answer["canvasAnnotations"])


class PresenterTests(unittest.TestCase):
    def test_annotation_apply_is_whitelisted_and_idempotent(self) -> None:
        command = {
            "commandId": "annotation-command:1", "operationId": "operation:1", "kind": "note",
            "pageId": "page:1", "anchorShapeId": "shape:1", "text": "explain",
            "bounds": {"x": 0, "y": 0, "width": 100, "height": 60, "coordinateSpace": "hardware-learning-page"},
            "targetShapeIds": ["shape:1"], "style": {"color": "blue"},
        }
        with TemporaryDirectory() as temporary:
            store = LearningSessionStore(temporary)
            applied: list[list[dict]] = []
            presenter = CanvasAnswerPresenter()
            first = presenter.apply(page_id="page:1", commands=[command], store=store, apply_callback=lambda value: applied.append(value) or {"ok": True})
            second = presenter.apply(page_id="page:1", commands=[command], store=store, apply_callback=lambda value: applied.append(value))
            self.assertEqual("APPLIED", first["status"])
            self.assertEqual("REPLAYED", second["status"])
            self.assertEqual(1, len(applied))

            forbidden = dict(command, commandId="annotation-command:2", operationId="operation:2", kind="image", imageUrl="https://example.invalid/generated.png")
            with self.assertRaisesRegex(ValueError, "blocked"):
                presenter.apply(page_id="page:1", commands=[forbidden], store=store, apply_callback=lambda value: value)


class SavedQuestionWorkflowTests(unittest.TestCase):
    @staticmethod
    def _write_widget_question(root: Path, *, session_id: str, page_id: str, level: str = "intermediate") -> dict:
        store = LearningSessionStore(root)
        screenshot_path = store.root / "assets" / f"{page_id.replace(':', '-')}.png"
        screenshot_path.write_bytes(b"\x89PNG\r\n\x1a\nfixture")
        screenshot_sha256 = sha256_file(screenshot_path)
        question = LearningCanvasAdapter().build_question(
            session_id=session_id,
            canvas_page_id=page_id,
            shapes=fixture_shape({"id": page_id.replace(":", "-"), "asset": "fixture://saved.png"}),
            user_question="这个选区的信号路径怎么工作？",
            learning_level=level,
            canvas_snapshot_sha256=SHA,
            screenshot_sha256=screenshot_sha256,
        )
        record = {
            "schemaVersion": "jlc.hardware-learning-question-record.v1",
            "question": question,
            "screenshot": {"path": str(screenshot_path.resolve()), "sha256": screenshot_sha256},
            "savedAt": question["requestedAt"],
        }
        widget_path = store.root / "questions" / store._widget_id_filename(question["questionId"])
        write_json_atomic(widget_path, record, overwrite=False)
        return question

    def test_saved_widget_question_is_answered_idempotently_and_resumed(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            session_id = "learning:jlc-hardware-learning:page-e2e"
            first_question = self._write_widget_question(root, session_id=session_id, page_id="page:e2e")
            workflow = LearningQuestionWorkflow(root)
            first = workflow.answer_saved_offline(first_question["questionId"])
            second = workflow.answer_saved_offline(first_question["questionId"])
            self.assertFalse(first["replayed"])
            self.assertTrue(second["replayed"])
            self.assertEqual(first["answer"]["answerId"], second["answer"]["answerId"])
            self.assertEqual(first["evidence"]["bundleId"], second["evidence"]["bundleId"])
            self.assertEqual("insert", first["annotationRequest"]["action"])
            self.assertEqual("page:e2e", first["annotationRequest"]["pageId"])
            self.assertEqual({"note"}, {command["kind"] for command in first["annotationRequest"]["commands"]})

            second_question = self._write_widget_question(
                root,
                session_id=session_id,
                page_id="page:e2e",
                level="advanced",
            )
            LearningQuestionWorkflow(root).answer_saved_offline(second_question["questionId"])
            history = LearningSessionStore(root).resume_session(session_id)
            self.assertEqual(2, len(history["turns"]))
            self.assertEqual(
                [first_question["questionId"], second_question["questionId"]],
                [turn["question"]["questionId"] for turn in history["turns"]],
            )
            self.assertTrue(all(turn["answer"]["questionId"] == turn["question"]["questionId"] for turn in history["turns"]))

    def test_legacy_widget_question_is_read_as_canonical_jlc_contract(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            question = self._write_widget_question(
                root,
                session_id="learning:legacy:page",
                page_id="page:legacy",
            )
            store = LearningSessionStore(root)
            widget_path = store.root / "questions" / store._widget_id_filename(question["questionId"])
            record = json.loads(widget_path.read_text(encoding="utf-8"))
            record["schemaVersion"] = "cowart.learning-question-record.v1"
            selection = record["question"]["selection"]
            selection["cowartPageId"] = selection.pop("canvasPageId")
            selection["unionBounds"]["coordinateSpace"] = "cowart-page"
            for shape in selection["shapes"]:
                shape["pageBounds"]["coordinateSpace"] = "cowart-page"
            write_json_atomic(widget_path, record)

            loaded = store.load_widget_question_record(question["questionId"])
            canonical = loaded["question"]["selection"]
            self.assertEqual("page:legacy", canonical["canvasPageId"])
            self.assertNotIn("cowartPageId", canonical)
            self.assertEqual("hardware-learning-page", canonical["unionBounds"]["coordinateSpace"])
            self.assertEqual("cowart.learning-question-record.v1", loaded["record"]["schemaVersion"])

    def test_saved_widget_screenshot_digest_is_verified(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            question = self._write_widget_question(root, session_id="learning:jlc-hardware-learning:tamper", page_id="page:tamper")
            store = LearningSessionStore(root)
            record = store.load_widget_question_record(question["questionId"])
            Path(record["record"]["screenshot"]["path"]).write_bytes(b"tampered")
            with self.assertRaisesRegex(ValueError, "digest mismatch"):
                LearningQuestionWorkflow(root).answer_saved_offline(question["questionId"])

    def test_session_refuses_cross_page_merge(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            session_id = "learning:jlc-hardware-learning:single-page"
            first = self._write_widget_question(root, session_id=session_id, page_id="page:one")
            LearningQuestionWorkflow(root).answer_saved_offline(first["questionId"])
            second = self._write_widget_question(root, session_id=session_id, page_id="page:two")
            with self.assertRaisesRegex(ValueError, "different JLC Hardware Learning pages"):
                LearningQuestionWorkflow(root).answer_saved_offline(second["questionId"])

    def test_workbench_cli_answers_and_resumes_widget_question(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            session_id = "learning:jlc-hardware-learning:cli"
            question = self._write_widget_question(root, session_id=session_id, page_id="page:cli")
            output = StringIO()
            with redirect_stdout(output):
                exit_code = workbench_main([
                    "learning-answer-saved",
                    "--project", str(root),
                    "--question-id", question["questionId"],
                ])
            self.assertEqual(0, exit_code)
            result = json.loads(output.getvalue())
            self.assertTrue(result["ok"])
            self.assertEqual("insert", result["annotationRequest"]["action"])

            output = StringIO()
            with redirect_stdout(output):
                exit_code = workbench_main([
                    "learning-resume",
                    "--project", str(root),
                    "--session-id", session_id,
                ])
            self.assertEqual(0, exit_code)
            history = json.loads(output.getvalue())["history"]
            self.assertEqual(question["questionId"], history["turns"][0]["question"]["questionId"])


@unittest.skip("legacy EPRO canvas-image route is disabled by product policy")
class CanvasPageImportTests(unittest.TestCase):
    @staticmethod
    def _records(root: Path) -> tuple[dict, dict, dict, dict]:
        identity = {
            "projectUuid": "project-guarded",
            "documentUuid": "document-guarded",
            "documentType": 1,
        }
        source = root / "active-document-source.epro"
        source.write_bytes(b"guarded-epro-fixture")
        png = root / "source-render.png"
        png.write_bytes(
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
            b"\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00"
            b"\x1f\x15\xc4\x89"
        )
        source_envelope_path = root / "source-envelope.json"
        write_json_atomic(source_envelope_path, {
            "schemaVersion": "easyeda.gateway.formal-export-evidence.v1",
            "status": "PASS",
            "identity": identity,
            "sourcePreservation": {"sourceUnchanged": True},
        })
        render_envelope_path = root / "render-envelope.json"
        write_json_atomic(render_envelope_path, {
            "schemaVersion": "easyeda.gateway.offline-source-render.v1",
            "status": "PASS",
            "easyedaApiCallCount": 0,
            "quality": {
                "structuralStatus": "PASS",
                "visualStatus": "UNQUALIFIED",
                "visualReviewRequired": True,
                "limitations": ["Visual comparison is required."],
            },
            "spec": {
                "documentUuid": identity["documentUuid"],
                "renderPng": True,
            },
        })
        source_execution = {
            "success": True,
            "schemaVersion": "easyeda.gateway.formal-export-execution.v1",
            "identity": identity,
            "spec": {"kind": "source", "variant": "epro"},
            "artifact": {"path": str(source), "sha256": sha256_file(source)},
            "evidencePath": str(source_envelope_path),
        }
        render_execution = {
            "success": True,
            "schemaVersion": "easyeda.gateway.offline-source-render.v1",
            "executionModel": "LOCAL_ONLY_NO_EASYEDA_CALLS",
            "source": {"path": str(source), "sha256": sha256_file(source)},
            "png": {"path": str(png), "sha256": sha256_file(png)},
            "evidencePath": str(render_envelope_path),
        }
        return identity, source_execution, render_execution, identity.copy()

    def test_builds_exact_official_export_tool_arguments(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            before, source, render, after = self._records(root)
            manifest = CanvasPageImportBuilder().build(
                project_dir=root,
                canvas_page_id="page:learning",
                identity_before=before,
                source_execution=source,
                render_execution=render,
                identity_after=after,
            )

            self.assertEqual("READY", manifest["status"])
            self.assertTrue(manifest["reviewRequired"])
            self.assertEqual("UNQUALIFIED", manifest["render"]["quality"]["visualStatus"])
            self.assertEqual(
                "UNQUALIFIED",
                manifest["toolArgs"]["assetMeta"]["renderQuality"]["visualStatus"],
            )
            self.assertEqual("mcp__jlc_hardware_learning_mcp__insert_hardware_learning_image", manifest["tool"])
            self.assertEqual("official-easyeda-export", manifest["toolArgs"]["evidenceSource"])
            self.assertFalse(manifest["toolArgs"]["replaceAiImageHolder"])
            self.assertEqual("page:learning", manifest["toolArgs"]["pageId"])
            self.assertEqual(
                "current-page-from-epro",
                manifest["toolArgs"]["assetMeta"]["scope"],
            )
            self.assertEqual(
                "official-easyeda-export",
                manifest["toolArgs"]["assetMeta"]["evidenceSource"],
            )
            self.assertEqual(before["documentUuid"], manifest["easyedaIdentity"]["documentUuid"])

    def test_refuses_identity_drift(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            before, source, render, after = self._records(root)
            after["documentUuid"] = "different-page"

            with self.assertRaisesRegex(ValueError, "identity changed"):
                CanvasPageImportBuilder().build(
                    project_dir=root,
                    canvas_page_id="page:learning",
                    identity_before=before,
                    source_execution=source,
                    render_execution=render,
                    identity_after=after,
                )

    def test_refuses_tampered_png(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            before, source, render, after = self._records(root)
            Path(render["png"]["path"]).write_bytes(b"tampered")

            with self.assertRaisesRegex(ValueError, "digest mismatch"):
                CanvasPageImportBuilder().build(
                    project_dir=root,
                    canvas_page_id="page:learning",
                    identity_before=before,
                    source_execution=source,
                    render_execution=render,
                    identity_after=after,
                )

    def test_accepts_formal_adapters_verified_published_source_copy(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            before, source, render, after = self._records(root)
            source_path = Path(source["artifact"]["path"])
            published = root / "published.epro"
            published.write_bytes(source_path.read_bytes())
            source["publishedOutput"] = str(published)
            envelope_path = Path(source["evidencePath"])
            envelope = json.loads(envelope_path.read_text(encoding="utf-8"))
            envelope["publishedOutput"] = {
                "path": str(published),
                "sha256": sha256_file(published),
            }
            write_json_atomic(envelope_path, envelope)
            render["source"] = {
                "path": str(published),
                "sha256": sha256_file(published),
            }

            manifest = CanvasPageImportBuilder().build(
                project_dir=root,
                canvas_page_id="page:learning",
                identity_before=before,
                source_execution=source,
                render_execution=render,
                identity_after=after,
            )

            self.assertEqual("READY", manifest["status"])
            self.assertEqual(source_path.resolve(), Path(manifest["source"]["path"]))

    def test_cli_writes_no_overwrite_manifest(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            before, source, render, after = self._records(root)
            inputs = {}
            for name, value in {
                "before": before,
                "source": source,
                "render": render,
                "after": after,
            }.items():
                path = root / f"{name}.json"
                write_json_atomic(path, value)
                inputs[name] = path
            output_path = root / "import-manifest.json"
            output = StringIO()
            with redirect_stdout(output):
                exit_code = workbench_main([
                    "learning-page-import-manifest",
                    "--project", str(root),
                    "--canvas-page-id", "page:learning",
                    "--identity-before", str(inputs["before"]),
                    "--source-execution", str(inputs["source"]),
                    "--render-execution", str(inputs["render"]),
                    "--identity-after", str(inputs["after"]),
                    "--output", str(output_path),
                ])
            self.assertEqual(0, exit_code)
            self.assertTrue(output_path.is_file())
            self.assertEqual("page:learning", json.loads(output.getvalue())["toolArgs"]["pageId"])

            with redirect_stdout(StringIO()):
                replay_exit = workbench_main([
                    "learning-page-import-manifest",
                    "--project", str(root),
                    "--canvas-page-id", "page:learning",
                    "--identity-before", str(inputs["before"]),
                    "--source-execution", str(inputs["source"]),
                    "--render-execution", str(inputs["render"]),
                    "--identity-after", str(inputs["after"]),
                    "--output", str(output_path),
                ])
            self.assertEqual(2, replay_exit)


@unittest.skip("legacy EPRO all-page canvas-image route is disabled by product policy")
class CanvasProjectImportTests(unittest.TestCase):
    @staticmethod
    def _records(root: Path) -> tuple[dict, dict, dict, dict]:
        identity = {
            "projectUuid": "project-guarded",
            "documentUuid": "page-1",
            "documentType": 1,
        }
        source = root / "active-project-source.epro"
        source.write_bytes(b"guarded-project-epro-fixture")
        source_sha256 = sha256_file(source)
        pages = [
            {
                "documentUuid": "page-1",
                "schematicUuid": "schematic-1",
                "schematicName": "Power",
                "pageName": "Input",
            },
            {
                "documentUuid": "page-2",
                "schematicUuid": "schematic-1",
                "schematicName": "Power",
                "pageName": "Control",
            },
        ]
        source_envelope_path = root / "project-source-envelope.json"
        write_json_atomic(source_envelope_path, {
            "schemaVersion": "easyeda.gateway.formal-export-evidence.v1",
            "status": "PASS",
            "identity": identity,
            "projectTreePreservation": {
                "treeUnchanged": True,
                "pageUuidSetMatch": True,
            },
        })
        source_execution = {
            "success": True,
            "schemaVersion": "easyeda.gateway.formal-export-execution.v1",
            "identity": identity,
            "spec": {"kind": "project-source", "variant": "epro"},
            "artifact": {
                "path": str(source),
                "sha256": source_sha256,
                "sheets": pages,
            },
            "evidencePath": str(source_envelope_path),
        }
        rendered_pages = []
        for index, page in enumerate(pages, start=1):
            png = root / f"page-{index}.png"
            png.write_bytes(
                b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
                + index.to_bytes(4, "big")
            )
            render_envelope_path = root / f"page-{index}-render-envelope.json"
            write_json_atomic(render_envelope_path, {
                "schemaVersion": "easyeda.gateway.offline-source-render.v1",
                "status": "PASS",
                "easyedaApiCallCount": 0,
                "quality": {
                    "structuralStatus": "PASS",
                    "visualStatus": "UNQUALIFIED",
                    "visualReviewRequired": True,
                    "limitations": ["Visual comparison is required."],
                },
                "spec": {
                    "documentUuid": page["documentUuid"],
                    "renderPng": True,
                },
            })
            page_render = {
                "schemaVersion": "easyeda.gateway.offline-source-render.v1",
                "executionModel": "LOCAL_ONLY_NO_EASYEDA_CALLS",
                "source": {"path": str(source), "sha256": source_sha256},
                "png": {"path": str(png), "sha256": sha256_file(png)},
                "publishedPng": str(png),
                "evidencePath": str(render_envelope_path),
            }
            rendered_pages.append({
                **page,
                "index": index,
                "png": page_render["png"],
                "publishedPng": str(png),
                "renderEvidencePath": str(render_envelope_path),
                "renderExecution": page_render,
            })
        batch_envelope_path = root / "batch-render-envelope.json"
        write_json_atomic(batch_envelope_path, {
            "schemaVersion": "easyeda.gateway.offline-project-source-render.v1",
            "status": "PASS",
            "easyedaApiCallCount": 0,
            "quality": {
                "structuralStatus": "PASS",
                "visualStatus": "UNQUALIFIED",
                "visualReviewRequired": True,
                "limitations": ["Project pages require visual comparison."],
            },
        })
        render_execution = {
            "success": True,
            "schemaVersion": "easyeda.gateway.offline-project-source-render.v1",
            "executionModel": "LOCAL_ONLY_NO_EASYEDA_CALLS",
            "easyedaApiCallCount": 0,
            "source": {"path": str(source), "sha256": source_sha256},
            "pageCount": len(rendered_pages),
            "pages": rendered_pages,
            "evidencePath": str(batch_envelope_path),
        }
        return identity, source_execution, render_execution, identity.copy()

    def test_builds_ordered_project_import_operations(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            before, source, render, after = self._records(root)
            manifest = CanvasProjectImportBuilder().build(
                project_dir=root,
                canvas_page_id="page:learning",
                identity_before=before,
                source_execution=source,
                render_execution=render,
                identity_after=after,
            )

            self.assertEqual("READY", manifest["status"])
            self.assertTrue(manifest["reviewRequired"])
            self.assertEqual("UNQUALIFIED", manifest["render"]["quality"]["visualStatus"])
            self.assertEqual(2, len(manifest["operations"]))
            self.assertEqual(
                ["page-1", "page-2"],
                [item["documentUuid"] for item in manifest["operations"]],
            )
            self.assertTrue(manifest["layout"]["anchorFromPreviousResult"])
            self.assertEqual(
                "current-project-from-epro",
                manifest["operations"][0]["toolArgs"]["assetMeta"]["scope"],
            )
            self.assertEqual(
                "UNQUALIFIED",
                manifest["operations"][0]["toolArgs"]["assetMeta"]["renderQuality"]["visualStatus"],
            )

    def test_refuses_project_render_page_reordering(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            before, source, render, after = self._records(root)
            render["pages"].reverse()

            with self.assertRaisesRegex(ValueError, "order or UUIDs"):
                CanvasProjectImportBuilder().build(
                    project_dir=root,
                    canvas_page_id="page:learning",
                    identity_before=before,
                    source_execution=source,
                    render_execution=render,
                    identity_after=after,
                )

    def test_cli_writes_project_import_manifest(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            before, source, render, after = self._records(root)
            inputs = {}
            for name, value in {
                "before": before,
                "source": source,
                "render": render,
                "after": after,
            }.items():
                path = root / f"{name}.json"
                write_json_atomic(path, value)
                inputs[name] = path
            output_path = root / "project-import-manifest.json"
            output = StringIO()
            with redirect_stdout(output):
                exit_code = workbench_main([
                    "learning-project-import-manifest",
                    "--project", str(root),
                    "--canvas-page-id", "page:learning",
                    "--identity-before", str(inputs["before"]),
                    "--source-execution", str(inputs["source"]),
                    "--render-execution", str(inputs["render"]),
                    "--identity-after", str(inputs["after"]),
                    "--output", str(output_path),
                ])

            self.assertEqual(0, exit_code)
            self.assertEqual(2, json.loads(output.getvalue())["pageCount"])
            self.assertTrue(output_path.is_file())


class CanvasNativeVisualImportTests(unittest.TestCase):
    @staticmethod
    def _records(root: Path) -> tuple[dict, dict, dict]:
        identity = {
            "projectUuid": "project-guarded",
            "documentUuid": "document-guarded",
            "documentType": 1,
        }
        png = root / "native-current-schematic.png"
        png.write_bytes(
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
            b"\x00\x00\x00\x08\x00\x00\x00\x06\x08\x06\x00\x00\x00"
        )
        evidence_path = root / "native-export-envelope.json"
        write_json_atomic(evidence_path, {
            "schemaVersion": "easyeda.gateway.schematic-export-evidence.v1",
            "status": "PASS",
            "identity": identity,
            "spec": {"fileType": "PNG", "scope": "current-schematic", "theme": "Default"},
            "safety": {"capabilityId": "visual.current-schematic.png"},
        })
        execution = {
            "success": True,
            "schemaVersion": "easyeda.gateway.schematic-export-execution.v1",
            "identity": identity,
            "spec": {"fileType": "PNG", "scope": "current-schematic", "theme": "Default"},
            "artifact": {
                "path": str(png),
                "sha256": sha256_file(png),
                "mediaType": "image/png",
                "width": 8,
                "height": 6,
            },
            "publishedOutput": None,
            "evidencePath": str(evidence_path),
        }
        return identity, execution, identity.copy()

    def test_builds_native_png_tool_arguments(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            before, visual, after = self._records(root)
            manifest = CanvasNativeVisualImportBuilder().build(
                project_dir=root,
                canvas_page_id="page:learning",
                identity_before=before,
                visual_execution=visual,
                identity_after=after,
                visual_mode="default",
            )

            self.assertEqual("READY", manifest["status"])
            self.assertEqual("PNG", manifest["visual"]["format"])
            self.assertEqual("current-schematic", manifest["visual"]["scope"])
            self.assertEqual(1536, manifest["visual"]["displayWidth"])
            self.assertEqual(1536, manifest["toolArgs"]["displayWidth"])
            self.assertNotIn("displayHeight", manifest["toolArgs"])
            self.assertEqual("native-easyeda-png", manifest["toolArgs"]["assetMeta"]["visualSource"])
            self.assertEqual("official-easyeda-export", manifest["toolArgs"]["evidenceSource"])
            self.assertFalse(manifest["toolArgs"]["replaceAiImageHolder"])
            self.assertEqual("default", manifest["visualMode"])
            self.assertEqual("Default", manifest["easyedaExportTheme"])
            self.assertEqual("default", manifest["toolArgs"]["assetMeta"]["visualMode"])

    def test_builds_black_white_native_png_tool_arguments(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            before, visual, after = self._records(root)
            visual["spec"]["theme"] = "Black on White"
            evidence_path = Path(visual["evidencePath"])
            evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
            evidence["spec"]["theme"] = "Black on White"
            write_json_atomic(evidence_path, evidence)

            manifest = CanvasNativeVisualImportBuilder().build(
                project_dir=root,
                canvas_page_id="page:learning",
                identity_before=before,
                visual_execution=visual,
                identity_after=after,
                visual_mode="black-white",
            )

            self.assertEqual("black-white", manifest["visualMode"])
            self.assertEqual("Black on White", manifest["easyedaExportTheme"])
            self.assertEqual(
                "Black on White",
                manifest["toolArgs"]["shapeMeta"]["easyedaExportTheme"],
            )

    def test_builds_official_multi_page_png_bundle_operations(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            identity = {
                "projectUuid": "project-guarded",
                "documentUuid": "document-guarded",
                "documentType": 1,
            }
            bundle = root / "official-current-schematic.png"
            bundle.write_bytes(b"PK\x03\x04official-bundle")
            pages = []
            for index in (1, 2):
                page = root / f"page-{index}.png"
                page.write_bytes(
                    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
                    b"\x00\x00\x00\x08\x00\x00\x00\x06\x08\x06\x00\x00\x00"
                )
                pages.append({
                    "index": index,
                    "entryName": f"official-page-{index}.png",
                    "path": str(page),
                    "sha256": sha256_file(page),
                    "bytes": page.stat().st_size,
                    "mediaType": "image/png",
                    "width": 8,
                    "height": 6,
                })
            source_artifact = {
                "path": str(bundle),
                "sha256": sha256_file(bundle),
                "bytes": bundle.stat().st_size,
                "mediaType": "application/zip",
                "containerFormat": "easyeda.official-native-png-bundle.v1",
            }
            evidence_path = root / "native-bundle-envelope.json"
            evidence = {
                "schemaVersion": "easyeda.gateway.native-png-bundle-evidence.v1",
                "status": "PASS",
                "identity": identity,
                "sourceArtifact": source_artifact,
                "easyedaApiCallCount": 0,
                "pageCount": 2,
                "pages": pages,
                "safety": {
                    "capabilityId": "visual.current-schematic.png",
                    "officialCallRepeated": False,
                },
                "spec": {"fileType": "PNG", "scope": "current-schematic", "theme": "Default"},
            }
            write_json_atomic(evidence_path, evidence)
            execution = {
                "success": True,
                "schemaVersion": "easyeda.gateway.native-png-bundle-normalization.v1",
                "identity": identity,
                "spec": {"fileType": "PNG", "scope": "current-schematic", "theme": "Default"},
                "sourceArtifact": source_artifact,
                "pageCount": 2,
                "pages": pages,
                "evidencePath": str(evidence_path),
                "easyedaApiCallCount": 0,
            }

            manifest = CanvasNativeVisualImportBuilder().build(
                project_dir=root,
                canvas_page_id="page:learning",
                identity_before=identity,
                visual_execution=execution,
                identity_after=identity.copy(),
                visual_mode="default",
            )

            self.assertEqual("PNG_BUNDLE", manifest["visual"]["format"])
            self.assertEqual(1536, manifest["visual"]["displayWidth"])
            self.assertEqual(2, len(manifest["operations"]))
            self.assertTrue(all(
                item["toolArgs"]["displayWidth"] == 1536
                and item["toolArgs"]["margin"] == 120
                and "displayHeight" not in item["toolArgs"]
                for item in manifest["operations"]
            ))
            self.assertTrue(all(
                item["toolArgs"]["assetMeta"]["visualSource"] == "native-easyeda-png"
                for item in manifest["operations"]
            ))

    def test_builds_successful_official_export_bundle_operations(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            identity = {
                "projectUuid": "project-guarded",
                "documentUuid": "document-guarded",
                "documentType": 1,
            }
            bundle = root / "current-schematic.png"
            bundle.write_bytes(b"PK\x03\x04official-bundle")
            native_pages = root / "native-pages"
            native_pages.mkdir()
            pages = []
            for index in (1, 2):
                page = native_pages / f"{index:03d}-official-native.png"
                page.write_bytes(
                    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
                    b"\x00\x00\x00\x08\x00\x00\x00\x06\x08\x06\x00\x00\x00"
                )
                pages.append({
                    "index": index,
                    "entryName": f"official-page-{index}.png",
                    "path": str(page),
                    "sha256": sha256_file(page),
                    "bytes": page.stat().st_size,
                    "mediaType": "image/png",
                    "width": 8,
                    "height": 6,
                })
            artifact = {
                "path": str(bundle),
                "sha256": sha256_file(bundle),
                "bytes": bundle.stat().st_size,
                "mediaType": "application/zip",
                "containerFormat": "easyeda.official-native-png-bundle.v1",
                "pageCount": 2,
                "pages": pages,
            }
            evidence_path = root / "envelope.json"
            write_json_atomic(evidence_path, {
                "schemaVersion": "easyeda.gateway.schematic-export-evidence.v1",
                "status": "PASS",
                "identity": identity,
                "safety": {
                    "capabilityId": "visual.current-schematic.png",
                    "automaticRetry": False,
                },
                "files": {
                    "current-schematic.png": artifact["sha256"],
                    **{
                        f"native-pages/{index:03d}-official-native.png": page["sha256"]
                        for index, page in enumerate(pages, start=1)
                    },
                },
                "spec": {"fileType": "PNG", "scope": "current-schematic", "theme": "Default"},
            })
            execution = {
                "success": True,
                "schemaVersion": "easyeda.gateway.schematic-export-execution.v1",
                "identity": identity,
                "spec": {"fileType": "PNG", "scope": "current-schematic", "theme": "Default"},
                "artifact": artifact,
                "publishedOutput": None,
                "evidencePath": str(evidence_path),
            }

            manifest = CanvasNativeVisualImportBuilder().build(
                project_dir=root,
                canvas_page_id="page:learning",
                identity_before=identity,
                visual_execution=execution,
                identity_after=identity.copy(),
                visual_mode="default",
            )

            self.assertEqual("PNG_BUNDLE", manifest["visual"]["format"])
            self.assertEqual(2, len(manifest["operations"]))
            self.assertTrue(all(
                item["toolArgs"]["displayWidth"] == 1536
                and item["toolArgs"]["margin"] == 120
                for item in manifest["operations"]
            ))

            Path(pages[0]["path"]).write_bytes(b"tampered")
            with self.assertRaisesRegex(ValueError, "digest mismatch"):
                CanvasNativeVisualImportBuilder().build(
                    project_dir=root,
                    canvas_page_id="page:learning",
                    identity_before=identity,
                    visual_execution=execution,
                    identity_after=identity.copy(),
                    visual_mode="default",
                )

    def test_refuses_pdf_for_image_insertion(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            before, visual, after = self._records(root)
            visual["spec"]["fileType"] = "PDF"
            with self.assertRaisesRegex(ValueError, "requires an official EasyEDA PNG"):
                CanvasNativeVisualImportBuilder().build(
                    project_dir=root,
                    canvas_page_id="page:learning",
                    identity_before=before,
                    visual_execution=visual,
                    identity_after=after,
                    visual_mode="default",
                )

    def test_refuses_visual_mode_theme_mismatch(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            before, visual, after = self._records(root)
            with self.assertRaisesRegex(ValueError, "does not match the selected visual mode"):
                CanvasNativeVisualImportBuilder().build(
                    project_dir=root,
                    canvas_page_id="page:learning",
                    identity_before=before,
                    visual_execution=visual,
                    identity_after=after,
                    visual_mode="black-white",
                )


class CanvasPdfVisualImportTests(unittest.TestCase):
    @staticmethod
    def _records(root: Path) -> tuple[dict, dict, dict]:
        identity = {
            "projectUuid": "project-pdf",
            "documentUuid": "document-pdf",
            "documentType": 1,
        }
        official = root / "official"
        official.mkdir()
        source_pdf = official / "current-schematic.pdf"
        source_pdf.write_bytes(b"%PDF-official-fixture")
        source_pdf_sha256 = sha256_file(source_pdf)
        official_envelope = official / "envelope.json"
        write_json_atomic(official_envelope, {
            "schemaVersion": "easyeda.gateway.schematic-export-evidence.v1",
            "status": "PASS",
            "identity": identity,
            "spec": {"fileType": "PDF", "scope": "current-schematic", "theme": "Default"},
            "safety": {
                "capabilityId": "visual.current-schematic.pdf",
                "automaticRetry": False,
            },
            "files": {source_pdf.name: source_pdf_sha256},
        })

        rendered = root / "rendered"
        pages_dir = rendered / "native-pages"
        pages_dir.mkdir(parents=True)
        pages = []
        for index in (1, 2):
            page = pages_dir / f"{index:03d}-official-pdf-render.png"
            page.write_bytes(
                b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
                b"\x00\x00\x18\x00\x00\x00\x12\x00\x08\x06\x00\x00\x00"
            )
            pages.append({
                "index": index,
                "pdfPageIndex": index,
                "entryName": f"pdf-page-{index:03d}.png",
                "path": str(page),
                "sha256": sha256_file(page),
                "bytes": page.stat().st_size,
                "mediaType": "image/png",
                "width": 6144,
                "height": 4608,
            })
        renderer = {
            "name": "pdftoppm",
            "path": "C:/tools/pdftoppm.exe",
            "sha256": "a" * 64,
            "version": "pdftoppm 25.07",
        }
        render_settings = {
            "format": "PNG",
            "maxLongEdge": 6144,
            "timeoutSeconds": 300.0,
            "background": "white",
        }
        render_envelope = rendered / "envelope.json"
        write_json_atomic(render_envelope, {
            "schemaVersion": "easyeda.gateway.native-pdf-visual-evidence.v1",
            "status": "PASS",
            "identity": identity,
            "sourceSpec": {"fileType": "PDF", "scope": "current-schematic", "theme": "Default"},
            "sourceOfficialEvidencePath": str(official_envelope),
            "sourceArtifact": {
                "path": str(source_pdf),
                "sha256": source_pdf_sha256,
                "bytes": source_pdf.stat().st_size,
                "mediaType": "application/pdf",
            },
            "safety": {
                "sourceCapabilityId": "visual.current-schematic.pdf",
                "officialCallRepeated": False,
                "automaticRetry": False,
            },
            "easyedaApiCallCount": 0,
            "pageCount": 2,
            "pages": pages,
            "renderSettings": render_settings,
            "renderer": renderer,
            "files": {
                f"native-pages/{index:03d}-official-pdf-render.png": page["sha256"]
                for index, page in enumerate(pages, start=1)
            },
        })
        execution = {
            "success": True,
            "schemaVersion": "easyeda.gateway.native-pdf-visual-render.v1",
            "identity": identity,
            "spec": {"fileType": "PDF", "scope": "current-schematic", "theme": "Default"},
            "sourceArtifact": {
                "path": str(source_pdf),
                "sha256": source_pdf_sha256,
                "bytes": source_pdf.stat().st_size,
                "mediaType": "application/pdf",
            },
            "pageCount": 2,
            "pages": pages,
            "renderSettings": render_settings,
            "renderer": renderer,
            "evidencePath": str(render_envelope),
            "easyedaApiCallCount": 0,
            "automaticRetry": False,
        }
        return identity, execution, identity.copy()

    def test_builds_pdf_rendered_page_operations(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            before, render, after = self._records(root)
            manifest = CanvasPdfVisualImportBuilder().build(
                project_dir=root,
                canvas_page_id="page:learning",
                identity_before=before,
                render_execution=render,
                identity_after=after,
                visual_mode="default",
            )

            self.assertEqual("PDF_RENDERED_PNG_PAGES", manifest["visual"]["format"])
            self.assertEqual(2, len(manifest["operations"]))
            self.assertTrue(all(
                operation["toolArgs"]["evidenceSource"] == "official-easyeda-pdf-render"
                and operation["toolArgs"]["displayWidth"] == 1536
                and "displayHeight" not in operation["toolArgs"]
                for operation in manifest["operations"]
            ))
            self.assertEqual("default", manifest["visualMode"])
            self.assertEqual("Default", manifest["easyedaExportTheme"])
            self.assertTrue(all(
                operation["toolArgs"]["assetMeta"]["sourcePdfSha256"]
                == manifest["visual"]["sourceSha256"]
                for operation in manifest["operations"]
            ))

    def test_refuses_tampered_rendered_page(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            before, render, after = self._records(root)
            Path(render["pages"][0]["path"]).write_bytes(b"tampered")
            with self.assertRaisesRegex(ValueError, "digest mismatch"):
                CanvasPdfVisualImportBuilder().build(
                    project_dir=root,
                    canvas_page_id="page:learning",
                    identity_before=before,
                    render_execution=render,
                    identity_after=after,
                    visual_mode="default",
                )

    def test_refuses_pdf_visual_mode_theme_mismatch(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            before, render, after = self._records(root)
            with self.assertRaisesRegex(ValueError, "does not match the selected visual mode"):
                CanvasPdfVisualImportBuilder().build(
                    project_dir=root,
                    canvas_page_id="page:learning",
                    identity_before=before,
                    render_execution=render,
                    identity_after=after,
                    visual_mode="black-white",
                )

    def test_cli_writes_pdf_visual_manifest(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            before, render, after = self._records(root)
            inputs = {}
            for name, value in {"before": before, "render": render, "after": after}.items():
                path = root / f"{name}.json"
                write_json_atomic(path, value)
                inputs[name] = path
            output_path = root / "pdf-import-manifest.json"
            output = StringIO()
            with redirect_stdout(output):
                exit_code = workbench_main([
                    "learning-pdf-visual-import-manifest",
                    "--project", str(root),
                    "--canvas-page-id", "page:learning",
                    "--identity-before", str(inputs["before"]),
                    "--render-execution", str(inputs["render"]),
                    "--identity-after", str(inputs["after"]),
                    "--visual-mode", "default",
                    "--output", str(output_path),
                ])
            self.assertEqual(0, exit_code)
            self.assertTrue(output_path.is_file())
            self.assertEqual(2, json.loads(output.getvalue())["pageCount"])

    def test_cli_writes_native_visual_manifest(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            before, visual, after = CanvasNativeVisualImportTests._records(root)
            inputs = {}
            for name, value in {"before": before, "visual": visual, "after": after}.items():
                path = root / f"{name}.json"
                write_json_atomic(path, value)
                inputs[name] = path
            output_path = root / "native-import-manifest.json"
            output = StringIO()
            with redirect_stdout(output):
                exit_code = workbench_main([
                    "learning-native-visual-import-manifest",
                    "--project", str(root),
                    "--canvas-page-id", "page:learning",
                    "--identity-before", str(inputs["before"]),
                    "--visual-execution", str(inputs["visual"]),
                    "--identity-after", str(inputs["after"]),
                    "--visual-mode", "default",
                    "--output", str(output_path),
                ])
            self.assertEqual(0, exit_code)
            self.assertTrue(output_path.is_file())
            self.assertEqual("page:learning", json.loads(output.getvalue())["toolArgs"]["pageId"])

    def test_legacy_builders_are_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, "DISABLED_BY_POLICY"):
            CanvasPageImportBuilder().build(
                project_dir=".", canvas_page_id="page:test", identity_before={},
                source_execution={}, render_execution={}, identity_after={},
            )
        with self.assertRaisesRegex(ValueError, "DISABLED_BY_POLICY"):
            CanvasProjectImportBuilder().build(
                project_dir=".", canvas_page_id="page:test", identity_before={},
                source_execution={}, render_execution={}, identity_after={},
            )

    def test_legacy_cli_routes_close_before_reading_inputs(self) -> None:
        for command in ("learning-page-import-manifest", "learning-project-import-manifest"):
            with self.subTest(command=command):
                output = StringIO()
                with redirect_stdout(output):
                    exit_code = workbench_main([
                        command,
                        "--project", ".",
                        "--canvas-page-id", "page:test",
                        "--identity-before", "missing-before.json",
                        "--source-execution", "missing-source.json",
                        "--render-execution", "missing-render.json",
                        "--identity-after", "missing-after.json",
                        "--output", "never-written.json",
                    ])
                self.assertEqual(2, exit_code)
                self.assertIn("DISABLED_BY_POLICY", output.getvalue())


if __name__ == "__main__":
    unittest.main()
