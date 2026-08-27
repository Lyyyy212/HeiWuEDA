from __future__ import annotations

from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from hwlifecycle.io_utils import sha256_file, sha256_json, utc_now, write_json_atomic
from hwlifecycle.learning import (
    HardwareTutorEngine,
    LearningCanvasAdapter,
    LearningNotePackageBuilder,
    LearningSessionStore,
    OfficialEasyedaEvidenceProvider,
    render_learning_note_markdown,
)
from workbench import main as workbench_main


class LearningNotebookTests(unittest.TestCase):
    @staticmethod
    def _canvas(root: Path, *, frame_numbers: tuple[int, ...] = (4, 5)) -> Path:
        page_dir = root / "canvas" / "pages" / "page"
        assets_dir = page_dir / "assets"
        assets_dir.mkdir(parents=True, exist_ok=True)
        image_path = assets_dir / "official.png"
        image_path.write_bytes(b"\x89PNG\r\n\x1a\nnotebook-fixture")
        image_sha256 = sha256_file(image_path)
        store: dict[str, dict] = {
            "page:page": {
                "id": "page:page", "typeName": "page", "name": "Page 1",
                "meta": {"hardwareLearningNextFrameNumber": max(frame_numbers, default=0) + 1},
            },
            "asset:official": {
                "id": "asset:official", "typeName": "asset", "type": "image",
                "props": {"name": "official.png", "src": "/page-assets/page/official.png", "w": 1000, "h": 700},
                "meta": {
                    "evidenceSource": "official-easyeda-export",
                    "visualSource": "native-easyeda-png",
                    "visualSha256": image_sha256,
                    "projectUuid": "project-1", "documentUuid": "document-1", "documentType": 1,
                },
            },
            "shape:image": {
                "id": "shape:image", "typeName": "shape", "type": "image", "parentId": "page:page",
                "x": 0, "y": 0, "rotation": 0, "opacity": 1, "isLocked": True,
                "props": {"w": 1000, "h": 700, "assetId": "asset:official", "altText": "official"},
                "meta": {
                    "hardwareLearningEvidence": True,
                    "evidenceSource": "official-easyeda-export",
                    "visualSource": "native-easyeda-png",
                    "evidenceSha256": image_sha256,
                    "easyedaDocumentUuid": "document-1",
                },
            },
            "shape:note": {
                "id": "shape:note", "typeName": "shape", "type": "geo", "parentId": "page:page",
                "x": 500, "y": 500, "rotation": 0, "opacity": 1,
                "props": {"w": 200, "h": 100, "color": "yellow", "fill": "solid", "size": "m"},
                "meta": {
                    "hardwareLearningAnnotation": True,
                    "hardwareLearningKind": "note",
                    "hardwareLearningText": "待验证",
                },
            },
        }
        for index, number in enumerate(frame_numbers):
            store[f"shape:frame-{number}"] = {
                "id": f"shape:frame-{number}", "typeName": "shape", "type": "geo", "parentId": "page:page",
                "x": 100 + index * 250, "y": 120, "rotation": 0, "opacity": 1,
                "props": {"w": 180, "h": 140, "color": "black", "fill": "none", "size": "m"},
                "meta": {
                    "hardwareLearningAnnotation": True,
                    "hardwareLearningKind": "frame",
                    "hardwareLearningFrame": True,
                    "hardwareLearningFrameNumber": number,
                },
            }
        canvas_path = page_dir / "hardware-learning-canvas.json"
        write_json_atomic(canvas_path, {"schema": {"schemaVersion": 2}, "store": store})
        return canvas_path

    @staticmethod
    def _answer_question(root: Path, canvas_path: Path) -> dict:
        store = LearningSessionStore(root)
        session = store.create_session(
            canvas_page_id="page:page",
            learning_level="intermediate",
            session_id="learning:jlc-hardware-learning:page",
        )
        shapes = [{
            "shapeId": "shape:image", "shapeType": "image", "role": "source-image",
            "pageBounds": {"x": 0, "y": 0, "width": 1000, "height": 700},
        }]
        for number, x in ((4, 100), (5, 350)):
            shapes.append({
                "shapeId": f"shape:frame-{number}", "shapeType": "geo", "role": "selection-frame",
                "learningFrameNumber": number,
                "pageBounds": {"x": x, "y": 120, "width": 180, "height": 140},
                "meta": {"hardwareLearningFrame": True, "hardwareLearningFrameNumber": number},
            })
        question = LearningCanvasAdapter().build_question(
            session_id=session["sessionId"],
            canvas_page_id="page:page",
            shapes=shapes,
            user_question="模块4和5怎样配合？",
            canvas_snapshot_sha256=sha256_file(canvas_path),
        )
        question["selection"]["canvasSelectionVersion"] = 2
        question["selection"]["selectedFrameNumbers"] = [4, 5]
        question["selection"]["referencedFrameNumbers"] = [5]
        store.save_question(question)
        bundle = OfficialEasyedaEvidenceProvider().offline_bundle(question)
        store.save_evidence(bundle)
        answer = HardwareTutorEngine().answer(question, bundle)
        store.save_answer(answer, bundle)
        run = {
            "schemaVersion": "learning.question-run.v1",
            "runId": "run:notebook",
            "questionId": question["questionId"],
            "sessionId": question["sessionId"],
            "canvasPageId": "page:page",
            "mode": "offline-artifact",
            "questionSha256": sha256_json(question),
            "bundleId": bundle["bundleId"],
            "bundleSha256": sha256_json(bundle),
            "answerId": answer["answerId"],
            "answerSha256": sha256_json(answer),
            "completedAt": utc_now(),
        }
        store.save_question_run(question["questionId"], run)
        store.save_dialogue_response(
            question_id=question["questionId"],
            assistant_response="模块4负责输入处理，模块5负责后级控制；两者通过当前框选链路关联。",
        )
        return question

    def test_builds_frame_linked_dialogue_and_lark_plan(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            canvas = self._canvas(root)
            question = self._answer_question(root, canvas)
            package = LearningNotePackageBuilder(root).build(canvas_path=canvas, page_id="page:page")

            self.assertEqual("learning.note-package.v1", package["schemaVersion"])
            self.assertEqual([4, 5], [frame["frameNumber"] for frame in package["frames"]])
            self.assertEqual(1, len(package["dialogue"]["turns"]))
            turn = package["dialogue"]["turns"][0]
            self.assertEqual(question["questionId"], turn["questionId"])
            self.assertEqual("conversation", turn["responseSource"])
            self.assertEqual(
                [(4, "canvas-selection"), (5, "explicit-number")],
                [(link["frameNumber"], link["linkSource"]) for link in turn["frameLinks"]],
            )
            self.assertTrue(all(frame["dialogueTurnIds"] == [turn["turnId"]] for frame in package["frames"]))
            self.assertEqual("PLAN_ONLY_NO_CLOUD_WRITE", package["larkPlan"]["mode"])
            self.assertEqual(
                "whiteboard-cli-dsl-with-local-image-assets",
                package["larkPlan"]["whiteboard"]["strategy"],
            )
            self.assertEqual(
                {
                    "profile": "learning.module-index-board.v1",
                    "placement": "after-module-index-heading",
                    "contentScope": "source-page-images-and-learning-frames",
                    "nativeZoomAndAnnotation": True,
                    "learningFrameMarkerStyle": {
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
                    },
                },
                package["larkPlan"]["whiteboard"]["moduleIndexBoard"],
            )
            self.assertEqual(
                ["synchronized-learning-board", "module-index-board"],
                package["larkPlan"]["whiteboard"]["learningFrameMarkerStyleTargets"],
            )
            self.assertEqual(
                package["larkPlan"]["whiteboard"]["moduleIndexBoard"]["learningFrameMarkerStyle"],
                package["larkPlan"]["whiteboard"]["learningFrameMarkerStyle"],
            )
            self.assertEqual(0, len(package["dialogue"]["unlinkedTurnIds"]))
            self.assertIn("模块4", render_learning_note_markdown(package))
            self.assertIn("模块5", render_learning_note_markdown(package))

    def test_refuses_dialogue_link_to_missing_frame(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            full_canvas = self._canvas(root, frame_numbers=(4, 5))
            self._answer_question(root, full_canvas)
            canvas = self._canvas(root, frame_numbers=(4,))
            with self.assertRaisesRegex(ValueError, "references missing frame"):
                LearningNotePackageBuilder(root).build(canvas_path=canvas, page_id="page:page")

    def test_reads_legacy_canvas_metadata_without_rebranding_output(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            canvas = self._canvas(root, frame_numbers=(4,))
            snapshot = json.loads(canvas.read_text(encoding="utf-8"))
            for record in snapshot["store"].values():
                meta = record.get("meta") if isinstance(record, dict) else None
                if not isinstance(meta, dict):
                    continue
                replacements = {
                    "hardwareLearningNextFrameNumber": "cowartLearningNextFrameNumber",
                    "hardwareLearningEvidence": "cowartHardwareEvidence",
                    "hardwareLearningAnnotation": "cowartHardwareAnnotation",
                    "hardwareLearningKind": "cowartLearningKind",
                    "hardwareLearningText": "cowartLearningText",
                    "hardwareLearningFrame": "cowartLearningFrame",
                    "hardwareLearningFrameNumber": "cowartLearningFrameNumber",
                }
                for current, legacy in replacements.items():
                    if current in meta:
                        meta[legacy] = meta.pop(current)
            write_json_atomic(canvas, snapshot)

            package = LearningNotePackageBuilder(root).build(canvas_path=canvas, page_id="page:page")
            self.assertEqual([4], [frame["frameNumber"] for frame in package["frames"]])
            self.assertEqual(5, package["page"]["nextFrameNumber"])
            self.assertIn("hardware-learning-page", json.dumps(package, ensure_ascii=False))
            self.assertNotIn("cowart-page", json.dumps(package, ensure_ascii=False))

    def test_cli_writes_json_and_markdown_without_cloud_write(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            canvas = self._canvas(root)
            output = root / "notes" / "page.json"
            markdown = root / "notes" / "page.md"
            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = workbench_main([
                    "learning-note-package",
                    "--project", str(root),
                    "--canvas", str(canvas),
                    "--page-id", "page:page",
                    "--output", str(output),
                    "--markdown-output", str(markdown),
                ])
            result = json.loads(stdout.getvalue())
            self.assertEqual(0, exit_code)
            self.assertEqual(0, result["cloudWriteCount"])
            self.assertTrue(output.is_file())
            self.assertTrue(markdown.is_file())

    def test_dialogue_response_is_immutable_and_bound_to_tutor_answer(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            canvas = self._canvas(root)
            question = self._answer_question(root, canvas)
            store = LearningSessionStore(root)
            existing = store.dialogue_response(question["questionId"])
            self.assertEqual("learning.dialogue-response.v1", existing["schemaVersion"])
            with self.assertRaisesRegex(ValueError, "immutable learning record"):
                store.save_dialogue_response(
                    question_id=question["questionId"],
                    assistant_response="changed response",
                )


if __name__ == "__main__":
    unittest.main()
