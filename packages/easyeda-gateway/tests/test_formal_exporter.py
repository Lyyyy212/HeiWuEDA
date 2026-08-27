from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from easyeda_gateway.contract import ApiRegistry
from easyeda_gateway.errors import ContractError
from easyeda_gateway.formal_exporter import (
    FORMAL_EXPORT_ADAPTER_VERSION,
    FORMAL_EXPORT_RESULT_SCHEMA,
    SOURCE_NORMALIZATION_IGNORED,
    EasyedaFormalExportAdapter,
    FormalExportSpec,
    inspect_formal_artifact,
)
from tests.test_source_renderer_v22 import build_fixture_epro


WORKBENCH_ROOT = Path(__file__).resolve().parents[3]
MANIFEST = WORKBENCH_ROOT / "materials" / "manifests" / "api-manifest.json"


class FakeFormalClient:
    base_url = "http://127.0.0.1:49620"

    def __init__(self):
        self.execute_count = 0

    def health(self):
        return {"service": "easyeda-bridge", "edaConnected": True, "pendingRequests": 0}

    def windows(self):
        return {
            "windows": [{"windowId": "window-1", "connected": True, "active": True}],
            "activeWindowId": "window-1",
            "count": 1,
        }

    def execute_code(self, code: str, window_id: str):
        marker = "const __artifactPath="
        start = code.index(marker) + len(marker)
        artifact_path, _ = json.JSONDecoder().raw_decode(code[start:])
        artifact = Path(artifact_path)
        content = "Designator\tQuantity\tValue\nR1 R2\t2\t10k\n".encode("utf-16")
        artifact.write_bytes(content)
        self.execute_count += 1
        identity = {"projectUuid": "project-1", "documentUuid": "document-1", "documentType": 1}
        return {
            "success": True,
            "result": {
                "schemaVersion": FORMAL_EXPORT_RESULT_SCHEMA,
                "adapterVersion": FORMAL_EXPORT_ADAPTER_VERSION,
                "identityBefore": identity,
                "identityAfter": identity,
                "saved": True,
                "rawSourceUnchanged": False,
                "sourceUnchanged": True,
                "sourceNormalizationIgnored": list(SOURCE_NORMALIZATION_IGNORED),
                "artifact": {"size": len(content), "name": artifact.name, "type": "text/csv"},
            },
        }


class FakeProjectSourceClient(FakeFormalClient):
    def execute_code(self, code: str, window_id: str):
        marker = "const __artifactPath="
        start = code.index(marker) + len(marker)
        artifact_path, _ = json.JSONDecoder().raw_decode(code[start:])
        artifact = build_fixture_epro(
            Path(artifact_path),
            extra_sheet_uuids=["sheet-uuid-2"],
        )
        self.execute_count += 1
        identity = {"projectUuid": "project-1", "documentUuid": "sheet-uuid", "documentType": 1}
        return {
            "success": True,
            "result": {
                "schemaVersion": FORMAL_EXPORT_RESULT_SCHEMA,
                "adapterVersion": FORMAL_EXPORT_ADAPTER_VERSION,
                "identityBefore": identity,
                "identityAfter": identity,
                "saved": True,
                "projectTreeUnchanged": True,
                "projectPages": [
                    {
                        "schematicUuid": "schematic-uuid",
                        "schematicName": "Fixture Schematic",
                        "documentUuid": "sheet-uuid",
                        "pageName": "Fixture Sheet",
                    },
                    {
                        "schematicUuid": "schematic-uuid",
                        "schematicName": "Fixture Schematic",
                        "documentUuid": "sheet-uuid-2",
                        "pageName": "Fixture Sheet 2",
                    },
                ],
                "artifact": {
                    "size": artifact.stat().st_size,
                    "name": artifact.name,
                    "type": "application/octet-stream",
                },
            },
        }

class FormalExporterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.registry = ApiRegistry.from_file(MANIFEST)

    def test_builds_fixed_bom_netlist_and_source_calls(self) -> None:
        adapter = EasyedaFormalExportAdapter(self.registry, FakeFormalClient())
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            bom = adapter.build_code(FormalExportSpec("bom", "csv"), root / "bom.csv")
            netlist = adapter.build_code(FormalExportSpec("netlist", "jlceda"), root / "netlist.net")
            source = adapter.build_code(FormalExportSpec("source", "epro"), root / "source.epro")
            project_source = adapter.build_code(
                FormalExportSpec("project-source", "epro"),
                root / "project.epro",
            )
        self.assertIn("getBomFile", bom)
        self.assertIn("ESYS_NetlistType.JLCEDA_PRO", netlist)
        self.assertIn("getDocumentFile", source)
        self.assertIn("getDocumentSource", source)
        self.assertIn("delete meta.client", source)
        self.assertIn("delete meta.updateTime", source)
        self.assertIn("delete meta.version", source)
        self.assertIn("__rawSourceUnchanged=__sourceBefore===__sourceAfter", source)
        self.assertIn("__normalizedSourceBefore===__normalizedSourceAfter", source)
        self.assertIn("sourceNormalizationIgnored", source)
        self.assertIn("getProjectFile", project_source)
        self.assertIn("getAllSchematicsInfo", project_source)
        self.assertIn("projectTreeUnchanged", project_source)
        for code in (bom, netlist, source, project_source):
            self.assertIn("saveFileToFileSystem(__artifactPath,__file,undefined,false)", code)
            self.assertNotIn("//", code)

    def test_project_source_export_matches_live_tree_to_archive_pages(self) -> None:
        client = FakeProjectSourceClient()
        adapter = EasyedaFormalExportAdapter(self.registry, client)
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            result = adapter.execute(
                FormalExportSpec("project-source", "epro"),
                root / "evidence",
                identity={"projectUuid": "project-1", "documentUuid": "sheet-uuid"},
                safety_state_path=root / "safety.json",
            )
            envelope = json.loads(result.evidence_path.read_text(encoding="utf-8"))

        self.assertEqual(client.execute_count, 1)
        self.assertEqual(result.inspection["sheetCount"], 2)
        self.assertTrue(envelope["projectTreePreservation"]["treeUnchanged"])
        self.assertTrue(envelope["projectTreePreservation"]["pageUuidSetMatch"])

    def test_executes_one_csv_export_and_records_inspection(self) -> None:
        client = FakeFormalClient()
        adapter = EasyedaFormalExportAdapter(self.registry, client)
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            result = adapter.execute(
                FormalExportSpec("bom", "csv"),
                root / "evidence",
                identity={"projectUuid": "project-1", "documentUuid": "document-1"},
                safety_state_path=root / "safety.json",
            )
            envelope = json.loads(result.evidence_path.read_text(encoding="utf-8"))
        self.assertEqual(client.execute_count, 1)
        self.assertEqual(result.inspection["delimiter"], "tab")
        self.assertEqual(result.inspection["dataRowCount"], 1)
        self.assertEqual(envelope["safety"]["executionModel"], "ONE_OFFICIAL_CALL_PER_BRIDGE_REQUEST")

    def test_source_export_records_only_the_explicit_dochead_allowlist(self) -> None:
        client = FakeFormalClient()
        adapter = EasyedaFormalExportAdapter(self.registry, client)
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            result = adapter.execute(
                FormalExportSpec("source", "epro"),
                root / "evidence",
                identity={"projectUuid": "project-1", "documentUuid": "document-1"},
                safety_state_path=root / "safety.json",
            )
            envelope = json.loads(result.evidence_path.read_text(encoding="utf-8"))
        self.assertEqual(client.execute_count, 1)
        self.assertFalse(envelope["sourcePreservation"]["rawSourceUnchanged"])
        self.assertTrue(envelope["sourcePreservation"]["sourceUnchanged"])
        self.assertEqual(
            envelope["sourcePreservation"]["normalizationIgnored"],
            list(SOURCE_NORMALIZATION_IGNORED),
        )

    def test_unverified_xlsx_is_blocked_before_execute(self) -> None:
        client = FakeFormalClient()
        adapter = EasyedaFormalExportAdapter(self.registry, client)
        with TemporaryDirectory() as temporary:
            evidence_root = Path(temporary) / "evidence"
            with self.assertRaisesRegex(ContractError, "DOCUMENTED_UNVERIFIED"):
                adapter.execute(
                    FormalExportSpec("bom", "xlsx"),
                    evidence_root,
                    safety_state_path=Path(temporary) / "safety.json",
                )
            evidence_directory = next(evidence_root.iterdir())
            envelope = json.loads((evidence_directory / "envelope.json").read_text(encoding="utf-8"))
        self.assertEqual(client.execute_count, 0)
        self.assertEqual(envelope["safety"]["rejectionStage"], "CAPABILITY_ADMISSION")
        self.assertFalse(envelope["safety"]["officialCallIssued"])

    def test_jlceda_netlist_inspection_requires_components(self) -> None:
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "netlist.net"
            path.write_text(json.dumps({"components": {"R1": {}}}), encoding="utf-8")
            inspection = inspect_formal_artifact(path, FormalExportSpec("netlist", "jlceda"))
        self.assertEqual(inspection["componentCount"], 1)
