from __future__ import annotations

import json
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from _gateway_bootstrap import find_workbench_root
from hwlifecycle.bridge import BridgeError, OfficialBridgeClient, discover_bridge
from hwlifecycle.evidence import record_active_schematic_capture
from hwlifecycle.io_utils import load_json, sha256_file
from hwlifecycle.read_adapter import (
    build_active_schematic_code,
    build_active_schematic_plan,
    capture_active_schematic,
)
from hwlifecycle.session import DocumentIdentity, IDENTITY_CODE


PROJECT_UUID = "project-uuid-1"
DOCUMENT_UUID = "document-uuid-1"
WINDOW_ID = "window-1"


def identity_result() -> dict:
    return {
        "project": {"uuid": PROJECT_UUID, "name": "Example"},
        "document": {
            "uuid": DOCUMENT_UUID,
            "parentProjectUuid": PROJECT_UUID,
            "documentType": 1,
        },
    }


def snapshot_result() -> dict:
    identity = identity_result()
    return {
        "project": identity["project"],
        "beforeDocument": identity["document"],
        "afterDocument": identity["document"],
        "components": [
            {
                "primitiveId": "primitive-r1",
                "componentType": "part",
                "designator": "R1",
                "value": "10k",
                "uniqueId": "uid-r1",
                "device": {"libraryUuid": "lib", "uuid": "dev", "name": "10k"},
                "symbol": {"libraryUuid": "lib", "uuid": "sym", "name": "R"},
                "footprint": {"libraryUuid": "lib", "uuid": "fp", "name": "R0603"},
                "x": 100,
                "y": 200,
                "rotation": 0,
                "mirror": False,
                "addIntoBom": True,
                "addIntoPcb": True,
                "procurement": {
                    "Manufacturer": "Yageo",
                    "Manufacturer Part": "RC0603FR-0710KL",
                    "Supplier": "LCSC",
                    "Supplier Part": "C98220",
                },
                "pins": [
                    {"number": "1", "name": "1", "noConnected": False},
                    {"number": "2", "name": "2", "noConnected": False},
                ],
            }
        ],
    }


class MockBridgeHandler(BaseHTTPRequestHandler):
    windows = [{"windowId": WINDOW_ID, "connected": True, "active": True}]

    def log_message(self, format: str, *args: object) -> None:
        return

    def _send(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path == "/health":
            self._send(
                200,
                {
                    "service": "easyeda-bridge",
                    "gatewayId": "lyyyy.hardware-workbench",
                    "productId": "hardware-workbench",
                    "protocolVersion": 2,
                    "status": "ok",
                    "edaConnected": True,
                    "edaWindowCount": len(self.windows),
                    "activeWindowId": self.windows[0]["windowId"] if self.windows else None,
                },
            )
            return
        if self.path == "/eda-windows":
            windows = [
                {
                    **window,
                    "gatewayId": "lyyyy.hardware-workbench",
                    "productId": "hardware-workbench",
                    "protocolVersion": 2,
                }
                for window in self.windows
            ]
            self._send(
                200,
                {
                    "windows": windows,
                    "activeWindowId": windows[0]["windowId"] if windows else None,
                    "count": len(windows),
                },
            )
            return
        self._send(404, {"error": "not found"})

    def do_POST(self) -> None:
        if self.path != "/operations/execute":
            self._send(404, {"error": "not found"})
            return
        size = int(self.headers.get("Content-Length", "0"))
        request = json.loads(self.rfile.read(size).decode("utf-8"))
        if request.get("windowId") != WINDOW_ID:
            self._send(400, {"success": False, "error": "wrong window"})
            return
        if request.get("operation") != "workbench.official-api.execute.v1":
            self._send(400, {"success": False, "error": "wrong operation"})
            return
        code = (request.get("args") or {}).get("code")
        result = identity_result() if code == IDENTITY_CODE else snapshot_result()
        self._send(200, {"success": True, "result": result, "windowId": WINDOW_ID})


class MockBridge:
    def __enter__(self) -> "MockBridge":
        MockBridgeHandler.windows = [
            {"windowId": WINDOW_ID, "connected": True, "active": True}
        ]
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), MockBridgeHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        host, port = self.server.server_address
        self.base_url = f"http://{host}:{port}"
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)


def actual_manifest() -> dict:
    workbench = find_workbench_root()
    return load_json(workbench / "materials" / "manifests" / "api-manifest.json")


class BridgeTests(unittest.TestCase):
    def test_discovery_and_explicit_window_execution(self) -> None:
        with MockBridge() as bridge:
            endpoint = discover_bridge(bridge.base_url)
            self.assertEqual(bridge.base_url, endpoint.base_url)
            client = OfficialBridgeClient(endpoint.base_url)
            self.assertEqual(WINDOW_ID, client.resolve_window())
            result = client.execute(IDENTITY_CODE, window_id=WINDOW_ID)
            self.assertEqual(DOCUMENT_UUID, result["document"]["uuid"])

    def test_multiple_windows_require_explicit_selection(self) -> None:
        with MockBridge() as bridge:
            MockBridgeHandler.windows = [
                {"windowId": WINDOW_ID, "connected": True, "active": True},
                {"windowId": "window-2", "connected": True, "active": False},
            ]
            client = OfficialBridgeClient(bridge.base_url)
            with self.assertRaisesRegex(BridgeError, "multiple EasyEDA windows"):
                client.resolve_window()
            self.assertEqual(WINDOW_ID, client.resolve_window(WINDOW_ID))

    def test_remote_bridge_url_is_rejected(self) -> None:
        with self.assertRaisesRegex(BridgeError, "loopback"):
            OfficialBridgeClient("http://example.com:49620")


class ReadAdapterTests(unittest.TestCase):
    def test_fixed_template_has_no_mutating_document_calls(self) -> None:
        identity = DocumentIdentity(
            projectUuid=PROJECT_UUID,
            documentUuid=DOCUMENT_UUID,
            documentType="SCHEMATIC_PAGE",
            capturedAt="2026-08-24T00:00:00Z",
            bridge={
                "service": "easyeda-bridge",
                "baseUrl": "http://127.0.0.1:49620",
                "windowId": WINDOW_ID,
            },
        )
        code = build_active_schematic_code(identity)
        for forbidden in (
            ".modify(",
            ".create(",
            ".delete(",
            ".save(",
            ".openDocument(",
            ".activateDocument(",
        ):
            self.assertNotIn(forbidden, code)

    def test_actual_manifest_accepts_snapshot_plan(self) -> None:
        manifest = actual_manifest()
        identity = DocumentIdentity(
            projectUuid=PROJECT_UUID,
            documentUuid=DOCUMENT_UUID,
            documentType="SCHEMATIC_PAGE",
            capturedAt="2026-08-24T00:00:00Z",
            bridge={
                "service": "easyeda-bridge",
                "baseUrl": "http://127.0.0.1:49620",
                "windowId": WINDOW_ID,
            },
        )
        plan = build_active_schematic_plan(identity, manifest)
        from hwlifecycle.api_registry import validate_api_plan

        result = validate_api_plan(plan, manifest)
        self.assertTrue(result["valid"], result["errors"])
        self.assertTrue(result["executable"])

    def test_capture_and_immutable_evidence(self) -> None:
        manifest = actual_manifest()
        with MockBridge() as bridge, tempfile.TemporaryDirectory() as directory:
            client = OfficialBridgeClient(bridge.base_url)
            capture = capture_active_schematic(
                client, window_id=WINDOW_ID, manifest=manifest
            )
            self.assertEqual(1, capture["snapshot"]["counts"]["components"])
            self.assertEqual(2, capture["snapshot"]["counts"]["pins"])
            self.assertTrue(capture["validation"]["executable"])

            recorded = record_active_schematic_capture(directory, capture, manifest)
            self.assertEqual(recorded["snapshotSha256"], sha256_file(recorded["snapshot"]))
            self.assertEqual(recorded["apiPlanSha256"], sha256_file(recorded["apiPlan"]))
            envelope = load_json(recorded["envelope"])
            self.assertEqual("active-schematic-snapshot", envelope["artifactType"])
            self.assertEqual(DOCUMENT_UUID, envelope["sourceIdentity"]["documentUuid"])


if __name__ == "__main__":
    unittest.main()
