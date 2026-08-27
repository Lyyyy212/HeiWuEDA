from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from easyeda_gateway.client import BridgeClient
from easyeda_gateway.composite import COMPOSITE_RESULT_SCHEMA, CompositeReadExecutor
from easyeda_gateway.contract import ApiRegistry, classify_method_effect

from .support import MockBridge


WORKBENCH_ROOT = Path(__file__).resolve().parents[3]
MANIFEST = WORKBENCH_ROOT / "materials" / "manifests" / "api-manifest.json"


class CompositeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.registry = ApiRegistry.from_file(MANIFEST)

    def test_templates_only_reference_locked_read_methods(self) -> None:
        executor = CompositeReadExecutor(self.registry, None)
        for template_id in ("schematic.snapshot.v1", "pcb.snapshot.v1"):
            template = executor.template(template_id)
            for method_id in template.method_ids:
                descriptor = self.registry.resolve_method(method_id)
                self.assertFalse(descriptor.deprecated)
                self.assertEqual(classify_method_effect(descriptor.method_name), "READ")

    def test_generated_code_has_identity_guards_and_no_write_calls(self) -> None:
        executor = CompositeReadExecutor(self.registry, None)
        code = executor.build_code(
            "pcb.snapshot.v1",
            {"projectUuid": "project-1", "documentUuid": "pcb-1"},
        )
        self.assertIn("getAllNetsName", code)
        self.assertIn("EasyEDA identity changed during composite read", code)
        self.assertNotIn("//", code)
        self.assertNotIn(".modify(", code)
        self.assertNotIn(".save(", code)

        schematic_code = executor.build_code("schematic.snapshot.v1")
        self.assertIn("netlistStatus", schematic_code)
        self.assertIn("getNetlistFile", schematic_code)

    def test_execute_records_composite_evidence(self) -> None:
        payload = {
            "schemaVersion": "easyeda.gateway.pcb-snapshot.v1",
            "components": [],
            "pads": [],
            "lines": [],
            "arcs": [],
            "polylines": [],
            "vias": [],
            "texts": [],
            "netLengths": [],
            "netClasses": [],
            "differentialPairs": [],
            "equalLengthGroups": [],
            "padPairGroups": [],
        }
        identity = {"projectUuid": "project-1", "documentUuid": "pcb-1", "documentType": 3}
        bridge_result = {
            "schemaVersion": COMPOSITE_RESULT_SCHEMA,
            "templateId": "pcb.snapshot.v1",
            "templateVersion": "1.0.0",
            "identityBefore": identity,
            "identityAfter": identity,
            "payload": payload,
        }
        with MockBridge(bridge_result) as mock, TemporaryDirectory() as temporary:
            executor = CompositeReadExecutor(self.registry, BridgeClient(mock.url))
            result = executor.execute("pcb.snapshot.v1", temporary, window_id="window-1", postprocess=lambda value: {"count": len(value["components"])})
            envelope = json.loads(result.evidence_path.read_text(encoding="utf-8"))
            request = json.loads((result.evidence_path.parent / "request.json").read_text(encoding="utf-8"))
        self.assertEqual(result.derived, {"count": 0})
        self.assertEqual(envelope["risk"], "READ")
        self.assertEqual(request["template"]["templateId"], "pcb.snapshot.v1")
        self.assertEqual(mock.requests[-1]["path"], "/execute")


if __name__ == "__main__":
    unittest.main()
