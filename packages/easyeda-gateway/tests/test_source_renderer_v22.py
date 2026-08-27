import json
import importlib.util
import math
import os
import subprocess
import sys
import tempfile
import unittest
import zipfile
import dataclasses
from unittest import mock
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any


FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "pdf"

from easyeda_gateway import source_renderer_v22 as jlc_pdf


def _read_records(name: str) -> list[list[Any]]:
    return [
        json.loads(line)
        for line in (FIXTURE_DIR / name).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _records_text(records: list[list[Any]]) -> str:
    return "\n".join(
        json.dumps(record, ensure_ascii=False, separators=(",", ":"))
        for record in records
    ) + "\n"


def build_fixture_epro(
    target: Path,
    *,
    used_symbol_record: list[Any] | None = None,
    used_symbol_records: list[list[Any]] | None = None,
    sheet_extra: list[list[Any]] | None = None,
    component_part: str | None = None,
    project_devices: dict[str, Any] | None = None,
    extra_members: dict[str, str] | None = None,
    extra_sheet_uuids: list[str] | None = None,
) -> Path:
    sheet_records = _read_records("sheet.esch")
    if component_part is not None:
        next(record for record in sheet_records if record[0] == "COMPONENT")[2] = component_part
    sheet_records.extend(sheet_extra or [])
    symbol_records = _read_records("symbol.esym")
    if used_symbol_record is not None:
        symbol_records.append(used_symbol_record)
    symbol_records.extend(used_symbol_records or [])

    project = json.loads((FIXTURE_DIR / "project.json").read_text(encoding="utf-8"))
    project["devices"].update(project_devices or {})
    for offset, sheet_uuid in enumerate(extra_sheet_uuids or [], start=2):
        project["schematics"]["schematic-uuid"]["sheets"].append(
            {
                "uuid": sheet_uuid,
                "id": offset,
                "name": f"Fixture Sheet {offset}",
                "display_title": f"Fixture Sheet {offset}",
            }
        )

    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "project.json",
            json.dumps(project, ensure_ascii=False, indent=2),
        )
        archive.writestr(
            "SHEET/schematic-uuid/1.esch", _records_text(sheet_records)
        )
        for offset, _ in enumerate(extra_sheet_uuids or [], start=2):
            archive.writestr(
                f"SHEET/schematic-uuid/{offset}.esch", _records_text(sheet_records)
            )
        archive.writestr("SYMBOL/sym-used.esym", _records_text(symbol_records))
        archive.writestr(
            "SYMBOL/sym-unused.esym",
            (FIXTURE_DIR / "unreferenced.esym").read_text(encoding="utf-8"),
        )
        archive.writestr(
            "BLOB/logo.eblob", (FIXTURE_DIR / "blob.eblob").read_text(encoding="utf-8")
        )
        for member, contents in (extra_members or {}).items():
            archive.writestr(member, contents)
    return target


class V22ArchiveTests(unittest.TestCase):
    def test_lists_all_project_sheets_in_declared_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = build_fixture_epro(
                Path(tmp) / "fixture.epro",
                extra_sheet_uuids=["sheet-uuid-2", "sheet-uuid-3"],
            )
            sheets = jlc_pdf.list_v22_sheets(path)

        self.assertEqual(
            [item.document_uuid for item in sheets],
            ["sheet-uuid", "sheet-uuid-2", "sheet-uuid-3"],
        )
        self.assertEqual(sheets[1].member, "SHEET/schematic-uuid/2.esch")

    def test_loads_active_sheet_and_only_referenced_symbols(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive = jlc_pdf.load_v22_archive(
                build_fixture_epro(Path(tmp) / "fixture.epro"), "sheet-uuid"
            )

        self.assertEqual(archive.sheet_uuid, "sheet-uuid")
        self.assertEqual(archive.referenced_symbol_ids, ("sym-used",))
        self.assertNotIn("TABLE", archive.record_counts)
        self.assertEqual(archive.blobs["logo-hash"].mime_type, "image/svg+xml")

    def test_unknown_record_in_referenced_symbol_blocks(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = build_fixture_epro(
                Path(tmp) / "fixture.epro", used_symbol_record=["TABLE", "bad"]
            )
            with self.assertRaisesRegex(jlc_pdf.UnsupportedSource, "TABLE"):
                jlc_pdf.load_v22_archive(path, "sheet-uuid")

    def test_malformed_attr_length_blocks(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = build_fixture_epro(
                Path(tmp) / "fixture.epro", sheet_extra=[["ATTR", "too-short"]]
            )
            with self.assertRaisesRegex(jlc_pdf.MalformedSource, "ATTR"):
                jlc_pdf.load_v22_archive(path, "sheet-uuid")

    def test_single_default_part_accepts_legacy_component_instance_identifier(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = build_fixture_epro(
                Path(tmp) / "fixture.epro", component_part="legacy-instance-id"
            )

            archive = jlc_pdf.load_v22_archive(path, "sheet-uuid")

        self.assertEqual(archive.referenced_symbol_ids, ("sym-used",))

    def test_unsupported_record_in_unselected_part_does_not_block(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = build_fixture_epro(
                Path(tmp) / "fixture.epro",
                used_symbol_records=[
                    ["PART", "unused", {"BBOX": [0, 0, 10, 10]}],
                    ["TABLE", "ignored-unused-part"],
                ],
            )

            archive = jlc_pdf.load_v22_archive(path, "sheet-uuid")

        self.assertNotIn("TABLE", archive.record_counts)

    def test_malformed_unreferenced_blob_does_not_block(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = build_fixture_epro(
                Path(tmp) / "fixture.epro",
                extra_members={"BLOB/unreferenced.eblob": "not-json\n"},
            )

            archive = jlc_pdf.load_v22_archive(path, "sheet-uuid")

        self.assertEqual(archive.blobs["logo-hash"].mime_type, "image/svg+xml")

    def test_wrong_doctype_unreferenced_blob_does_not_block(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = build_fixture_epro(
                Path(tmp) / "fixture.epro",
                extra_members={
                    "BLOB/unreferenced.eblob": '["DOCTYPE","NOT_BLOB","1.0"]\n'
                },
            )

            archive = jlc_pdf.load_v22_archive(path, "sheet-uuid")

        self.assertIn("logo-hash", archive.blobs)


class SvgRenderTests(unittest.TestCase):
    def load_fixture(self) -> jlc_pdf.V22Archive:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        return jlc_pdf.load_v22_archive(
            build_fixture_epro(Path(temp_dir.name) / "fixture.epro"), "sheet-uuid"
        )

    def test_svg_renders_component_transform_styles_text_and_blob(self):
        result = jlc_pdf.render_svg(self.load_fixture(), margin=10)

        self.assertIn('transform="translate(100 200) rotate(-90)"', result.svg)
        self.assertIn('stroke="#008800"', result.svg)
        self.assertIn("A&amp;B &lt;test&gt;", result.svg)
        self.assertIn('href="data:image/svg+xml;base64,', result.svg)
        self.assertEqual(result.unsupported_records, ())
        self.assertGreater(result.width, 0)
        self.assertGreater(result.height, 0)

    def test_component_attribute_overrides_symbol_expression(self):
        result = jlc_pdf.render_svg(self.load_fixture())

        self.assertIn(">U1<", result.svg)
        self.assertNotIn("={Designator}", result.svg)
        self.assertLess(result.svg.index('data-component="e1"'), result.svg.index(">U1<"))

    def test_pin_name_and_number_attributes_are_rendered(self):
        result = jlc_pdf.render_svg(self.load_fixture())

        self.assertIn(">IN<", result.svg)
        self.assertIn(">1<", result.svg)
        self.assertEqual(result.primitive_count, 8)

    def test_invalid_coordinate_blocks_instead_of_omitting_shape(self):
        archive = self.load_fixture()
        archive = dataclasses.replace(
            archive,
            sheet_records=(
                *archive.sheet_records,
                ["WIRE", "bad", [[0, 0, float("nan"), 5]], "st-line", 0],
            ),
        )

        with self.assertRaisesRegex(jlc_pdf.MalformedSource, "finite"):
            jlc_pdf.render_svg(archive)

    def test_v22_ellipse_record_is_validated_and_rendered(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive = jlc_pdf.load_v22_archive(
                build_fixture_epro(
                    Path(tmp) / "fixture.epro",
                    used_symbol_record=[
                        "ELLIPSE",
                        "ellipse-1",
                        -25,
                        40,
                        1.5,
                        2.5,
                        30,
                        "st-line",
                        0,
                    ],
                ),
                "sheet-uuid",
            )
            result = jlc_pdf.render_svg(archive)

        self.assertIn('<ellipse cx="-25" cy="40" rx="1.5" ry="2.5"', result.svg)
        self.assertIn('rotate(-30 -25 40)', result.svg)
        self.assertIn('stroke="#880000"', result.svg)

    def test_attribute_expression_uses_project_device_attributes(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive = jlc_pdf.load_v22_archive(
                build_fixture_epro(
                    Path(tmp) / "fixture.epro",
                    used_symbol_record=[
                        "ATTR",
                        "s-mpn",
                        "",
                        "Name",
                        "={Manufacturer Part}",
                        0,
                        1,
                        0,
                        20,
                        0,
                        "st-font",
                        0,
                    ],
                    sheet_extra=[
                        [
                            "ATTR",
                            "a-device",
                            "e1",
                            "Device",
                            "device-1",
                            0,
                            0,
                            None,
                            None,
                            0,
                            "st-font",
                            0,
                        ]
                    ],
                    project_devices={
                        "device-1": {
                            "uuid": "device-1",
                            "attributes": {"Manufacturer Part": "OPA1654AIPWR"},
                        }
                    },
                ),
                "sheet-uuid",
            )
            result = jlc_pdf.render_svg(archive)

        self.assertIn(">OPA1654AIPWR<", result.svg)

    def minimal_sheet(self, *records: list[Any]) -> jlc_pdf.V22Archive:
        archive = self.load_fixture()
        return dataclasses.replace(
            archive,
            sheet_records=(
                ["DOCTYPE", "SCH", "1.1"],
                ["HEAD", {"originX": 0, "originY": 0}],
                ["LINESTYLE", "st-line", "#008800", 0, "", 1, 0],
                *records,
            ),
            symbols={},
            referenced_symbol_ids=(),
        )

    def test_ellipse_only_sheet_counts_as_visible_and_is_valid_xml(self):
        result = jlc_pdf.render_svg(
            self.minimal_sheet(["ELLIPSE", "e1", 0, 0, 5, 3, 0, "st-line", 0]),
            margin=0,
        )

        self.assertEqual(result.primitive_count, 1)
        ET.fromstring(result.svg)

    def test_negative_circle_radius_is_rejected(self):
        with self.assertRaisesRegex(jlc_pdf.MalformedSource, "radius"):
            jlc_pdf.render_svg(
                self.minimal_sheet(["CIRCLE", "c1", 0, 0, -1, "st-line", 0])
            )

    def test_major_arc_passes_through_reference_point_and_svg_is_valid_xml(self):
        result = jlc_pdf.render_svg(
            self.minimal_sheet(
                ["ARC", "a1", 1, 0, -1, 0, 0, 1, "st-line", 0]
            ),
            margin=0,
        )

        self.assertIn("A 1 1 0 1 0 0 1", result.svg)
        ET.fromstring(result.svg)

    def test_rotated_rectangle_bounds_include_all_four_corners(self):
        result = jlc_pdf.render_svg(
            self.minimal_sheet(
                ["RECT", "r1", 0, 0, 100, 10, 0, 0, -45, "st-line", 0]
            ),
            margin=0,
        )

        min_x, min_y, width, height = result.view_box
        self.assertLessEqual(min_x, -7)
        self.assertGreaterEqual(min_y + height, 77)

    def test_start_anchored_text_bounds_extend_right_from_anchor(self):
        result = jlc_pdf.render_svg(
            self.minimal_sheet(
                ["FONTSTYLE", "font-start", "#000000", 0, "Arial", 10, 0, 0, 0, 0, 1, 0],
                ["TEXT", "t1", 0, 0, 0, "abcdefghij", "font-start", 0],
            ),
            margin=0,
        )

        min_x, _, width, _ = result.view_box
        self.assertLessEqual(min_x, 0)
        self.assertGreaterEqual(min_x + width, 60)

    def test_rotated_end_anchored_text_bounds_follow_rotation(self):
        result = jlc_pdf.render_svg(
            self.minimal_sheet(
                ["FONTSTYLE", "font-end", "#000000", 0, "Arial", 10, 0, 0, 0, 0, 1, 2],
                ["TEXT", "t1", 0, 0, 90, "abcdefghij", "font-end", 0],
            ),
            margin=0,
        )

        min_x, min_y, width, height = result.view_box
        self.assertLessEqual(min_x, -5)
        self.assertLessEqual(min_y, 0)
        self.assertGreaterEqual(min_y + height, 60)
        self.assertGreaterEqual(min_x + width, 5)

    def test_supported_sheet_primitive_matrix_renders_valid_xml(self):
        records = [
            ["FONTSTYLE", "font", "#000000", 0, "Arial", 10, 0, 0, 0, 0, 1, 1],
            ["BUS", "b1", [[0, 0, 10, 0]], "st-line", 0],
            ["BUSENTRY", "be1", "", "", 10, 0, 45],
            ["POLY", "p1", [0, 0, 10, 0, 10, 10], 1, "st-line", 0],
            ["TEXT", "t1", 20, 20, 30, "text", "font", 0],
            ["CIRCLE", "c1", 30, 30, 4, "st-line", 0],
            ["ELLIPSE", "e1", 40, 40, 5, 3, 15, "st-line", 0],
            ["RECT", "r1", 50, 50, 60, 55, 0, 0, 25, "st-line", 0],
        ]

        result = jlc_pdf.render_svg(self.minimal_sheet(*records), margin=0)

        self.assertEqual(result.primitive_count, 7)
        ET.fromstring(result.svg)

    def test_invalid_dimension_matrix_is_rejected(self):
        invalid_records = [
            (["CIRCLE", "c1", 0, 0, -1, "st-line", 0], "radius"),
            (["ELLIPSE", "e1", 0, 0, -1, 2, 0, "st-line", 0], "radii"),
            (
                [
                    "OBJ",
                    "o1",
                    "",
                    0,
                    0,
                    -1,
                    2,
                    0,
                    0,
                    "data:image/png;base64,AA==",
                    0,
                ],
                "dimensions",
            ),
            (["RECT", "r1", 0, 0, 1, 1, -1, 0, 0, "st-line", 0], "corner radii"),
        ]

        for record, message in invalid_records:
            with self.subTest(record=record[0]):
                with self.assertRaisesRegex(jlc_pdf.MalformedSource, message):
                    jlc_pdf.render_svg(self.minimal_sheet(record))

    def test_non_image_data_url_reports_obj_record_type(self):
        with self.assertRaises(jlc_pdf.UnsupportedSource) as raised:
            jlc_pdf._validate_data_url("data:text/plain;base64,QQ==", "OBJ")

        self.assertEqual(raised.exception.record_type, "OBJ")

    def test_mirrored_component_attribute_bounds_use_composed_transform(self):
        bounds = jlc_pdf._Bounds()
        _, transform = jlc_pdf._component_transform(
            ["COMPONENT", "c1", "", 100, 200, 0, 1, {}, 0]
        )
        styles = {
            "font-end": {
                "size": 10,
                "horizontal": 2,
                "vertical": 1,
                "color": "#000000",
                "font": "Arial",
            }
        }
        record = [
            "ATTR",
            "a1",
            "",
            "Value",
            "abcdefghij",
            0,
            1,
            0,
            0,
            0,
            "font-end",
            0,
        ]

        element = jlc_pdf._attribute_svg(record, {}, styles, bounds, transform)

        self.assertIsNotNone(element)
        self.assertLessEqual(bounds.min_x, 100)
        self.assertGreaterEqual(bounds.max_x, 160)
        self.assertLessEqual(bounds.min_y, 195)
        self.assertGreaterEqual(bounds.max_y, 205)


class PdfConversionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        runtime = (
            Path.home()
            / ".cache"
            / "codex-runtimes"
            / "codex-primary-runtime"
            / "dependencies"
            / "node"
        )
        cls.node_executable = Path(
            os.environ.get("JLC_NODE_EXECUTABLE", runtime / "bin" / "node.exe")
        )
        cls.node_path = Path(
            os.environ.get("JLC_NODE_PATH", runtime / "node_modules")
        )
        if not cls.node_executable.is_file():
            raise unittest.SkipTest(f"Node executable is unavailable: {cls.node_executable}")
        if not (cls.node_path / "playwright").is_dir():
            raise unittest.SkipTest(f"Playwright module is unavailable: {cls.node_path}")
        if importlib.util.find_spec("pypdf") is None:
            raise unittest.SkipTest("pypdf is unavailable")

    def render_fixture(self) -> jlc_pdf.SvgResult:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        archive = jlc_pdf.load_v22_archive(
            build_fixture_epro(Path(temp_dir.name) / "fixture.epro"), "sheet-uuid"
        )
        return jlc_pdf.render_svg(archive)

    def test_chromium_conversion_is_one_page_and_keeps_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            svg = tmp_path / "input.svg"
            svg.write_text(self.render_fixture().svg, encoding="utf-8")
            pdf = tmp_path / "output.pdf"

            info = jlc_pdf.convert_svg_to_pdf(
                svg,
                pdf,
                node_executable=self.node_executable,
                node_path=self.node_path,
                timeout=30,
            )

            self.assertEqual(info.page_count, 1)
            self.assertTrue(pdf.read_bytes().startswith(b"%PDF-"))
            self.assertIn("U1", info.extracted_text)
            self.assertGreater(info.content_stream_bytes, 100)

    def test_chromium_png_raster_is_valid_and_matches_svg_extent(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            rendered = self.render_fixture()
            svg = tmp_path / "input.svg"
            svg.write_text(rendered.svg, encoding="utf-8")
            png = tmp_path / "output.png"

            info = jlc_pdf.convert_svg_to_png(
                svg,
                png,
                node_executable=self.node_executable,
                node_path=self.node_path,
                timeout=30,
            )

            self.assertTrue(png.read_bytes().startswith(b"\x89PNG\r\n\x1a\n"))
            self.assertEqual(math.ceil(rendered.width), info.width)
            self.assertEqual(math.ceil(rendered.height), info.height)
            self.assertGreater(info.bytes, 100)

    def test_png_conversion_refuses_existing_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            png = Path(tmp) / "output.png"
            png.write_bytes(b"keep")

            with self.assertRaisesRegex(jlc_pdf.OutputCollision, "already exists"):
                jlc_pdf.convert_svg_to_png(
                    Path(tmp) / "input.svg",
                    png,
                    node_executable=self.node_executable,
                    node_path=self.node_path,
                    timeout=30,
                )

            self.assertEqual(png.read_bytes(), b"keep")

    def test_conversion_refuses_existing_pdf(self):
        with tempfile.TemporaryDirectory() as tmp:
            pdf = Path(tmp) / "output.pdf"
            pdf.write_bytes(b"keep")

            with self.assertRaisesRegex(jlc_pdf.OutputCollision, "already exists"):
                jlc_pdf.convert_svg_to_pdf(
                    Path(tmp) / "input.svg",
                    pdf,
                    node_executable=self.node_executable,
                    node_path=self.node_path,
                    timeout=30,
                )

            self.assertEqual(pdf.read_bytes(), b"keep")

    def test_conversion_does_not_overwrite_destination_created_during_race(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            svg = tmp_path / "input.svg"
            svg.write_text(self.render_fixture().svg, encoding="utf-8")
            pdf = tmp_path / "output.pdf"
            real_link = os.link

            def race_link(source, destination):
                Path(destination).write_bytes(b"racer")
                return real_link(source, destination)

            with mock.patch.object(jlc_pdf.os, "link", side_effect=race_link):
                with self.assertRaisesRegex(jlc_pdf.OutputCollision, "appeared|exists"):
                    jlc_pdf.convert_svg_to_pdf(
                        svg,
                        pdf,
                        node_executable=self.node_executable,
                        node_path=self.node_path,
                        timeout=30,
                    )

            self.assertEqual(pdf.read_bytes(), b"racer")

    def test_spawn_oserror_is_wrapped_and_temporary_pdf_is_removed(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            svg = tmp_path / "input.svg"
            svg.write_text(self.render_fixture().svg, encoding="utf-8")
            pdf = tmp_path / "output.pdf"

            with mock.patch.object(
                jlc_pdf.subprocess, "Popen", side_effect=OSError("spawn failed")
            ):
                with self.assertRaisesRegex(jlc_pdf.PdfConversionError, "spawn failed"):
                    jlc_pdf.convert_svg_to_pdf(
                        svg,
                        pdf,
                        node_executable=self.node_executable,
                        node_path=self.node_path,
                        timeout=30,
                    )

            self.assertFalse(pdf.exists())
            self.assertEqual(list(tmp_path.glob(".*.tmp-*")), [])

    def test_timeout_terminates_the_converter_process_tree(self):
        process = mock.Mock(pid=321)
        process.communicate.side_effect = subprocess.TimeoutExpired("node", 1)

        with mock.patch.object(
            jlc_pdf.subprocess, "Popen", return_value=process
        ), mock.patch.object(jlc_pdf, "_terminate_process_tree") as terminate:
            with self.assertRaisesRegex(jlc_pdf.PdfConversionError, "exceeded"):
                jlc_pdf._run_pdf_process(
                    ["node", "helper"], Path.cwd(), os.environ.copy(), 1
                )

        terminate.assert_called_once_with(process)

    def test_communicate_oserror_terminates_tree_and_is_wrapped(self):
        process = mock.Mock(pid=322)
        process.communicate.side_effect = OSError("pipe failed")

        with mock.patch.object(
            jlc_pdf.subprocess, "Popen", return_value=process
        ), mock.patch.object(jlc_pdf, "_terminate_process_tree") as terminate:
            with self.assertRaisesRegex(jlc_pdf.PdfConversionError, "pipe failed"):
                jlc_pdf._run_pdf_process(
                    ["node", "helper"], Path.cwd(), os.environ.copy(), 1
                )

        terminate.assert_called_once_with(process)

    def test_keyboard_interrupt_terminates_tree_before_propagating(self):
        process = mock.Mock(pid=323)
        process.communicate.side_effect = KeyboardInterrupt()

        with mock.patch.object(
            jlc_pdf.subprocess, "Popen", return_value=process
        ), mock.patch.object(jlc_pdf, "_terminate_process_tree") as terminate:
            with self.assertRaises(KeyboardInterrupt):
                jlc_pdf._run_pdf_process(
                    ["node", "helper"], Path.cwd(), os.environ.copy(), 1
                )

        terminate.assert_called_once_with(process)

    def test_windows_tree_termination_uses_taskkill_recursive_force(self):
        process = mock.Mock(pid=324)

        with mock.patch.object(jlc_pdf.os, "name", "nt"), mock.patch.object(
            jlc_pdf.subprocess, "run"
        ) as run:
            jlc_pdf._terminate_process_tree(process)

        run.assert_called_once_with(
            ["taskkill", "/PID", "324", "/T", "/F"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        process.wait.assert_called_once_with(timeout=5)


if __name__ == "__main__":
    unittest.main()
