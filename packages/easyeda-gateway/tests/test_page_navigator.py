from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from easyeda_gateway.client import BridgeClient
from easyeda_gateway.contract import ApiRegistry
from easyeda_gateway.errors import BridgeError, ContractError
from easyeda_gateway.page_navigator import (
    PAGE_NAVIGATION_RESULT_SCHEMA,
    PAGE_NAVIGATOR_ADAPTER_VERSION,
    EasyedaPageNavigator,
    SchematicPageNavigationSpec,
)

from .support import MockBridge


WORKBENCH_ROOT = Path(__file__).resolve().parents[3]
MANIFEST = WORKBENCH_ROOT / "materials" / "manifests" / "api-manifest.json"
EXPECTED_IDENTITY = {
    "projectUuid": "project-1",
    "documentUuid": "page-1",
    "documentType": 1,
}


def navigation_result(
    action: str,
    *,
    after_page: str = "page-1",
    status: str = "PASS",
    failure: str | None = None,
    restored: bool | None = None,
) -> dict:
    pages = [
        {"uuid": "page-1", "name": "Power", "parentSchematicUuid": "sch-1", "index": 0},
        {"uuid": "page-2", "name": "Analog", "parentSchematicUuid": "sch-1", "index": 1},
    ]
    return {
        "schemaVersion": PAGE_NAVIGATION_RESULT_SCHEMA,
        "adapterVersion": PAGE_NAVIGATOR_ADAPTER_VERSION,
        "status": status,
        "action": action,
        "identityBefore": {**EXPECTED_IDENTITY, "tabId": "tab-1"},
        "identityAfter": {
            "projectUuid": "project-1",
            "documentUuid": after_page,
            "documentType": 1,
            "tabId": "tab-1" if after_page == "page-1" else "tab-2",
        },
        "schematic": {"uuid": "sch-1", "name": "Main", "pages": pages},
        "targetPageUuid": "page-2" if action == "activate" else None,
        "visitedPages": [
            {
                "pageUuid": after_page,
                "tabId": "tab-1" if after_page == "page-1" else "tab-2",
                "alreadyActive": after_page == "page-1",
            }
        ],
        "restoration": {
            "attempted": action == "traverse" or status == "FAILED",
            "succeeded": restored,
            "pageUuid": "page-1",
            "tabId": "tab-1",
            "identity": {**EXPECTED_IDENTITY, "tabId": "tab-1"} if restored else None,
            "error": None,
        },
        "failure": failure,
        "saveCalled": False,
        "documentContentMutation": False,
    }


class PageNavigatorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.registry = ApiRegistry.from_file(MANIFEST)

    def adapter(self, mock: MockBridge) -> EasyedaPageNavigator:
        return EasyedaPageNavigator(self.registry, BridgeClient(mock.url))

    def test_spec_requires_uuid_only_for_activate(self) -> None:
        with self.assertRaises(ContractError):
            SchematicPageNavigationSpec("activate").normalized()
        with self.assertRaises(ContractError):
            SchematicPageNavigationSpec("list", "page-1").normalized()
        self.assertEqual(
            SchematicPageNavigationSpec(" ACTIVATE ", " page-2 ").normalized(),
            SchematicPageNavigationSpec("activate", "page-2"),
        )

    def test_state_changing_actions_require_exact_origin_identity(self) -> None:
        with MockBridge() as mock:
            adapter = self.adapter(mock)
            with self.assertRaises(ContractError):
                adapter.build_code(SchematicPageNavigationSpec("traverse"), {})
            with self.assertRaises(ContractError):
                adapter.build_code(
                    SchematicPageNavigationSpec("activate", "page-2"),
                    {"projectUuid": "project-1"},
                )

    def test_fixed_code_uses_only_navigation_and_identity_apis(self) -> None:
        with MockBridge() as mock:
            code = self.adapter(mock).build_code(
                SchematicPageNavigationSpec("activate", "page-2"),
                EXPECTED_IDENTITY,
            )
        self.assertIn("eda.dmt_Project.getCurrentProjectInfo()", code)
        self.assertIn("eda.dmt_SelectControl.getCurrentDocumentInfo()", code)
        self.assertIn("eda.dmt_EditorControl.openDocument(pageUuid)", code)
        self.assertIn("eda.dmt_EditorControl.activateDocument(tabId)", code)
        self.assertIn("item?.schematic??item", code)
        self.assertIn("saveCalled:false", code)
        self.assertNotIn("sch_Document.save", code)
        self.assertNotIn("closeDocument", code)
        self.assertNotIn("getCurrentRenderedAreaImage", code)
        self.assertNotIn("getExportDocumentFile", code)
        self.assertNotIn("//", code)

    def test_list_records_immutable_evidence_without_switching(self) -> None:
        with MockBridge(execute_result=navigation_result("list")) as mock, TemporaryDirectory() as temporary:
            result = self.adapter(mock).execute(
                SchematicPageNavigationSpec("list"),
                temporary,
                identity=EXPECTED_IDENTITY,
                window_id="window-1",
            )
            envelope = json.loads(result.evidence_path.read_text(encoding="utf-8"))
        self.assertEqual(result.action, "list")
        self.assertEqual([page["uuid"] for page in result.schematic["pages"]], ["page-1", "page-2"])
        self.assertEqual(envelope["risk"], "READ")
        self.assertFalse(envelope["safety"]["saveCalled"])
        self.assertFalse(envelope["safety"]["documentContentMutation"])
        self.assertIn("request.json", envelope["files"])
        self.assertIn("result.json", envelope["files"])

    def test_activate_intentionally_leaves_verified_target_active(self) -> None:
        with MockBridge(execute_result=navigation_result("activate", after_page="page-2")) as mock, TemporaryDirectory() as temporary:
            result = self.adapter(mock).execute(
                SchematicPageNavigationSpec("activate", "page-2"),
                temporary,
                identity=EXPECTED_IDENTITY,
            )
        self.assertEqual(result.identity_before["documentUuid"], "page-1")
        self.assertEqual(result.identity_after["documentUuid"], "page-2")
        self.assertFalse(result.restoration["attempted"])

    def test_traverse_requires_and_records_original_page_restoration(self) -> None:
        payload = navigation_result("traverse", restored=True)
        payload["visitedPages"] = [
            {"pageUuid": "page-1", "tabId": "tab-1", "alreadyActive": True},
            {"pageUuid": "page-2", "tabId": "tab-2", "alreadyActive": False},
        ]
        with MockBridge(execute_result=payload) as mock, TemporaryDirectory() as temporary:
            result = self.adapter(mock).execute(
                SchematicPageNavigationSpec("traverse"),
                temporary,
                identity=EXPECTED_IDENTITY,
            )
        self.assertEqual([item["pageUuid"] for item in result.visited_pages], ["page-1", "page-2"])
        self.assertTrue(result.restoration["attempted"])
        self.assertTrue(result.restoration["succeeded"])
        self.assertEqual(result.identity_after["documentUuid"], "page-1")

    def test_failed_activation_preserves_failure_and_restoration_evidence(self) -> None:
        payload = navigation_result(
            "activate",
            status="FAILED",
            failure="Could not activate schematic page page-2",
            restored=True,
        )
        with MockBridge(execute_result=payload) as mock, TemporaryDirectory() as temporary:
            with self.assertRaises(BridgeError):
                self.adapter(mock).execute(
                    SchematicPageNavigationSpec("activate", "page-2"),
                    temporary,
                    identity=EXPECTED_IDENTITY,
                )
            evidence_directories = list(Path(temporary).iterdir())
            self.assertEqual(len(evidence_directories), 1)
            envelope = json.loads(
                (evidence_directories[0] / "envelope.json").read_text(encoding="utf-8")
            )
        self.assertEqual(envelope["status"], "FAILED")
        self.assertTrue(envelope["safety"]["restoration"]["succeeded"])
        self.assertFalse(envelope["safety"]["automaticRetry"])


if __name__ == "__main__":
    unittest.main()
