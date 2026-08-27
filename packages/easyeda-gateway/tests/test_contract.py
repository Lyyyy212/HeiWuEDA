from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import unittest

from easyeda_gateway.contract import ApiRegistry, plan_digest
from easyeda_gateway.version import GATEWAY_VERSION


WORKBENCH_ROOT = Path(__file__).resolve().parents[3]
MANIFEST = WORKBENCH_ROOT / "materials" / "manifests" / "api-manifest.json"


class ContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.registry = ApiRegistry.from_file(MANIFEST)

    def read_plan(self) -> dict:
        plan = {
            "schemaVersion": "easyeda.hardware-lifecycle.api-plan.v1",
            "planId": "unit-read",
            "risk": "READ",
            "registry": self.registry.identity,
            "identity": {
                "projectUuid": None,
                "documentUuid": None,
                "documentType": None,
                "capturedAt": "2026-08-24T00:00:00Z",
                "bridgeService": "easyeda-bridge",
                "windowId": None,
                "gatewayVersion": GATEWAY_VERSION,
                "bridgeScriptSha256": None,
            },
            "calls": [
                {
                    "methodId": "DMT_Project.getCurrentProjectInfo#1",
                    "effect": "READ",
                    "purpose": "read identity",
                    "args": [],
                    "resultKey": "project",
                },
            ],
            "save": False,
        }
        plan["planDigest"] = plan_digest(plan)
        return plan

    def test_registry_identity_and_method_resolution(self) -> None:
        self.assertEqual(self.registry.identity["version"], "0.4.15")
        descriptor = self.registry.resolve_method("DMT_Project.getCurrentProjectInfo#1")
        self.assertEqual(descriptor.runtime_module, "dmt_Project")
        self.assertGreater(self.registry.method_count, 700)

    def test_valid_read_plan(self) -> None:
        report = self.registry.validate_plan(self.read_plan())
        self.assertTrue(report.valid, report.as_dict())
        self.assertTrue(report.executable)

    def test_registry_drift_is_rejected(self) -> None:
        plan = self.read_plan()
        plan["registry"]["version"] = "0.0.0"
        plan["planDigest"] = plan_digest(plan)
        report = self.registry.validate_plan(plan)
        self.assertFalse(report.valid)
        self.assertIn("REGISTRY_DRIFT", {issue.code for issue in report.issues})

    def test_effect_mismatch_and_unknown_method_are_rejected(self) -> None:
        plan = self.read_plan()
        plan["calls"][0]["effect"] = "WRITE"
        plan["calls"].append(
            {
                "methodId": "DMT_Project.notARealMethod#1",
                "effect": "READ",
                "purpose": "must fail",
                "args": [],
                "resultKey": "missing",
            },
        )
        plan["planDigest"] = plan_digest(plan)
        report = self.registry.validate_plan(plan)
        codes = {issue.code for issue in report.issues}
        self.assertIn("EFFECT_MISMATCH", codes)
        self.assertIn("UNKNOWN_METHOD", codes)
        self.assertIn("READ_PLAN_WRITE", codes)

    def test_digest_detects_mutation(self) -> None:
        plan = self.read_plan()
        changed = deepcopy(plan)
        changed["calls"][0]["purpose"] = "different"
        self.assertNotEqual(plan_digest(plan), plan_digest(changed))

    def test_enum_reference_is_bound_to_manifest(self) -> None:
        self.assertTrue(self.registry.validate_enum_reference("EPCB_LayerId.TOP"))
        self.assertFalse(self.registry.validate_enum_reference("EPCB_LayerId.NOT_REAL"))

    def test_undefined_sentinel_is_limited_to_optional_top_level_argument(self) -> None:
        plan = self.read_plan()
        plan["calls"] = [{
            "methodId": "SCH_PrimitiveComponent.getAll#1",
            "effect": "READ",
            "purpose": "read only the active schematic page",
            "args": [{"$undefined": True}, False],
            "resultKey": "components",
        }]
        plan["planDigest"] = plan_digest(plan)
        self.assertTrue(self.registry.validate_plan(plan).valid)

        plan["calls"] = [{
            "methodId": "SCH_PrimitiveComponent.getAllPinsByPrimitiveId#1",
            "effect": "READ",
            "purpose": "invalid required argument",
            "args": [{"$undefined": True}],
            "resultKey": "pins",
        }]
        plan["planDigest"] = plan_digest(plan)
        report = self.registry.validate_plan(plan)
        self.assertFalse(report.valid)
        self.assertIn("UNDEFINED_REFERENCE", {issue.code for issue in report.issues})

    def persistent_plan(self) -> dict:
        plan = {
            "schemaVersion": "easyeda.hardware-lifecycle.api-plan.v1",
            "planId": "unit-persistent",
            "risk": "PERSISTENT_WRITE",
            "registry": self.registry.identity,
            "identity": {
                "projectUuid": "project-1",
                "documentUuid": "page-1",
                "documentType": 1,
                "capturedAt": "2026-08-24T00:00:00Z",
                "bridgeService": "easyeda-bridge",
                "windowId": "window-1",
                "gatewayVersion": GATEWAY_VERSION,
                "bridgeScriptSha256": "a" * 64,
            },
            "calls": [
                {
                    "methodId": "SCH_PrimitiveComponent.modify#1",
                    "effect": "WRITE",
                    "purpose": "write an authorized procurement field",
                    "args": ["component-1", {"manufacturer": "Texas Instruments"}],
                    "resultKey": "modified",
                },
                {
                    "methodId": "SCH_Document.save#1",
                    "effect": "WRITE",
                    "purpose": "persist the authorized plan",
                    "args": [],
                    "resultKey": "saved",
                },
            ],
            "scope": {"allowedFields": ["Manufacturer"], "pageUuid": "page-1"},
            "save": True,
        }
        plan["planDigest"] = plan_digest(plan)
        return plan

    def test_persistent_procurement_plan_is_valid_but_needs_external_evidence(self) -> None:
        report = self.registry.validate_plan(self.persistent_plan())
        self.assertTrue(report.valid, report.as_dict())
        self.assertFalse(report.executable)

    def test_protected_component_fields_are_rejected(self) -> None:
        plan = self.persistent_plan()
        plan["calls"][0]["args"][1] = {"designator": "R999"}
        plan["planDigest"] = plan_digest(plan)
        report = self.registry.validate_plan(plan)
        self.assertFalse(report.valid)
        self.assertIn("PROTECTED_FIELD_WRITE", {issue.code for issue in report.issues})


if __name__ == "__main__":
    unittest.main()
