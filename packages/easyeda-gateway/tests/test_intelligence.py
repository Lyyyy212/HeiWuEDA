from __future__ import annotations

import unittest

from easyeda_gateway.intelligence import analyze_netlist, analyze_schematic_snapshot, build_pcb_report


class IntelligenceTests(unittest.TestCase):
    def test_analyzes_official_netlist_shape(self) -> None:
        netlist = {
            "components": {
                "a": {
                    "props": {"Designator": "J1", "Device_name": "HEADER", "Value": "2P"},
                    "pinInfoMap": {
                        "1": {"pinName": "VBUS", "net": "5V"},
                        "2": {"pinName": "DATA", "net": "USB_D+"},
                    },
                },
                "b": {
                    "props": {"Designator": "J2", "Device_name": "HEADER", "Value": "2P"},
                    "pinInfoMap": {
                        "1": {"pinName": "VBUS", "net": "5V"},
                        "2": {"pinName": "DATA", "net": "USB_D+"},
                        "3": {"pinName": "NC", "net": ""},
                    },
                },
            },
        }
        result = analyze_netlist(netlist)
        self.assertEqual(result["statistics"]["components"], 2)
        self.assertEqual(result["statistics"]["floatingPins"], 1)
        self.assertEqual(result["statistics"]["connectorPairs"], 1)
        self.assertEqual(result["connectorPairs"][0]["mapping"][0]["net"], "5V")
        self.assertEqual(result["connectorPairs"][0]["mapping"][1]["netType"], "interface")

    def test_schematic_snapshot_preserves_netlist_failure_without_connectivity_claims(self) -> None:
        result = analyze_schematic_snapshot(
            {
                "schemaVersion": "easyeda.gateway.schematic-snapshot.v1",
                "project": {"uuid": "project-1"},
                "document": {"uuid": "page-1", "documentType": 1},
                "netlistStatus": "unavailable",
                "netlistError": "validation failed",
                "netlist": None,
                "componentPins": [{"designator": "U1", "pins": [{"number": "1"}, {"number": "2"}]}],
                "noConnectedPins": 1,
            },
        )
        self.assertFalse(result["statistics"]["connectivityAvailable"])
        self.assertEqual(result["statistics"]["components"], 1)
        self.assertEqual(result["statistics"]["activePageComponents"], 1)
        self.assertEqual(result["statistics"]["pins"], 2)
        self.assertEqual(result["netlistError"], "validation failed")
        self.assertIsNone(result["netlistAnalysis"])

    def test_pcb_report_uses_outline_and_converts_mil_to_mm(self) -> None:
        snapshot = _pcb_snapshot()
        report = build_pcb_report(snapshot)
        self.assertEqual(report["statistics"]["components"], 1)
        self.assertEqual(report["statistics"]["tracks"], 4)
        self.assertEqual(report["boardBounds"]["basis"], "board-outline bounding box")
        self.assertEqual(report["boardBounds"]["widthMm"], 25.4)
        self.assertEqual(report["netLengths"][0]["lengthMm"], 50.8)

    def test_pcb_report_falls_back_to_primitive_bounds(self) -> None:
        snapshot = _pcb_snapshot()
        snapshot["lines"] = []
        snapshot["arcs"] = []
        snapshot["polylines"] = []
        report = build_pcb_report(snapshot)
        self.assertEqual(report["boardBounds"]["basis"], "primitive bounding box")


def _pcb_snapshot() -> dict:
    return {
        "schemaVersion": "easyeda.gateway.pcb-snapshot.v1",
        "components": [{"designator": "U1", "x": 100, "y": 200}],
        "pads": [{"x": 150, "y": 250}],
        "vias": [{"x": 200, "y": 300}],
        "lines": [
            {"layer": 11, "startX": 0, "startY": 0, "endX": 1000, "endY": 0},
            {"layer": 1, "startX": 10, "startY": 10, "endX": 20, "endY": 20},
        ],
        "arcs": [{"layer": 11, "startX": 1000, "startY": 0, "endX": 1000, "endY": 500}],
        "polylines": [{"layer": 11, "polygon": [0, 0, 0, 500], "lineWidth": 5}],
        "netLengths": [{"net": "GND", "lengthMil": 1000}, {"net": "USB_D+", "lengthMil": 2000}],
        "netClasses": [{"name": "Default"}],
        "differentialPairs": {"USB": {"positive": "USB_D+", "negative": "USB_D-"}},
        "equalLengthGroups": [],
        "padPairGroups": [],
    }


if __name__ == "__main__":
    unittest.main()
