from __future__ import annotations

import unittest

from easyeda_gateway.client import DEFAULT_REQUEST_TIMEOUT, BridgeClient, discover_bridge
from easyeda_gateway.errors import BridgeError, BridgeTimeoutError

from .support import MockBridge


class ClientTests(unittest.TestCase):
    def test_localhost_only(self) -> None:
        with self.assertRaises(BridgeError):
            BridgeClient("https://example.com:49620")

    def test_health_windows_select_and_execute(self) -> None:
        with MockBridge() as mock:
            client = BridgeClient(mock.url)
            self.assertEqual(client.health()["service"], "easyeda-bridge")
            self.assertEqual(client.windows()["count"], 1)
            self.assertEqual(client.select_window("window-1")["activeWindowId"], "window-1")
            response = client.execute_code("return 1;", "window-1")
            self.assertTrue(response["success"])
            self.assertEqual(mock.requests[-1]["payload"]["windowId"], "window-1")

    def test_discovery_verifies_service_identity(self) -> None:
        with MockBridge() as mock:
            client = discover_bridge(mock.port, mock.port)
            self.assertEqual(client.base_url, mock.url)
            self.assertEqual(client.timeout, DEFAULT_REQUEST_TIMEOUT)

    def test_official_bridge_http_timeout_is_classified_as_unresolved_execution(self) -> None:
        with MockBridge(execute_error=(500, "Request fixture timed out after 30000ms")) as mock:
            with self.assertRaisesRegex(BridgeTimeoutError, "may still be running"):
                BridgeClient(mock.url).execute_code("return 1;", "window-1")

    def test_non_timeout_bridge_http_error_remains_a_regular_failure(self) -> None:
        with MockBridge(execute_error=(500, "EasyEDA rejected the method")) as mock:
            with self.assertRaises(BridgeError) as raised:
                BridgeClient(mock.url).execute_code("return 1;", "window-1")
        self.assertNotIsInstance(raised.exception, BridgeTimeoutError)


if __name__ == "__main__":
    unittest.main()
