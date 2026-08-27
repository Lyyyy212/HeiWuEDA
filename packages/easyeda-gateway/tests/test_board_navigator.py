from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from easyeda_gateway.board_navigator import (
    BOARD_NAVIGATION_RESULT_SCHEMA,
    BOARD_NAVIGATOR_ADAPTER_VERSION,
    BoardDocumentNavigationSpec,
    EasyedaBoardDocumentNavigator,
)
from easyeda_gateway.client import BridgeClient
from easyeda_gateway.contract import ApiRegistry
from easyeda_gateway.errors import BridgeError, ContractError

from .support import MockBridge


WORKBENCH_ROOT = Path(__file__).resolve().parents[3]
MANIFEST = WORKBENCH_ROOT / "materials" / "manifests" / "api-manifest.json"
ORIGIN = {
    "projectUuid": "project-1",
    "documentUuid": "page-1",
    "documentType": 1,
}


def navigation_result(
    action: str,
    *,
    after_uuid: str = "page-1",
    after_type: int = 1,
    status: str = "PASS",
    failure: str | None = None,
    restored: bool | None = None,
) -> dict:
    documents = [
        {
            "uuid": "page-1",
            "name": "Power",
            "documentType": 1,
            "parentProjectUuid": "project-1",
            "boardName": "Board 1",
        },
        {
            "uuid": "pcb-1",
            "name": "PCB 1",
            "documentType": 3,
            "parentProjectUuid": "project-1",
            "boardName": "Board 1",
        },
    ]
    return {
        "schemaVersion": BOARD_NAVIGATION_RESULT_SCHEMA,
        "adapterVersion": BOARD_NAVIGATOR_ADAPTER_VERSION,
        "status": status,
        "action": action,
        "identityBefore": {**ORIGIN, "tabId": "tab-1"},
        "identityAfter": {
            "projectUuid": "project-1",
            "documentUuid": after_uuid,
            "documentType": after_type,
            "tabId": "tab-1" if after_uuid == "page-1" else "tab-pcb",
        },
        "boards": [
            {
                "name": "Board 1",
                "index": 0,
                "parentProjectUuid": "project-1",
                "schematic": {"uuid": "sch-1", "name": "SCH", "pages": [documents[0]]},
                "pcb": documents[1],
            }
        ],
        "documents": documents,
        "targetDocumentUuid": "pcb-1" if action == "activate" else None,
        "targetDocumentType": 3 if action == "activate" else None,
        "visitedDocument": (
            {**documents[1], "tabId": "tab-pcb", "alreadyActive": False}
            if action == "activate" and status == "PASS"
            else None
        ),
        "restoration": {
            "attempted": status == "FAILED",
            "succeeded": restored,
            "documentUuid": "page-1",
            "documentType": 1,
            "tabId": "tab-1",
            "identity": {**ORIGIN, "tabId": "tab-1"} if restored else None,
            "error": None,
        },
        "failure": failure,
        "saveCalled": False,
        "documentContentMutation": False,
    }


class BoardNavigatorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.registry = ApiRegistry.from_file(MANIFEST)

    def adapter(self, mock: MockBridge) -> EasyedaBoardDocumentNavigator:
        return EasyedaBoardDocumentNavigator(self.registry, BridgeClient(mock.url))

    def test_spec_requires_exact_supported_target(self) -> None:
        with self.assertRaises(ContractError):
            BoardDocumentNavigationSpec("activate").normalized()
        with self.assertRaises(ContractError):
            BoardDocumentNavigationSpec("activate", "pcb-1", 2).normalized()
        with self.assertRaises(ContractError):
            BoardDocumentNavigationSpec("list", "pcb-1", 3).normalized()

    def test_activation_requires_exact_origin_identity(self) -> None:
        with MockBridge() as mock:
            adapter = self.adapter(mock)
            with self.assertRaises(ContractError):
                adapter.build_code(
                    BoardDocumentNavigationSpec("activate", "pcb-1", 3),
                    {"projectUuid": "project-1"},
                )
            code = adapter.build_code(
                BoardDocumentNavigationSpec("activate", "pcb-1", 3),
                {"projectUuid": "project-1", "documentUuid": "page-1"},
            )
            self.assertIn('"documentType":null', code)

    def test_fixed_code_uses_board_inventory_and_navigation_only(self) -> None:
        with MockBridge() as mock:
            code = self.adapter(mock).build_code(
                BoardDocumentNavigationSpec("activate", "pcb-1", 3), ORIGIN
            )
        self.assertIn("eda.dmt_Board.getAllBoardsInfo()", code)
        self.assertIn("eda.dmt_EditorControl.openDocument(__targetUuid)", code)
        self.assertIn("eda.dmt_EditorControl.activateDocument(tabId)", code)
        self.assertIn("saveCalled:false", code)
        self.assertNotIn("closeDocument", code)
        self.assertNotIn("Document.save", code)
        self.assertNotIn("//", code)

    def test_list_preserves_identity_and_records_evidence(self) -> None:
        with MockBridge(execute_result=navigation_result("list")) as mock, TemporaryDirectory() as temporary:
            result = self.adapter(mock).execute(
                BoardDocumentNavigationSpec("list"),
                temporary,
                identity=ORIGIN,
                window_id="window-1",
            )
            envelope = json.loads(result.evidence_path.read_text(encoding="utf-8"))
        self.assertEqual([item["uuid"] for item in result.documents], ["page-1", "pcb-1"])
        self.assertEqual(envelope["risk"], "READ")
        self.assertFalse(envelope["safety"]["saveCalled"])

    def test_activate_leaves_exact_pcb_active(self) -> None:
        payload = navigation_result("activate", after_uuid="pcb-1", after_type=3)
        with MockBridge(execute_result=payload) as mock, TemporaryDirectory() as temporary:
            result = self.adapter(mock).execute(
                BoardDocumentNavigationSpec("activate", "pcb-1", 3),
                temporary,
                identity=ORIGIN,
            )
        self.assertEqual(result.identity_after["documentUuid"], "pcb-1")
        self.assertEqual(result.identity_after["documentType"], 3)
        self.assertFalse(result.restoration["attempted"])

    def test_failed_activation_records_verified_restoration(self) -> None:
        payload = navigation_result(
            "activate",
            status="FAILED",
            failure="Could not activate board document pcb-1",
            restored=True,
        )
        with MockBridge(execute_result=payload) as mock, TemporaryDirectory() as temporary:
            with self.assertRaises(BridgeError):
                self.adapter(mock).execute(
                    BoardDocumentNavigationSpec("activate", "pcb-1", 3),
                    temporary,
                    identity=ORIGIN,
                )
            envelope_path = next(Path(temporary).iterdir()) / "envelope.json"
            envelope = json.loads(envelope_path.read_text(encoding="utf-8"))
        self.assertEqual(envelope["status"], "FAILED")
        self.assertTrue(envelope["safety"]["restoration"]["succeeded"])


if __name__ == "__main__":
    unittest.main()
