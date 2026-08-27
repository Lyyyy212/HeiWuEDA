from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest import mock

from pypdf import PdfWriter

from easyeda_gateway.artifact_io import sha256_file
from easyeda_gateway.errors import ContractError
from easyeda_gateway.native_pdf_visual import render_existing_official_pdf


IDENTITY = {
    "projectUuid": "project-pdf",
    "documentUuid": "document-pdf",
    "documentType": 1,
}


def _png(width: int, height: int) -> bytes:
    return (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
        + width.to_bytes(4, "big")
        + height.to_bytes(4, "big")
        + b"\x08\x06\x00\x00\x00"
    )


class NativePdfVisualTests(unittest.TestCase):
    @staticmethod
    def _source(root: Path, page_count: int = 2) -> dict:
        official = root / "official-export"
        official.mkdir()
        pdf = official / "current-schematic.pdf"
        writer = PdfWriter()
        for _ in range(page_count):
            writer.add_blank_page(width=612, height=792)
        with pdf.open("wb") as handle:
            writer.write(handle)
        envelope = official / "envelope.json"
        envelope.write_text(json.dumps({
            "schemaVersion": "easyeda.gateway.schematic-export-evidence.v1",
            "status": "PASS",
            "identity": IDENTITY,
            "safety": {
                "capabilityId": "visual.current-schematic.pdf",
                "automaticRetry": False,
            },
            "files": {pdf.name: sha256_file(pdf)},
        }), encoding="utf-8")
        return {
            "success": True,
            "schemaVersion": "easyeda.gateway.schematic-export-execution.v1",
            "identity": IDENTITY,
            "spec": {"fileType": "PDF", "scope": "current-schematic"},
            "artifact": {
                "path": str(pdf),
                "sha256": sha256_file(pdf),
                "bytes": pdf.stat().st_size,
                "mediaType": "application/pdf",
            },
            "evidencePath": str(envelope),
        }

    @staticmethod
    def _fake_render(_renderer, _source, temporary, page_count, max_long_edge, _timeout):
        pages = []
        for index in range(1, page_count + 1):
            page = temporary / f"rendered-{index}.png"
            page.write_bytes(_png(max_long_edge, max_long_edge - 100))
            pages.append(page)
        return pages

    @mock.patch("easyeda_gateway.native_pdf_visual._renderer_version", return_value="pdftoppm test")
    @mock.patch("easyeda_gateway.native_pdf_visual._run_pdftoppm", side_effect=_fake_render.__func__)
    def test_renders_and_seals_official_pdf_pages(self, _render, _version) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = self._source(root)
            renderer = root / "pdftoppm.exe"
            renderer.write_bytes(b"renderer-fixture")
            output = root / "render-execution.json"

            execution = render_existing_official_pdf(
                source_execution=source,
                identity_before=IDENTITY,
                identity_after=IDENTITY.copy(),
                evidence_root=root / "derived",
                output_path=output,
                pdftoppm_path=renderer,
                max_long_edge=6144,
            )

            self.assertTrue(output.is_file())
            self.assertEqual(0, execution["easyedaApiCallCount"])
            self.assertEqual(2, execution["pageCount"])
            self.assertTrue(all(max(page["width"], page["height"]) == 6144 for page in execution["pages"]))
            evidence = json.loads(Path(execution["evidencePath"]).read_text(encoding="utf-8"))
            self.assertEqual("PASS", evidence["status"])
            self.assertEqual("visual.current-schematic.pdf", evidence["safety"]["sourceCapabilityId"])
            self.assertFalse(evidence["safety"]["officialCallRepeated"])
            self.assertEqual(sha256_file(renderer), evidence["renderer"]["sha256"])
            for page in execution["pages"]:
                page_path = Path(page["path"])
                relative = page_path.relative_to(Path(execution["evidencePath"]).parent).as_posix()
                self.assertEqual(page["sha256"], evidence["files"][relative])

    @mock.patch("easyeda_gateway.native_pdf_visual._renderer_version", return_value="pdftoppm test")
    @mock.patch("easyeda_gateway.native_pdf_visual._run_pdftoppm", side_effect=_fake_render.__func__)
    def test_rejects_identity_drift_before_rendering(self, render, _version) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = self._source(root, page_count=1)
            renderer = root / "pdftoppm.exe"
            renderer.write_bytes(b"renderer-fixture")
            changed = {**IDENTITY, "documentUuid": "different"}
            with self.assertRaisesRegex(ContractError, "identity changed"):
                render_existing_official_pdf(
                    source_execution=source,
                    identity_before=IDENTITY,
                    identity_after=changed,
                    evidence_root=root / "derived",
                    output_path=root / "render.json",
                    pdftoppm_path=renderer,
                )
            render.assert_not_called()

    def test_rejects_unbounded_render_size(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = self._source(root, page_count=1)
            with self.assertRaisesRegex(ContractError, "max-long-edge"):
                render_existing_official_pdf(
                    source_execution=source,
                    identity_before=IDENTITY,
                    identity_after=IDENTITY,
                    evidence_root=root / "derived",
                    output_path=root / "render.json",
                    max_long_edge=16384,
                )


if __name__ == "__main__":
    unittest.main()
