from __future__ import annotations

from pathlib import Path
import unittest

from easyeda_gateway.composite import TRUSTED_READ_TEMPLATES
from easyeda_gateway.contract import ApiRegistry


WORKBENCH_ROOT = Path(__file__).resolve().parents[3]
SOURCES = WORKBENCH_ROOT / "materials" / "sources" / "examples"
MANIFEST = WORKBENCH_ROOT / "materials" / "manifests" / "api-manifest.json"


class OfficialSourceRegressionTests(unittest.TestCase):
    def test_netlist_template_matches_official_collection_path(self) -> None:
        source = (SOURCES / "eext-netlist-explorer" / "src" / "index.ts").read_text(encoding="utf-8")
        iframe = (SOURCES / "eext-netlist-explorer" / "iframe" / "netlist.html").read_text(encoding="utf-8")
        self.assertIn("sch_ManufactureData.getNetlistFile()", source)
        self.assertIn("pinInfoMap", iframe)
        self.assertEqual(
            TRUSTED_READ_TEMPLATES["schematic.snapshot.v1"].source_commit,
            "6661961fc8780e13b97a9450a96afbaaf2960bf7",
        )

    def test_pcb_report_replaces_only_the_deprecated_net_name_method(self) -> None:
        source = (SOURCES / "eext-export-design-report" / "src" / "index.ts").read_text(encoding="utf-8")
        registry = ApiRegistry.from_file(MANIFEST)
        self.assertIn("pcb_Net.getAllNetName()", source)
        self.assertTrue(registry.resolve_method("PCB_Net.getAllNetName#1").deprecated)
        self.assertFalse(registry.resolve_method("PCB_Net.getAllNetsName#1").deprecated)
        self.assertIn("getAllNetsName", TRUSTED_READ_TEMPLATES["pcb.snapshot.v1"].body)

    def test_bom_and_ibom_sources_retain_the_expected_algorithms(self) -> None:
        comparator = (SOURCES / "eext-bom-compare" / "iframe" / "src" / "core" / "comparator.ts").read_text(encoding="utf-8")
        ibom = (SOURCES / "eext-interactive-html-bom" / "iframe" / "index.html").read_text(encoding="utf-8")
        self.assertIn("cellDiffs", comparator)
        self.assertIn("comparedColumns", comparator)
        self.assertIn("pcb_PrimitiveComponent.getAll()", ibom)
        self.assertIn("pcb_PrimitivePad.getAll()", ibom)


if __name__ == "__main__":
    unittest.main()
