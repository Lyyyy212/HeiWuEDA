from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from easyeda_gateway.contract import ApiRegistry
from easyeda_gateway.device_match import (
    DEVICE_MATCH_ADAPTER_VERSION,
    DEVICE_MATCH_RESULT_SCHEMA,
    DeviceMatchSpec,
    EasyedaDeviceMatchDryRunAdapter,
    calculate_official_default_score,
)


WORKBENCH_ROOT = Path(__file__).resolve().parents[3]
MANIFEST = WORKBENCH_ROOT / "materials" / "manifests" / "api-manifest.json"


class FakeDeviceMatchClient:
    base_url = "http://127.0.0.1:49620"

    def health(self):
        return {"service": "easyeda-bridge", "edaConnected": True, "pendingRequests": 0}

    def windows(self):
        return {
            "windows": [{"windowId": "window-1", "connected": True, "active": True}],
            "activeWindowId": "window-1",
            "count": 1,
        }

    def execute_code(self, code: str, window_id: str):
        identity = {"projectUuid": "project-1", "documentUuid": "sheet-1", "documentType": 1}
        return {
            "success": True,
            "result": {
                "schemaVersion": DEVICE_MATCH_RESULT_SCHEMA,
                "adapterVersion": DEVICE_MATCH_ADAPTER_VERSION,
                "dryRun": True,
                "identityBefore": identity,
                "identityAfter": identity,
                "limits": {"maxComponents": 2, "maxCandidates": 2},
                "items": [
                    {
                        "component": {
                            "primitiveId": "p1",
                            "designator": "U1",
                            "name": "STM32F103",
                            "value": "",
                            "manufacturerId": "STM32F103C8T6",
                            "supplierId": "C8734",
                            "manufacturer": "ST",
                            "footprint": {"name": "LQFP-48"},
                        },
                        "queries": ["STM32F103C8T6", "C8734"],
                        "candidates": [
                            {
                                "name": "STM32F103C8T6",
                                "manufacturerId": "STM32F103C8T6",
                                "supplierId": "C8734",
                                "manufacturer": "ST",
                                "footprintName": "LQFP-48",
                                "uuid": "device-1",
                                "libraryUuid": "lib-1",
                            }
                        ],
                        "searchErrors": [],
                    }
                ],
            },
        }


class DeviceMatchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.registry = ApiRegistry.from_file(MANIFEST)

    def test_official_default_score(self) -> None:
        component = {"manufacturerId": "ABC123", "value": "", "name": ""}
        self.assertEqual(calculate_official_default_score(component, {"name": "ABC123"}), 100)
        self.assertEqual(calculate_official_default_score(component, {"name": "ABC123-TR"}), 85)
        self.assertEqual(calculate_official_default_score(component, {"name": "XYZ"}), 60)

    def test_build_code_contains_only_read_search_surface(self) -> None:
        code = EasyedaDeviceMatchDryRunAdapter(self.registry, FakeDeviceMatchClient()).build_code(
            DeviceMatchSpec(("U1",), 2, 2),
        )
        self.assertIn("sch_PrimitiveComponent.getAll", code)
        self.assertIn("lib_Device.search", code)
        self.assertNotIn("sch_PrimitiveComponent.modify", code)
        self.assertNotIn("sch_Document.save", code)

    def test_dry_run_scores_and_records_zero_write_boundary(self) -> None:
        adapter = EasyedaDeviceMatchDryRunAdapter(self.registry, FakeDeviceMatchClient())
        with TemporaryDirectory() as temporary:
            result = adapter.run(
                DeviceMatchSpec(("U1",), 2, 2),
                Path(temporary) / "evidence",
                identity={"projectUuid": "project-1", "documentUuid": "sheet-1"},
            )
            report = json.loads(result.report_path.read_text(encoding="utf-8"))
            envelope = json.loads(result.evidence_path.read_text(encoding="utf-8"))
        self.assertEqual(result.status, "PASS")
        self.assertEqual(report["items"][0]["candidates"][0]["score"], 100)
        self.assertEqual(report["summary"]["designWriteCalls"], 0)
        self.assertEqual(envelope["writeBoundary"]["designSaveCalls"], 0)


if __name__ == "__main__":
    unittest.main()
