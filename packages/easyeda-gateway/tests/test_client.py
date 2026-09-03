from __future__ import annotations

import unittest
from unittest.mock import patch

from easyeda_gateway.client import (
    DEFAULT_REQUEST_TIMEOUT,
    WORKBENCH_GATEWAY_ID,
    WORKBENCH_CODE_OPERATION,
    WORKBENCH_CODE_PROFILE,
    WORKBENCH_PRODUCT_ID,
    WORKBENCH_PROTOCOL_VERSION,
    BridgeClient,
    discover_bridge,
)
from easyeda_gateway.errors import BridgeError, BridgeTimeoutError

from .support import MockBridge


class ClientTests(unittest.TestCase):
    def test_localhost_only(self) -> None:
        with self.assertRaises(BridgeError):
            BridgeClient("https://example.com:49620")

    def test_health_windows_select_and_allowlisted_operation(self) -> None:
        with MockBridge() as mock:
            client = BridgeClient(mock.url)
            self.assertEqual(client.health()["service"], "easyeda-bridge")
            self.assertEqual(client.windows()["count"], 1)
            self.assertEqual(client.select_window("window-1")["activeWindowId"], "window-1")
            response = client.execute_operation(
                "workbench.context.read.v1",
                {},
                "window-1",
            )
            self.assertTrue(response["success"])
            self.assertEqual(mock.requests[-1]["payload"]["windowId"], "window-1")
            self.assertEqual(
                mock.requests[-1]["payload"]["gatewayId"],
                WORKBENCH_GATEWAY_ID,
            )
            self.assertEqual(
                mock.requests[-1]["payload"]["productId"],
                WORKBENCH_PRODUCT_ID,
            )
            self.assertEqual(
                mock.requests[-1]["payload"]["protocolVersion"],
                WORKBENCH_PROTOCOL_VERSION,
            )

    def test_generated_code_uses_dedicated_allowlisted_operation(self) -> None:
        with MockBridge() as mock:
            response = BridgeClient(mock.url).execute_code("return 1;", "window-1")
        self.assertTrue(response["success"])
        request = mock.requests[-1]
        self.assertEqual(request["path"], "/operations/execute")
        self.assertEqual(request["payload"]["operation"], WORKBENCH_CODE_OPERATION)
        self.assertEqual(request["payload"]["args"]["profile"], WORKBENCH_CODE_PROFILE)
        self.assertEqual(len(request["payload"]["args"]["codeSha256"]), 64)

    def test_discovery_verifies_service_identity(self) -> None:
        with MockBridge() as mock:
            client = discover_bridge(mock.port, mock.port)
            self.assertEqual(client.base_url, mock.url)
            self.assertEqual(client.timeout, DEFAULT_REQUEST_TIMEOUT)

    def test_discovery_ignores_lower_generic_bridge(self) -> None:
        def health(client: BridgeClient) -> dict[str, object]:
            if client.port == 49620:
                return {"service": "easyeda-bridge", "status": "ok"}
            return {
                "service": "easyeda-bridge",
                "status": "ok",
                "gatewayId": WORKBENCH_GATEWAY_ID,
                "productId": WORKBENCH_PRODUCT_ID,
                "protocolVersion": WORKBENCH_PROTOCOL_VERSION,
            }

        with patch.object(BridgeClient, "health", autospec=True, side_effect=health):
            client = discover_bridge(49620, 49621)
        self.assertEqual(client.port, 49621)

    def test_generic_official_bridge_is_rejected(self) -> None:
        with MockBridge(gateway_id=None, product_id=None, protocol_version=None) as mock:
            with self.assertRaisesRegex(BridgeError, "Dedicated Hardware Workbench bridge"):
                BridgeClient(mock.url).health()

    def test_discovery_ignores_a_foreign_project_gateway(self) -> None:
        def health(client: BridgeClient) -> dict[str, object]:
            return {
                "service": "easyeda-bridge",
                "status": "ok",
                "gatewayId": "another.project",
                "productId": WORKBENCH_PRODUCT_ID,
                "protocolVersion": WORKBENCH_PROTOCOL_VERSION,
            }

        with patch.object(BridgeClient, "health", autospec=True, side_effect=health):
            with self.assertRaisesRegex(
                BridgeError,
                "No dedicated Hardware Workbench EasyEDA bridge found",
            ):
                discover_bridge(49620, 49621)

    def test_bridge_http_timeout_is_classified_as_unresolved_operation(self) -> None:
        with MockBridge(execute_error=(500, "Request fixture timed out after 30000ms")) as mock:
            with self.assertRaisesRegex(BridgeTimeoutError, "may still be running"):
                BridgeClient(mock.url).execute_operation(
                    "workbench.context.read.v1",
                    {},
                    "window-1",
                )

    def test_non_timeout_bridge_http_error_remains_a_regular_failure(self) -> None:
        with MockBridge(execute_error=(500, "EasyEDA rejected the method")) as mock:
            with self.assertRaises(BridgeError) as raised:
                BridgeClient(mock.url).execute_operation(
                    "workbench.context.read.v1",
                    {},
                    "window-1",
                )
        self.assertNotIsInstance(raised.exception, BridgeTimeoutError)


if __name__ == "__main__":
    unittest.main()
