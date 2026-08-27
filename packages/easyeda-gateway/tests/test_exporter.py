from __future__ import annotations

import base64
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
import zipfile

from easyeda_gateway.contract import ApiRegistry
from easyeda_gateway.artifact_io import publish_copy_no_overwrite
from easyeda_gateway.errors import BridgeError, BridgeTimeoutError, ContractError
from easyeda_gateway.exporter import (
    COMPATIBILITY_CONTRACT,
    EXPORT_METHOD_ID,
    EXPORT_RESULT_SCHEMA,
    EasyedaExportAdapter,
    SchematicExportSpec,
)


WORKBENCH_ROOT = Path(__file__).resolve().parents[3]
MANIFEST = WORKBENCH_ROOT / "materials" / "manifests" / "api-manifest.json"
PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


class FakeExportClient:
    base_url = "http://127.0.0.1:49620"

    def __init__(self) -> None:
        self.requests: list[dict[str, str]] = []

    def health(self) -> dict[str, object]:
        return {
            "service": "easyeda-bridge",
            "edaConnected": True,
            "activeWindowId": "window-1",
        }

    def windows(self) -> dict[str, object]:
        return {
            "windows": [{"windowId": "window-1", "connected": True, "active": True}],
            "activeWindowId": "window-1",
            "count": 1,
        }

    def execute_code(self, code: str, window_id: str) -> dict[str, object]:
        marker = "const __artifactPath="
        start = code.index(marker) + len(marker)
        artifact_path, _ = json.JSONDecoder().raw_decode(code[start:])
        target = Path(artifact_path)
        target.write_bytes(PNG_1X1)
        self.requests.append({"code": code, "windowId": window_id, "artifactPath": str(target)})
        identity = {
            "projectUuid": "project-1",
            "documentUuid": "document-1",
            "documentType": 1,
        }
        return {
            "success": True,
            "windowId": window_id,
            "result": {
                "schemaVersion": EXPORT_RESULT_SCHEMA,
                "adapterVersion": "1.0.0",
                "identityBefore": identity,
                "identityAfter": identity,
                "saved": True,
                "artifact": {
                    "path": str(target),
                    "name": target.name,
                    "type": "image/png",
                    "size": len(PNG_1X1),
                },
            },
        }


class FailingExportClient(FakeExportClient):
    def execute_code(self, code: str, window_id: str) -> dict[str, object]:
        raise BridgeError("simulated export timeout")


class TimeoutExportClient(FakeExportClient):
    def execute_code(self, code: str, window_id: str) -> dict[str, object]:
        raise BridgeTimeoutError("simulated transport timeout")


class RestartedExportClient(FakeExportClient):
    def windows(self) -> dict[str, object]:
        return {
            "windows": [{"windowId": "window-new", "connected": True, "active": True}],
            "activeWindowId": "window-new",
            "count": 1,
        }


class BundledExportClient(FakeExportClient):
    def execute_code(self, code: str, window_id: str) -> dict[str, object]:
        marker = "const __artifactPath="
        start = code.index(marker) + len(marker)
        artifact_path, _ = json.JSONDecoder().raw_decode(code[start:])
        target = Path(artifact_path)
        with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_STORED) as archive:
            archive.writestr("page-1.png", PNG_1X1)
            archive.writestr("page-2.png", PNG_1X1)
        self.requests.append({"code": code, "windowId": window_id, "artifactPath": str(target)})
        identity = {"projectUuid": "project-1", "documentUuid": "document-1", "documentType": 1}
        return {
            "success": True,
            "windowId": window_id,
            "result": {
                "schemaVersion": EXPORT_RESULT_SCHEMA,
                "adapterVersion": "1.0.0",
                "identityBefore": identity,
                "identityAfter": identity,
                "saved": True,
                "artifact": {
                    "path": str(target),
                    "name": target.name,
                    "type": "application/zip",
                    "size": target.stat().st_size,
                },
            },
        }


class ExportAdapterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.registry = ApiRegistry.from_file(MANIFEST)

    def test_deprecated_export_is_quarantined_without_weakening_registry(self) -> None:
        descriptor = self.registry.resolve_method(EXPORT_METHOD_ID)
        self.assertTrue(descriptor.deprecated)
        self.assertEqual(COMPATIBILITY_CONTRACT["status"], "QUARANTINED_CAPABILITY_MATRIX")
        self.assertEqual(COMPATIBILITY_CONTRACT["verifiedScope"], "Current Schematic")
        self.assertTrue(COMPATIBILITY_CONTRACT["ordinaryTypedPlansRemainBlocked"])

    def test_generated_current_page_png_code_is_fixed_and_identity_guarded(self) -> None:
        adapter = EasyedaExportAdapter(self.registry, FakeExportClient())
        code = adapter.build_code(
            SchematicExportSpec(scope="current-page"),
            Path("evidence") / "page.png",
            {"projectUuid": "project-1", "documentUuid": "document-1"},
        )
        self.assertIn("ESCH_ExportDocumentFileType.PNG", code)
        self.assertIn('"Current Schematic Page"', code)
        self.assertIn("saveFileToFileSystem(__artifactPath,__file,undefined,false)", code)
        self.assertIn("EasyEDA identity changed during schematic export", code)
        self.assertNotIn("//", code)
        self.assertNotIn(".modify(", code)
        self.assertNotIn(".save(", code)

    def test_execute_records_immutable_artifact_and_published_copy(self) -> None:
        client = FakeExportClient()
        adapter = EasyedaExportAdapter(self.registry, client)
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            published = root / "published" / "page.png"
            result = adapter.execute(
                SchematicExportSpec(),
                root / "evidence",
                identity={
                    "projectUuid": "project-1",
                    "documentUuid": "document-1",
                    "windowId": "window-1",
                },
                output_path=published,
            )
            envelope = json.loads(result.evidence_path.read_text(encoding="utf-8"))
            request = json.loads((result.evidence_path.parent / "request.json").read_text(encoding="utf-8"))
            self.assertEqual(result.artifact_path.read_bytes(), PNG_1X1)
            self.assertEqual(result.spec.scope, "current-schematic")
            self.assertEqual(published.read_bytes(), PNG_1X1)
        self.assertEqual(result.identity["documentUuid"], "document-1")
        self.assertEqual(result.inspection["width"], 1)
        self.assertEqual(result.inspection["height"], 1)
        self.assertEqual(envelope["risk"], "READ_WITH_LOCAL_ARTIFACT")
        self.assertEqual(envelope["status"], "PASS")
        self.assertEqual(envelope["spec"]["theme"], result.spec.theme)
        self.assertEqual(request["compatibility"]["methodId"], EXPORT_METHOD_ID)
        self.assertEqual(client.requests[0]["windowId"], "window-1")

    def test_execute_accepts_official_multi_page_png_bundle(self) -> None:
        adapter = EasyedaExportAdapter(self.registry, BundledExportClient())
        with TemporaryDirectory() as temporary:
            result = adapter.execute(
                SchematicExportSpec(),
                Path(temporary) / "evidence",
                identity={"projectUuid": "project-1", "documentUuid": "document-1"},
            )
            envelope = json.loads(result.evidence_path.read_text(encoding="utf-8"))
            self.assertTrue(all(Path(item["path"]).is_file() for item in result.inspection["pages"]))
        self.assertEqual("application/zip", result.inspection["mediaType"])
        self.assertEqual(2, result.inspection["pageCount"])
        self.assertEqual(5, len(envelope["files"]))

    def test_output_suffix_and_no_overwrite_are_enforced(self) -> None:
        adapter = EasyedaExportAdapter(self.registry, FakeExportClient())
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            with self.assertRaises(ContractError):
                adapter.execute(SchematicExportSpec(), root / "evidence-a", output_path=root / "page.pdf")
            existing = root / "page.png"
            existing.write_bytes(b"keep")
            with self.assertRaises(ContractError):
                adapter.execute(SchematicExportSpec(), root / "evidence-b", output_path=existing)
            self.assertEqual(existing.read_bytes(), b"keep")

    def test_explicit_rebind_uses_only_connected_window_with_identity_guard(self) -> None:
        client = RestartedExportClient()
        adapter = EasyedaExportAdapter(self.registry, client)
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            result = adapter.execute(
                SchematicExportSpec(),
                root / "evidence",
                identity={
                    "projectUuid": "project-1",
                    "documentUuid": "document-1",
                    "windowId": "window-old",
                },
                allow_window_rebind=True,
                safety_state_path=root / "safety.json",
            )
            envelope = json.loads(result.evidence_path.read_text(encoding="utf-8"))
        self.assertEqual(client.requests[0]["windowId"], "window-new")
        self.assertTrue(envelope["bridge"]["windowResolution"]["rebound"])
        self.assertEqual(
            envelope["bridge"]["windowResolution"]["requestedWindowId"],
            "window-old",
        )

    def test_publication_helper_never_replaces_a_racing_target(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.png"
            target = root / "target.png"
            source.write_bytes(PNG_1X1)
            target.write_bytes(b"created by another process")
            with self.assertRaises(ContractError):
                publish_copy_no_overwrite(source, target)
            self.assertEqual(target.read_bytes(), b"created by another process")

    def test_runtime_failure_records_complete_failure_envelope(self) -> None:
        adapter = EasyedaExportAdapter(self.registry, FailingExportClient())
        with TemporaryDirectory() as temporary:
            evidence_root = Path(temporary) / "evidence"
            with self.assertRaisesRegex(BridgeError, "simulated export timeout"):
                adapter.execute(SchematicExportSpec(), evidence_root)
            directories = list(evidence_root.iterdir())
            self.assertEqual(len(directories), 1)
            envelope = json.loads((directories[0] / "envelope.json").read_text(encoding="utf-8"))
            failure = json.loads((directories[0] / "failure.json").read_text(encoding="utf-8"))
            self.assertEqual(envelope["status"], "FAIL")
            self.assertEqual(envelope["error"]["type"], "BridgeError")
            self.assertIn("failure.json", envelope["files"])
            self.assertIn("request.json", envelope["files"])
            self.assertEqual(failure["spec"]["officialScope"], "Current Schematic")

    def test_known_hanging_current_page_scope_is_blocked_before_execute(self) -> None:
        client = FakeExportClient()
        adapter = EasyedaExportAdapter(self.registry, client)
        with TemporaryDirectory() as temporary:
            evidence_root = Path(temporary) / "evidence"
            with self.assertRaisesRegex(ContractError, "BLOCKED_KNOWN_HANG"):
                adapter.execute(
                    SchematicExportSpec(scope="current-page"),
                    evidence_root,
                    safety_state_path=Path(temporary) / "safety.json",
                )
            evidence_directory = next(evidence_root.iterdir())
            envelope = json.loads((evidence_directory / "envelope.json").read_text(encoding="utf-8"))
        self.assertEqual(client.requests, [])
        self.assertEqual(envelope["safety"]["rejectionStage"], "CAPABILITY_ADMISSION")
        self.assertFalse(envelope["safety"]["officialCallIssued"])

    def test_transport_timeout_opens_persistent_circuit_breaker(self) -> None:
        adapter = EasyedaExportAdapter(self.registry, TimeoutExportClient())
        with TemporaryDirectory() as temporary:
            state = Path(temporary) / "safety.json"
            with self.assertRaises(BridgeTimeoutError):
                adapter.execute(
                    SchematicExportSpec(),
                    Path(temporary) / "evidence",
                    safety_state_path=state,
                )
            value = json.loads(state.read_text(encoding="utf-8"))
            self.assertEqual(value["status"], "OPEN")
            self.assertTrue(value["recoveryRequired"])


if __name__ == "__main__":
    unittest.main()
