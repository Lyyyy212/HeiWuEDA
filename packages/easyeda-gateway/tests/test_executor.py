from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from easyeda_gateway.client import BridgeClient
from easyeda_gateway.contract import ApiRegistry, plan_digest
from easyeda_gateway.executor import BridgeExecutor
from easyeda_gateway.version import GATEWAY_VERSION
from easyeda_gateway.errors import AuthorizationError

from .support import MockBridge


WORKBENCH_ROOT = Path(__file__).resolve().parents[3]
MANIFEST = WORKBENCH_ROOT / "materials" / "manifests" / "api-manifest.json"


class ExecutorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.registry = ApiRegistry.from_file(MANIFEST)

    def read_plan(self) -> dict:
        plan = {
            "schemaVersion": "easyeda.hardware-lifecycle.api-plan.v1",
            "planId": "executor-read",
            "risk": "READ",
            "registry": self.registry.identity,
            "identity": {
                "projectUuid": "project-1",
                "documentUuid": "document-1",
                "documentType": 1,
                "capturedAt": "2026-08-24T00:00:00Z",
                "bridgeService": "easyeda-bridge",
                "windowId": "window-1",
                "gatewayVersion": GATEWAY_VERSION,
                "bridgeScriptSha256": None,
            },
            "calls": [
                {
                    "methodId": "DMT_Project.getCurrentProjectInfo#1",
                    "effect": "READ",
                    "purpose": "read project",
                    "args": [],
                    "resultKey": "project",
                    "pick": ["uuid", "friendlyName"],
                },
            ],
            "save": False,
        }
        plan["planDigest"] = plan_digest(plan)
        return plan

    def test_build_code_uses_manifest_runtime_module_and_identity_guard(self) -> None:
        with MockBridge() as mock:
            executor = BridgeExecutor(self.registry, BridgeClient(mock.url))
            code = executor.build_code(self.read_plan())
        self.assertIn("eda.dmt_Project.getCurrentProjectInfo()", code)
        self.assertIn("EasyEDA identity drift", code)
        self.assertIn("friendlyName", code)
        self.assertNotIn("//", code)

    def test_build_code_renders_safe_optional_undefined(self) -> None:
        plan = self.read_plan()
        plan["calls"] = [{
            "methodId": "SCH_PrimitiveComponent.getAll#1",
            "effect": "READ",
            "purpose": "read current page components",
            "args": [{"$undefined": True}, False],
            "resultKey": "components",
        }]
        plan["planDigest"] = plan_digest(plan)
        with MockBridge() as mock:
            executor = BridgeExecutor(self.registry, BridgeClient(mock.url))
            code = executor.build_code(plan)
        self.assertIn("eda.sch_PrimitiveComponent.getAll(undefined,false)", code)

    def test_execute_records_hashed_evidence(self) -> None:
        with MockBridge() as mock, TemporaryDirectory() as temporary:
            executor = BridgeExecutor(self.registry, BridgeClient(mock.url))
            result = executor.execute(self.read_plan(), temporary)
            envelope = json.loads(result.evidence_path.read_text(encoding="utf-8"))
            self.assertEqual(envelope["bridge"]["service"], "easyeda-bridge")
            self.assertEqual(envelope["bridge"]["windowId"], "window-1")
            self.assertIn("request.json", envelope["files"])
            self.assertIn("result.json", envelope["files"])
            payload = mock.requests[-1]["payload"]
            self.assertEqual(payload["windowId"], "window-1")
            self.assertIn(
                "eda.dmt_Project.getCurrentProjectInfo()",
                payload["args"]["code"],
            )

    def test_write_execution_requires_trusted_bridge_runtime(self) -> None:
        plan = {
            "schemaVersion": "easyeda.hardware-lifecycle.api-plan.v1",
            "planId": "guarded-write",
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
                    "purpose": "write procurement field",
                    "args": ["component-1", {"manufacturer": "TI"}],
                    "resultKey": "modified",
                },
                {
                    "methodId": "SCH_Document.save#1",
                    "effect": "WRITE",
                    "purpose": "save approved write",
                    "args": [],
                    "resultKey": "saved",
                },
            ],
            "scope": {"allowedFields": ["Manufacturer"], "pageUuid": "page-1"},
            "save": True,
        }
        plan["planDigest"] = plan_digest(plan)
        with MockBridge() as mock, TemporaryDirectory() as temporary:
            executor = BridgeExecutor(self.registry, BridgeClient(mock.url))
            with self.assertRaises(AuthorizationError):
                executor.execute(plan, temporary)


if __name__ == "__main__":
    unittest.main()
