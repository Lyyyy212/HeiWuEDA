from __future__ import annotations

import unittest

from easyeda_gateway.window_guard import resolve_window


class WindowGuardTests(unittest.TestCase):
    def setUp(self) -> None:
        self.windows = {
            "activeWindowId": "window-new",
            "windows": [{"windowId": "window-new", "connected": True}],
        }
        self.identity = {
            "projectUuid": "project-1",
            "documentUuid": "document-1",
            "windowId": "window-old",
        }

    def test_rebind_is_explicit_and_requires_exact_identity(self) -> None:
        with self.assertRaisesRegex(Exception, "not connected"):
            resolve_window(
                self.windows,
                requested_window_id="window-old",
                identity=self.identity,
            )
        resolution = resolve_window(
            self.windows,
            requested_window_id="window-old",
            identity=self.identity,
            allow_rebind=True,
        )
        self.assertTrue(resolution.rebound)
        self.assertEqual(resolution.resolved_window_id, "window-new")

    def test_rebind_refuses_ambiguous_or_unbound_identity(self) -> None:
        with self.assertRaisesRegex(Exception, "document UUID"):
            resolve_window(
                self.windows,
                requested_window_id="window-old",
                identity={"projectUuid": "project-1"},
                allow_rebind=True,
            )
        ambiguous = {
            "windows": [
                {"windowId": "window-a", "connected": True},
                {"windowId": "window-b", "connected": True},
            ]
        }
        with self.assertRaisesRegex(Exception, "exactly one"):
            resolve_window(
                ambiguous,
                requested_window_id="window-old",
                identity=self.identity,
                allow_rebind=True,
            )


if __name__ == "__main__":
    unittest.main()
