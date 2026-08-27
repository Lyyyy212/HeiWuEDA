from __future__ import annotations

import unittest

from easyeda_gateway.drc import DRC_REPORT_SCHEMA, build_drc_report


class DrcTests(unittest.TestCase):
    def test_drc_summary_keeps_errors_warnings_and_review_gate_distinct(self) -> None:
        report = build_drc_report(
            [
                {"type": "warning", "count": 3},
                {"type": "error", "count": 2},
                {"type": "notice"},
            ],
            {"projectUuid": "p", "documentUuid": "d", "documentType": 1},
        )
        self.assertEqual(report["schemaVersion"], DRC_REPORT_SCHEMA)
        self.assertEqual(report["status"], "BLOCKED_BY_DRC")
        self.assertEqual(report["errorCount"], 2)
        self.assertEqual(report["warningCount"], 3)
        self.assertEqual(report["otherCount"], 1)
        self.assertEqual(report["detailAvailability"], "SUMMARY_ONLY")
        self.assertTrue(report["limitations"])

    def test_warning_only_is_review_required(self) -> None:
        report = build_drc_report([{"type": "warning"}], {"documentType": 1})
        self.assertEqual(report["status"], "REVIEW_REQUIRED")
        self.assertFalse(report["passed"])

    def test_verbose_drc_details_and_fatal_error_are_preserved(self) -> None:
        report = build_drc_report(
            [
                {
                    "type": "fatalError",
                    "rule": "OUT-OUT",
                    "net": "VCC",
                    "primitives": [{"primitiveId": "gge1", "designator": "U1"}],
                }
            ],
            {"documentType": 1},
        )

        self.assertEqual(report["status"], "BLOCKED_BY_DRC")
        self.assertEqual(report["errorCount"], 1)
        self.assertEqual(report["detailAvailability"], "FULL")
        self.assertEqual(report["limitations"], [])
