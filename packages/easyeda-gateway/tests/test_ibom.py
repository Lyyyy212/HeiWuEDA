from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from easyeda_gateway.ibom import build_ibom_model, render_ibom_html, write_ibom_html

from .test_intelligence import _pcb_snapshot


class InteractiveBomTests(unittest.TestCase):
    def test_builds_grouped_bom_and_embeds_traceable_identity(self) -> None:
        snapshot = _pcb_snapshot()
        snapshot["components"] = [
            {
                "primitiveId": "p1",
                "designator": "R1",
                "name": "10k",
                "footprint": {"name": "0603"},
                "layer": 1,
                "x": 10,
                "y": 20,
                "procurement": {"manufacturerPart": "RC0603"},
            },
            {
                "primitiveId": "p2",
                "designator": "R2",
                "name": "10k",
                "footprint": {"name": "0603"},
                "layer": 1,
                "x": 30,
                "y": 40,
                "procurement": {"manufacturerPart": "RC0603"},
            },
        ]
        model = build_ibom_model(snapshot, project={"uuid": "project-1", "documentUuid": "pcb-1", "friendlyName": "Board"})
        self.assertEqual(model["statistics"]["bomGroups"], 1)
        self.assertEqual(model["bom"][0]["quantity"], 2)
        self.assertEqual(model["metadata"]["projectUuid"], "project-1")
        self.assertEqual(model["metadata"]["documentUuid"], "pcb-1")

    def test_html_escapes_embedded_json_and_dynamic_cells(self) -> None:
        snapshot = _pcb_snapshot()
        snapshot["components"] = [
            {"designator": "R1", "name": "<script>alert(1)</script>", "layer": 1, "x": 1, "y": 2},
        ]
        html = render_ibom_html(build_ibom_model(snapshot))
        self.assertNotIn("<script>alert(1)</script>", html)
        self.assertIn("\\u003cscript>alert(1)\\u003c/script>", html)
        self.assertIn("replace(/[&<>", html)

    def test_atomic_html_write(self) -> None:
        model = build_ibom_model(_pcb_snapshot())
        with TemporaryDirectory() as temporary:
            target = Path(temporary) / "ibom.html"
            output = write_ibom_html(target, model)
            self.assertEqual(output, target.resolve())
            self.assertTrue(target.read_text(encoding="utf-8").startswith("<!doctype html>"))

    def test_corrupt_bridge_title_falls_back_without_losing_uuid(self) -> None:
        model = build_ibom_model(
            _pcb_snapshot(),
            project={"uuid": "project-1", "friendlyName": "\ufffd\ufffd\ufffd", "documentUuid": "pcb-1"},
        )
        self.assertEqual(model["metadata"]["title"], "EasyEDA PCB")
        self.assertEqual(model["metadata"]["projectUuid"], "project-1")


if __name__ == "__main__":
    unittest.main()
