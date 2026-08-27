from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from easyeda_gateway.bom import compare_boms, load_bom, map_columns, normalize_bom_rows


class BomTests(unittest.TestCase):
    def test_normalizes_aliases_designators_and_quantity(self) -> None:
        result = normalize_bom_rows(
            [
                {"位号": "R10 R2,R2", "封装": "0603", "制造商": "Yageo", "型号": "RC0603"},
            ],
        )
        self.assertEqual(result["rows"][0]["designator"], "R2,R10")
        self.assertEqual(result["rows"][0]["quantity"], "2")
        self.assertEqual(result["rows"][0]["partNumber"], "RC0603")

    def test_duplicate_column_mapping_is_reported_not_silently_overwritten(self) -> None:
        mappings, duplicates = map_columns(["Designator", "RefDes", "Value"])
        self.assertEqual(mappings[1]["targetField"], "ignore")
        self.assertEqual(duplicates[0]["targetField"], "designator")
        self.assertEqual(duplicates[0]["conflictWith"], ["RefDes"])

    def test_compare_reports_changed_added_and_removed(self) -> None:
        old = normalize_bom_rows(
            [
                {"Designator": "R1", "Value": "10k", "Footprint": "0603"},
                {"Designator": "C1", "Value": "1u", "Footprint": "0603"},
            ],
            source="old.csv",
        )
        new = normalize_bom_rows(
            [
                {"Designator": "R1", "Value": "12k", "Footprint": "0603"},
                {"Designator": "U1", "Value": "MCU", "Footprint": "QFN"},
            ],
            source="new.csv",
        )
        diff = compare_boms(old, new)
        self.assertEqual(diff["summary"], {"same": 0, "changed": 1, "added": 1, "removed": 1, "total": 3})
        changed = next(row for row in diff["rows"] if row["type"] == "changed")
        self.assertEqual(changed["cellDiffs"][0]["field"], "value")

    def test_loads_gb18030_csv(self) -> None:
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "bom.csv"
            path.write_bytes("位号,值,封装\nR1,10k,0603\n".encode("gb18030"))
            result = load_bom(path)
        self.assertEqual(result["rowCount"], 1)
        self.assertEqual(result["rows"][0]["value"], "10k")

    def test_loads_official_utf16_tab_separated_csv(self) -> None:
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "official-bom.csv"
            path.write_text("Designator\tQuantity\tValue\nR1 R2\t2\t10k\n", encoding="utf-16")
            result = load_bom(path)
        self.assertEqual(result["rowCount"], 1)
        self.assertEqual(result["rows"][0]["designator"], "R1,R2")
        self.assertEqual(result["rows"][0]["quantity"], "2")


if __name__ == "__main__":
    unittest.main()
