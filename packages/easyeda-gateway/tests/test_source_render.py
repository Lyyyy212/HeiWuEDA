from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from easyeda_gateway.source_render import (
    OfflineProjectSourceRenderAdapter,
    OfflineSourceRenderAdapter,
    SourceRenderSpec,
)
from tests.test_source_renderer_v22 import build_fixture_epro


class OfflineSourceRenderAdapterTests(unittest.TestCase):
    def test_renders_every_project_sheet_to_ordered_pngs(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = build_fixture_epro(
                root / "fixture.epro",
                extra_sheet_uuids=["sheet-uuid-2"],
            )
            output = root / "all-pages"
            result = OfflineProjectSourceRenderAdapter().execute(
                source,
                root / "evidence",
                output,
            )
            envelope = json.loads(result.evidence_path.read_text(encoding="utf-8"))

            self.assertEqual(result.as_dict()["pageCount"], 2)
            self.assertEqual(envelope["status"], "PASS")
            self.assertEqual(envelope["renderStatus"], "STRUCTURAL_PASS")
            self.assertEqual(envelope["quality"]["visualStatus"], "UNQUALIFIED")
            self.assertEqual(envelope["easyedaApiCallCount"], 0)
            self.assertEqual(
                [item["documentUuid"] for item in result.pages],
                ["sheet-uuid", "sheet-uuid-2"],
            )
            self.assertTrue(all(Path(item["publishedPng"]).is_file() for item in result.pages))

            with self.assertRaisesRegex(Exception, "already exists"):
                OfflineProjectSourceRenderAdapter().execute(
                    source,
                    root / "evidence-replay",
                    output,
                )

    def test_renders_svg_without_any_easyeda_or_bridge_dependency(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = build_fixture_epro(root / "fixture.epro")
            result = OfflineSourceRenderAdapter().execute(
                SourceRenderSpec("sheet-uuid"),
                source,
                root / "evidence",
                svg_output=root / "published.svg",
            )
            envelope = json.loads(result.evidence_path.read_text(encoding="utf-8"))

        self.assertEqual(envelope["status"], "PASS")
        self.assertEqual(envelope["renderStatus"], "STRUCTURAL_PASS")
        self.assertEqual(envelope["quality"]["visualStatus"], "UNQUALIFIED")
        self.assertTrue(envelope["quality"]["visualReviewRequired"])
        self.assertEqual(envelope["easyedaApiCallCount"], 0)
        self.assertEqual(envelope["executionModel"], "LOCAL_ONLY_NO_EASYEDA_CALLS")
        self.assertGreater(envelope["artifacts"]["svg"]["primitiveCount"], 0)

    def test_renders_canvas_ready_png_with_immutable_evidence(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = build_fixture_epro(root / "fixture.epro")
            output = root / "published.png"
            result = OfflineSourceRenderAdapter().execute(
                SourceRenderSpec("sheet-uuid", render_png=True),
                source,
                root / "evidence",
                png_output=output,
            )
            envelope = json.loads(result.evidence_path.read_text(encoding="utf-8"))

            self.assertEqual(envelope["status"], "PASS")
            self.assertEqual(result.as_dict()["renderStatus"], "STRUCTURAL_PASS")
            self.assertEqual(result.as_dict()["visualStatus"], "UNQUALIFIED")
            self.assertEqual(envelope["easyedaApiCallCount"], 0)
            self.assertEqual(result.published_png, output.resolve())
            self.assertEqual(result.png_sha256, envelope["artifacts"]["png"]["sha256"])
            self.assertGreater(envelope["artifacts"]["png"]["width"], 0)
            self.assertGreater(envelope["artifacts"]["png"]["height"], 0)
            self.assertTrue(output.read_bytes().startswith(b"\x89PNG\r\n\x1a\n"))

    def test_refuses_to_overwrite_published_svg_before_rendering(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = build_fixture_epro(root / "fixture.epro")
            output = root / "published.svg"
            output.write_text("keep", encoding="utf-8")

            with self.assertRaisesRegex(Exception, "already exists"):
                OfflineSourceRenderAdapter().execute(
                    SourceRenderSpec("sheet-uuid"),
                    source,
                    root / "evidence",
                    svg_output=output,
                )

            self.assertEqual(output.read_text(encoding="utf-8"), "keep")

    def test_refuses_to_overwrite_published_png_before_rendering(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = build_fixture_epro(root / "fixture.epro")
            output = root / "published.png"
            output.write_bytes(b"keep")

            with self.assertRaisesRegex(Exception, "already exists"):
                OfflineSourceRenderAdapter().execute(
                    SourceRenderSpec("sheet-uuid", render_png=True),
                    source,
                    root / "evidence",
                    png_output=output,
                )

            self.assertEqual(output.read_bytes(), b"keep")


if __name__ == "__main__":
    unittest.main()
