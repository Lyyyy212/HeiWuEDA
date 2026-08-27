from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from easyeda_gateway.errors import BridgeError, BridgeTimeoutError, ContractError
from easyeda_gateway.export_safety import (
    ExportSafetyController,
    capability_report,
    refuse_epro_visual_render,
)


class FakeClient:
    base_url = "http://127.0.0.1:49620"

    def health(self):
        return {"service": "easyeda-bridge", "pendingRequests": 0}


class ExportSafetyTests(unittest.TestCase):
    def test_capability_report_exposes_known_hang_and_no_retry(self) -> None:
        report = capability_report()
        capabilities = {item["capabilityId"]: item for item in report["capabilities"]}
        self.assertFalse(report["automaticRetry"])
        self.assertFalse(report["timeoutCancelsEasyEdaOperation"])
        self.assertEqual(capabilities["visual.current-page.png"]["status"], "BLOCKED_KNOWN_HANG")
        self.assertTrue(capabilities["bom.csv"]["executable"])
        for capability_id in (
            "pcb.dfm-report",
            "pcb.manufacturing-svg",
            "pcb.gencad",
        ):
            self.assertEqual(capabilities[capability_id]["status"], "VERIFIED_SERIAL")
            self.assertTrue(capabilities[capability_id]["executable"])
            self.assertEqual(capabilities[capability_id]["defaultTimeoutSeconds"], 30)
        self.assertEqual(report["derivedVisualPolicy"]["status"], "DISABLED_BY_POLICY")
        self.assertEqual(
            report["derivedVisualPolicy"]["admittedOfficialSources"],
            ["visual.current-schematic.png", "visual.current-schematic.pdf"],
        )

    def test_epro_visual_routes_are_refused_by_policy(self) -> None:
        for command in ("schematic-source-render", "schematic-project-source-render"):
            with self.subTest(command=command):
                with self.assertRaisesRegex(ContractError, "DISABLED_BY_POLICY"):
                    refuse_epro_visual_render(command)

    def test_blocked_capability_never_creates_active_lock(self) -> None:
        with TemporaryDirectory() as temporary:
            controller = ExportSafetyController(Path(temporary) / "state.json")
            with self.assertRaisesRegex(ContractError, "BLOCKED_KNOWN_HANG"):
                controller.acquire("visual.current-page.png", FakeClient(), "window-1")
            self.assertFalse(controller.lock_path.exists())

    def test_timeout_trips_breaker_and_reset_requires_reason(self) -> None:
        with TemporaryDirectory() as temporary:
            controller = ExportSafetyController(Path(temporary) / "state.json")
            controller.acquire("visual.current-schematic.png", FakeClient(), "window-1")
            controller.finish(success=False, error=BridgeTimeoutError("timeout"))
            self.assertEqual(controller.status()["status"], "OPEN")
            with self.assertRaises(ContractError):
                controller.reset("")
            self.assertEqual(controller.reset("EasyEDA restarted")["status"], "CLOSED")

    def test_single_flight_lock_blocks_second_export(self) -> None:
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "state.json"
            first = ExportSafetyController(path)
            second = ExportSafetyController(path)
            first.acquire("visual.current-schematic.png", FakeClient(), "window-1")
            with self.assertRaisesRegex(BridgeError, "Another EasyEDA export"):
                second.acquire("bom.csv", FakeClient(), "window-1")
            first.finish(success=True)
