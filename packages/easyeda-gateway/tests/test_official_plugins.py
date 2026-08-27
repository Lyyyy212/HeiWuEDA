from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
import zipfile

from easyeda_gateway.contract import ApiRegistry
from easyeda_gateway.export_safety import ALLOWED_STATUS, CAPABILITIES
from easyeda_gateway.official_plugins import (
    DEFINITIONS,
    OFFICIAL_PLUGIN_ADAPTER_VERSION,
    OFFICIAL_PLUGIN_RESULT_SCHEMA,
    EasyedaOfficialPluginAdapter,
    OfficialPluginSpec,
    inspect_official_plugin_artifact,
)


WORKBENCH_ROOT = Path(__file__).resolve().parents[3]
MANIFEST = WORKBENCH_ROOT / "materials" / "manifests" / "api-manifest.json"


def _dfm_report() -> dict[str, object]:
    rows = [
        {
            "number": number,
            "item": f"check-{number}",
            "actualValue": "ok",
            "standardValue": "ok",
            "result": "success",
        }
        for number in range(1, 19)
    ]
    return {
        "result": {
            "timestamp": 1,
            "results": rows,
            "passed": True,
            "errorCount": 0,
            "warningCount": 0,
        },
        "meta": [{"label": "板材", "value": "FR4"}],
    }


class FakeOfficialPluginClient:
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
        if "kind:\"dfm\"" in code:
            artifact.write_text(json.dumps(_dfm_report(), ensure_ascii=False), encoding="utf-8")
            kind = "dfm"
        elif "kind:\"manufacturing-svg\"" in code:
            with zipfile.ZipFile(artifact, "w") as archive:
                archive.writestr("layers/top.svg", '<svg xmlns="http://www.w3.org/2000/svg"/>')
            kind = "manufacturing-svg"
        else:
            artifact.write_text(
                "$HEADER\nGENCAD 1.4\n$ENDHEADER\n$BOARD\n$ENDBOARD\n"
                "$COMPONENTS\nCOMPONENT \"R1\"\n$ENDCOMPONENTS\n"
                "$SIGNALS\nSIGNAL \"GND\"\n$ENDSIGNALS\n$END\n",
                encoding="utf-8",
            )
            kind = "gencad"
        self.execute_count += 1
        identity = {"projectUuid": "project-1", "documentUuid": "pcb-1", "documentType": 3}
        return {
            "success": True,
            "result": {
                "schemaVersion": OFFICIAL_PLUGIN_RESULT_SCHEMA,
                "adapterVersion": OFFICIAL_PLUGIN_ADAPTER_VERSION,
                "kind": kind,
                "saved": True,
                "identityBefore": identity,
                "identityAfter": identity,
                "plugin": {"captureCount": 1},
            },
        }


class OfficialPluginTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.registry = ApiRegistry.from_file(MANIFEST)

    def test_source_pins_and_bundles_match(self) -> None:
        adapter = EasyedaOfficialPluginAdapter(self.registry, FakeOfficialPluginClient())
        for definition in DEFINITIONS.values():
            bundle = adapter.runtime_root / definition.bundle_name
            self.assertTrue(bundle.is_file())
            self.assertEqual(len(definition.source_commit), 40)
            self.assertEqual(len(definition.bundle_sha256), 64)

    def test_build_code_locks_identity_and_redirects_artifacts(self) -> None:
        adapter = EasyedaOfficialPluginAdapter(self.registry, FakeOfficialPluginClient())
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            dfm = adapter.build_code(OfficialPluginSpec("dfm"), root / "dfm.json")
            svg = adapter.build_code(OfficialPluginSpec("manufacturing-svg"), root / "svg.zip")
            gencad = adapter.build_code(OfficialPluginSpec("gencad"), root / "board.cad")
        self.assertIn("pcbDfmWithMaterial", dfm)
        self.assertIn("setExtensionUserConfig", dfm)
        self.assertIn("const ESYS_LogType=Object.freeze", dfm)
        self.assertIn("const ESYS_BottomPanelTab=Object.freeze", dfm)
        self.assertIn("const EPCB_LayerId=Object.freeze", dfm)
        self.assertIn("exportCurrentBoardToSvg", svg)
        self.assertIn("exportGencad", gencad)
        for code in (dfm, svg, gencad):
            self.assertIn("saveFileToFileSystem", code)
            self.assertIn('"documentType":3', code)
            self.assertIn("identity changed", code)
            self.assertIn("__captureCount", code)

    def test_inspectors_reject_or_accept_expected_contracts(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            dfm = root / "dfm.json"
            dfm.write_text(json.dumps(_dfm_report(), ensure_ascii=False), encoding="utf-8")
            self.assertEqual(
                inspect_official_plugin_artifact(dfm, OfficialPluginSpec("dfm"))["checkCount"],
                18,
            )
            svg = root / "svg.zip"
            with zipfile.ZipFile(svg, "w") as archive:
                archive.writestr("top.svg", '<svg xmlns="http://www.w3.org/2000/svg"/>')
            self.assertEqual(
                inspect_official_plugin_artifact(svg, OfficialPluginSpec("manufacturing-svg"))["svgCount"],
                1,
            )
            gencad = root / "board.cad"
            gencad.write_text(
                "$HEADER\n$ENDHEADER\n$BOARD\n$ENDBOARD\n$COMPONENTS\n"
                "COMPONENT \"U1\"\n$ENDCOMPONENTS\n$SIGNALS\nSIGNAL \"VCC\"\n"
                "$ENDSIGNALS\n$END\n",
                encoding="utf-8",
            )
            inspection = inspect_official_plugin_artifact(gencad, OfficialPluginSpec("gencad"))
            self.assertEqual(inspection["componentCount"], 1)
            self.assertEqual(inspection["signalCount"], 1)

    def test_each_qualified_adapter_executes_once_and_records_evidence(self) -> None:
        client = FakeOfficialPluginClient()
        adapter = EasyedaOfficialPluginAdapter(self.registry, client)
        originals = {key: CAPABILITIES[definition.capability_id] for key, definition in DEFINITIONS.items()}
        try:
            for definition in DEFINITIONS.values():
                CAPABILITIES[definition.capability_id] = replace(
                    CAPABILITIES[definition.capability_id],
                    status=ALLOWED_STATUS,
                )
            with TemporaryDirectory() as temporary:
                root = Path(temporary)
                for kind in DEFINITIONS:
                    result = adapter.export(
                        OfficialPluginSpec(kind),
                        root / "evidence",
                        identity={"projectUuid": "project-1", "documentUuid": "pcb-1"},
                        safety_state_path=root / "safety.json",
                    )
                    envelope = json.loads(result.evidence_path.read_text(encoding="utf-8"))
                    self.assertEqual(envelope["safety"]["automaticRetry"], False)
                    self.assertTrue(result.artifact_path.is_file())
        finally:
            for kind, capability in originals.items():
                CAPABILITIES[DEFINITIONS[kind].capability_id] = capability
        self.assertEqual(client.execute_count, 3)


if __name__ == "__main__":
    unittest.main()
