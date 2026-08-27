from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest import mock

from easyeda_gateway.consistency import build_consistency_report


class ConsistencyTests(unittest.TestCase):
    def test_matching_bom_netlist_pdf_and_drc_pass(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            pdf = root / "schematic.pdf"
            pdf.write_bytes(b"%PDF-fixture")
            bom = root / "bom.csv"
            bom.write_text("Designator\tQuantity\nR1 R2\t2\n", encoding="utf-16")
            netlist = root / "netlist.net"
            netlist.write_text(
                json.dumps(
                    {
                        "components": {
                            "a": {"props": {"Designator": "R1", "Add into BOM": "Yes", "Convert to PCB": "Yes"}},
                            "b": {"props": {"Designator": "R2", "Add into BOM": "Yes", "Convert to PCB": "Yes"}},
                        },
                    },
                ),
                encoding="utf-8",
            )
            with mock.patch("easyeda_gateway.consistency.extract_pdf_text", return_value=("R1 R2", "PASS:1_PAGES")):
                report = build_consistency_report(
                    pdf,
                    bom,
                    netlist,
                    {"status": "PASS"},
                    required_refs=["R1"],
                    forbidden_refs=["C99"],
                )
        self.assertEqual(report["status"], "PASS")
        self.assertTrue(report["accepted"])
        self.assertTrue(report["comparison"]["bomNetlistSetMatch"])
        self.assertTrue(report["comparison"]["pdfReferenceCoverageComplete"])

    def test_missing_pdf_parser_blocks_validation_instead_of_claiming_pass(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            pdf = root / "schematic.pdf"
            pdf.write_bytes(b"%PDF-fixture")
            bom = root / "bom.csv"
            bom.write_text("Designator\tQuantity\nR1\t1\n", encoding="utf-16")
            netlist = root / "netlist.net"
            netlist.write_text(
                json.dumps({"components": {"a": {"props": {"Designator": "R1", "Add into BOM": True}}}}),
                encoding="utf-8",
            )
            with mock.patch("easyeda_gateway.consistency.extract_pdf_text", return_value=(None, "PYPDF_UNAVAILABLE")):
                report = build_consistency_report(pdf, bom, netlist, {"status": "PASS"})
        self.assertEqual(report["status"], "BLOCKED_VALIDATION")
        self.assertIsNone(report["comparison"]["pdfReferenceCoverageComplete"])

    def test_incomplete_pdf_text_layer_requires_review_without_claiming_missing_objects(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            pdf = root / "schematic.pdf"
            pdf.write_bytes(b"%PDF-fixture")
            bom = root / "bom.csv"
            bom.write_text("Designator\tQuantity\nR1 R2\t2\n", encoding="utf-16")
            netlist = root / "netlist.net"
            netlist.write_text(
                json.dumps(
                    {
                        "components": {
                            "a": {"props": {"Designator": "R1", "Add into BOM": True}},
                            "b": {"props": {"Designator": "R2", "Add into BOM": True}},
                        }
                    }
                ),
                encoding="utf-8",
            )
            with mock.patch(
                "easyeda_gateway.consistency.extract_pdf_text",
                return_value=("R1", "PASS:1_PAGES"),
            ):
                report = build_consistency_report(pdf, bom, netlist, {"status": "PASS"})

        self.assertEqual(report["status"], "REVIEW_REQUIRED")
        self.assertFalse(report["accepted"])
        self.assertEqual(report["blockers"], [])
        self.assertIsNone(report["comparison"]["pdfReferenceCoverageComplete"])
        self.assertFalse(report["comparison"]["pdfTextLayerCoverageComplete"])
        self.assertEqual(report["reviewFindings"][0]["code"], "PDF_TEXT_LAYER_INCOMPLETE")
