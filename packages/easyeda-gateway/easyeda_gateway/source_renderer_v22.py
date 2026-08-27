#!/usr/bin/env python3
"""Strict EasyEDA Pro V2.2 source parser and local vector rendering helpers."""

from __future__ import annotations

import base64
import binascii
import html
import json
import math
import os
import re
import signal
import subprocess
import uuid
import zipfile
import xml.etree.ElementTree as ET
from collections import Counter
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Iterable


class PdfSourceError(Exception):
    """Base class for source-rendered PDF failures."""


class UnsupportedSource(PdfSourceError):
    """Raised when the active render closure contains an unsupported record."""

    def __init__(
        self,
        message: str,
        *,
        record_type: str | None = None,
        context: str | None = None,
    ):
        super().__init__(message)
        self.record_type = record_type
        self.context = context


class MalformedSource(PdfSourceError):
    """Raised when an EasyEDA source record is invalid or incomplete."""


class OutputCollision(PdfSourceError):
    """Raised when a requested output already exists."""


class PdfConversionError(PdfSourceError):
    """Raised when local SVG-to-PDF conversion or validation fails."""


class PngConversionError(PdfSourceError):
    """Raised when local SVG-to-PNG conversion or validation fails."""


@dataclass(frozen=True)
class BlobData:
    mime_type: str
    data_url: str


@dataclass(frozen=True)
class V22Archive:
    project: dict[str, Any]
    sheet_uuid: str
    schematic_uuid: str
    sheet_id: int
    sheet_name: str
    sheet_records: tuple[list[Any], ...]
    symbols: dict[str, tuple[list[Any], ...]]
    blobs: dict[str, BlobData]
    referenced_symbol_ids: tuple[str, ...]
    record_counts: dict[str, int]


@dataclass(frozen=True)
class V22SheetInfo:
    """One renderable schematic page declared by an EPRO project archive."""

    document_uuid: str
    schematic_uuid: str
    sheet_id: int
    page_name: str
    display_title: str
    schematic_name: str
    member: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "documentUuid": self.document_uuid,
            "schematicUuid": self.schematic_uuid,
            "sheetId": self.sheet_id,
            "pageName": self.page_name,
            "displayTitle": self.display_title,
            "schematicName": self.schematic_name,
            "member": self.member,
        }


SUPPORTED_ARITIES: dict[str, set[int]] = {
    "DOCTYPE": {3},
    "HEAD": {2},
    "FONTSTYLE": {12},
    "LINESTYLE": {6, 7},
    "PART": {3},
    "GROUP": {5},
    "COMPONENT": {9},
    "ATTR": {12},
    "PIN": {11},
    "WIRE": {5},
    "BUS": {5},
    "BUSENTRY": {7},
    "TEXT": {7, 8},
    "RECT": {11},
    "POLY": {6},
    "CIRCLE": {7},
    "ELLIPSE": {9},
    "ARC": {10},
    "OBJ": {11},
}

_DATA_URL_RE = re.compile(
    r"^data:(?P<mime>[A-Za-z0-9.+-]+/[A-Za-z0-9.+-]+);base64,(?P<data>[A-Za-z0-9+/=\r\n]+)$"
)


def _safe_members(archive: zipfile.ZipFile) -> dict[str, zipfile.ZipInfo]:
    members: dict[str, zipfile.ZipInfo] = {}
    for info in archive.infolist():
        name = info.filename.replace("\\", "/")
        path = PurePosixPath(name)
        if path.is_absolute() or ".." in path.parts:
            raise MalformedSource(f"Unsafe archive member path: {info.filename}")
        if name in members:
            raise MalformedSource(f"Duplicate archive member: {name}")
        members[name] = info
    return members


def _read_json_object(archive: zipfile.ZipFile, member: str) -> dict[str, Any]:
    try:
        value = json.loads(archive.read(member).decode("utf-8-sig"))
    except (KeyError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MalformedSource(f"Invalid JSON object in {member}: {exc}") from exc
    if not isinstance(value, dict):
        raise MalformedSource(f"JSON root must be an object in {member}")
    return value


def _read_json_lines(archive: zipfile.ZipFile, member: str) -> list[list[Any]]:
    try:
        text = archive.read(member).decode("utf-8-sig")
    except (KeyError, UnicodeDecodeError) as exc:
        raise MalformedSource(f"Cannot read {member}: {exc}") from exc
    records: list[list[Any]] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise MalformedSource(
                f"Invalid JSON record in {member}:{line_number}: {exc}"
            ) from exc
        if not isinstance(value, list) or not value or not isinstance(value[0], str):
            raise MalformedSource(
                f"Record in {member}:{line_number} must be a nonempty JSON array"
            )
        records.append(value)
    if not records:
        raise MalformedSource(f"No records found in {member}")
    return records


def _validate_data_url(value: str, context: str) -> BlobData:
    match = _DATA_URL_RE.fullmatch(value)
    if not match:
        raise MalformedSource(f"Invalid base64 data URL in {context}")
    try:
        base64.b64decode(match.group("data"), validate=True)
    except (binascii.Error, ValueError) as exc:
        raise MalformedSource(f"Invalid base64 payload in {context}") from exc
    mime_type = match.group("mime").lower()
    if not mime_type.startswith("image/"):
        raise UnsupportedSource(
            f"OBJ payload is not an image in {context}: {mime_type}",
            record_type="OBJ",
            context=context,
        )
    return BlobData(mime_type=mime_type, data_url=value)


def _validate_record(record: list[Any], context: str) -> None:
    record_type = record[0]
    arities = SUPPORTED_ARITIES.get(record_type)
    if arities is None:
        raise UnsupportedSource(
            f"Unsupported V2.2 record {record_type} in {context}",
            record_type=record_type,
            context=context,
        )
    if len(record) not in arities:
        expected = "/".join(str(value) for value in sorted(arities))
        raise MalformedSource(
            f"{record_type} in {context} has {len(record)} fields; expected {expected}"
        )


def _finite_numbers(values: Iterable[Any], context: str) -> None:
    for value in values:
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise MalformedSource(f"Coordinate in {context} is not numeric: {value!r}")
        if not math.isfinite(float(value)):
            raise MalformedSource(f"Coordinate in {context} must be finite")


def _validate_coordinates(record: list[Any], context: str) -> None:
    record_type = record[0]
    if record_type in {"COMPONENT"}:
        _finite_numbers(record[3:6], context)
    elif record_type == "ATTR" and record[7] is not None and record[8] is not None:
        _finite_numbers(record[7:10], context)
    elif record_type in {"WIRE", "BUS"}:
        if not isinstance(record[2], list):
            raise MalformedSource(f"{record_type} coordinate groups must be an array in {context}")
        for group in record[2]:
            if not isinstance(group, list) or len(group) < 4 or len(group) % 2:
                raise MalformedSource(f"{record_type} coordinate group is malformed in {context}")
            _finite_numbers(group, context)
    elif record_type == "BUSENTRY":
        _finite_numbers(record[4:7], context)
    elif record_type == "TEXT":
        _finite_numbers(record[2:5], context)
    elif record_type == "RECT":
        _finite_numbers(record[2:9], context)
        if record[6] < 0 or record[7] < 0:
            raise MalformedSource(f"RECT corner radii must be nonnegative in {context}")
    elif record_type == "POLY":
        if not isinstance(record[2], list) or len(record[2]) < 4 or len(record[2]) % 2:
            raise MalformedSource(f"POLY coordinates are malformed in {context}")
        _finite_numbers(record[2], context)
    elif record_type == "CIRCLE":
        _finite_numbers(record[2:5], context)
        if record[4] < 0:
            raise MalformedSource(f"CIRCLE radius must be nonnegative in {context}")
    elif record_type == "ELLIPSE":
        _finite_numbers(record[2:7], context)
        if record[4] < 0 or record[5] < 0:
            raise MalformedSource(f"ELLIPSE radii must be nonnegative in {context}")
    elif record_type == "ARC":
        _finite_numbers(record[2:8], context)
    elif record_type == "PIN":
        _finite_numbers(record[4:8], context)
    elif record_type == "OBJ":
        _finite_numbers(record[3:9], context)
        if record[5] < 0 or record[6] < 0:
            raise MalformedSource(f"OBJ dimensions must be nonnegative in {context}")


def _require_doctype(records: list[list[Any]], expected: str, context: str) -> None:
    first = records[0]
    if len(first) != 3 or first[0] != "DOCTYPE" or first[1] != expected:
        raise MalformedSource(f"{context} does not begin with DOCTYPE/{expected}")


def _load_blobs(
    archive: zipfile.ZipFile,
    members: dict[str, zipfile.ZipInfo],
    required_hashes: set[str],
) -> dict[str, BlobData]:
    blobs: dict[str, BlobData] = {}
    if not required_hashes:
        return blobs
    for name in sorted(members):
        if not name.startswith("BLOB/") or not name.endswith(".eblob"):
            continue
        try:
            records = _read_json_lines(archive, name)
        except MalformedSource:
            stem = PurePosixPath(name).stem
            if stem in required_hashes:
                raise
            continue
        candidate_hashes = {
            str(record[1])
            for record in records
            if len(record) >= 2
            and record[0] == "BLOB"
            and isinstance(record[1], str)
            and record[1] in required_hashes
        }
        if not candidate_hashes and PurePosixPath(name).stem not in required_hashes:
            continue
        _require_doctype(records, "BLOB", name)
        for record in records[1:]:
            if (
                len(record) < 2
                or record[0] != "BLOB"
                or not isinstance(record[1], str)
                or record[1] not in required_hashes
            ):
                continue
            if len(record) != 4:
                raise MalformedSource(f"Malformed BLOB record in {name}")
            if record[1] in blobs:
                raise MalformedSource(f"Duplicate BLOB hash: {record[1]}")
            if not isinstance(record[3], str):
                raise MalformedSource(f"BLOB data URL must be a string in {name}")
            blobs[record[1]] = _validate_data_url(record[3], name)
    missing = sorted(required_hashes - set(blobs))
    if missing:
        raise MalformedSource("Missing referenced BLOB data: " + ", ".join(missing))
    return blobs


def _selected_symbol_closure(
    records: list[list[Any]], requested_parts: set[str], context: str
) -> tuple[list[list[Any]], set[str]]:
    parts = [record for record in records if record[0] == "PART"]
    for record in parts:
        _validate_record(record, context)
    available = {str(record[1]) for record in parts}
    if not available:
        raise MalformedSource(f"Referenced symbol has no PART records in {context}")
    selected: set[str] = set()
    for requested in requested_parts:
        if requested in available:
            selected.add(requested)
        elif available == {""}:
            selected.add("")
        else:
            raise MalformedSource(
                f"Referenced symbol {context} is missing PART {requested!r}"
            )

    closure: list[list[Any]] = []
    seen_part = False
    active = False
    for record in records:
        if record[0] == "PART":
            seen_part = True
            active = str(record[1]) in selected
            if active:
                closure.append(record)
            continue
        if not seen_part or active:
            closure.append(record)
    for record in closure:
        _validate_record(record, context)
        _validate_coordinates(record, context)
    return closure, selected


def list_v22_sheets(path: Path) -> tuple[V22SheetInfo, ...]:
    """List every schematic page in stable project order without rendering it."""

    try:
        archive = zipfile.ZipFile(path)
    except (OSError, zipfile.BadZipFile) as exc:
        raise MalformedSource(f"Invalid .epro ZIP archive {path}: {exc}") from exc

    with archive:
        members = _safe_members(archive)
        if "project.json" not in members:
            raise MalformedSource(".epro archive is missing project.json")
        project = _read_json_object(archive, "project.json")
        schematics = project.get("schematics")
        if not isinstance(schematics, dict):
            raise MalformedSource("project.json schematics must be an object")

        result: list[V22SheetInfo] = []
        seen: set[str] = set()
        for schematic_uuid, schematic in schematics.items():
            if not isinstance(schematic, dict):
                raise MalformedSource(f"Schematic {schematic_uuid} must be an object")
            sheets = schematic.get("sheets")
            if not isinstance(sheets, list):
                raise MalformedSource(f"Schematic {schematic_uuid} sheets must be an array")
            schematic_name = schematic.get("name")
            if not isinstance(schematic_name, str):
                schematic_name = str(schematic_uuid)
            for sheet in sheets:
                if not isinstance(sheet, dict):
                    raise MalformedSource(f"Schematic {schematic_uuid} contains an invalid sheet")
                document_uuid = sheet.get("uuid")
                sheet_id = sheet.get("id")
                if not isinstance(document_uuid, str) or not document_uuid.strip():
                    raise MalformedSource(f"Schematic {schematic_uuid} contains a sheet without UUID")
                if document_uuid in seen:
                    raise MalformedSource(f"Duplicate schematic page UUID in project.json: {document_uuid}")
                if not isinstance(sheet_id, int) or isinstance(sheet_id, bool):
                    raise MalformedSource(f"Schematic page {document_uuid} id must be an integer")
                member = f"SHEET/{schematic_uuid}/{sheet_id}.esch"
                if member not in members:
                    raise MalformedSource(f"Missing schematic page source: {member}")
                page_name = sheet.get("name")
                display_title = sheet.get("display_title")
                result.append(
                    V22SheetInfo(
                        document_uuid=document_uuid,
                        schematic_uuid=str(schematic_uuid),
                        sheet_id=sheet_id,
                        page_name=page_name if isinstance(page_name, str) else document_uuid,
                        display_title=(
                            display_title
                            if isinstance(display_title, str)
                            else (page_name if isinstance(page_name, str) else document_uuid)
                        ),
                        schematic_name=schematic_name,
                        member=member,
                    )
                )
                seen.add(document_uuid)
        if not result:
            raise MalformedSource("EPRO project contains no schematic pages")
        return tuple(result)


def load_v22_archive(path: Path, document_uuid: str) -> V22Archive:
    """Load the active V2.2 sheet and exactly the symbols it references."""
    try:
        archive = zipfile.ZipFile(path)
    except (OSError, zipfile.BadZipFile) as exc:
        raise MalformedSource(f"Invalid .epro ZIP archive {path}: {exc}") from exc

    with archive:
        members = _safe_members(archive)
        if "project.json" not in members:
            raise MalformedSource(".epro archive is missing project.json")
        project = _read_json_object(archive, "project.json")
        matches: list[tuple[str, dict[str, Any]]] = []
        schematics = project.get("schematics")
        if not isinstance(schematics, dict):
            raise MalformedSource("project.json schematics must be an object")
        for schematic_uuid, schematic in schematics.items():
            if not isinstance(schematic, dict) or not isinstance(schematic.get("sheets"), list):
                continue
            for sheet in schematic["sheets"]:
                if isinstance(sheet, dict) and sheet.get("uuid") == document_uuid:
                    matches.append((str(schematic_uuid), sheet))
        if len(matches) != 1:
            raise MalformedSource(
                f"Expected one active sheet {document_uuid}, found {len(matches)}"
            )
        schematic_uuid, sheet = matches[0]
        sheet_id = sheet.get("id")
        if not isinstance(sheet_id, int):
            raise MalformedSource("Active sheet id must be an integer")
        sheet_member = f"SHEET/{schematic_uuid}/{sheet_id}.esch"
        if sheet_member not in members:
            raise MalformedSource(f"Missing active sheet source: {sheet_member}")
        sheet_records = _read_json_lines(archive, sheet_member)
        _require_doctype(sheet_records, "SCH", sheet_member)

        component_parts: dict[str, str] = {}
        for record in sheet_records:
            _validate_record(record, sheet_member)
            _validate_coordinates(record, sheet_member)
            if record[0] == "COMPONENT":
                component_parts[str(record[1])] = str(record[2])

        component_symbols: dict[str, str] = {}
        for record in sheet_records:
            if (
                record[0] == "ATTR"
                and record[2] in component_parts
                and record[3] == "Symbol"
                and isinstance(record[4], str)
                and record[4]
            ):
                component_symbols[str(record[2])] = record[4]
        missing_component_symbols = sorted(set(component_parts) - set(component_symbols))
        if missing_component_symbols:
            raise MalformedSource(
                "COMPONENT records missing Symbol ATTR: "
                + ", ".join(missing_component_symbols)
            )

        requested_parts_by_symbol: dict[str, set[str]] = {}
        for component_id, symbol_id in component_symbols.items():
            requested_parts_by_symbol.setdefault(symbol_id, set()).add(
                component_parts[component_id]
            )

        referenced_symbol_ids = tuple(sorted(requested_parts_by_symbol))
        symbols: dict[str, tuple[list[Any], ...]] = {}
        symbol_closures: dict[str, tuple[list[Any], ...]] = {}
        for symbol_id in referenced_symbol_ids:
            member = f"SYMBOL/{symbol_id}.esym"
            if member not in members:
                raise MalformedSource(f"Missing referenced symbol source: {member}")
            records = _read_json_lines(archive, member)
            _require_doctype(records, "SYMBOL", member)
            closure, _ = _selected_symbol_closure(
                records, requested_parts_by_symbol[symbol_id], member
            )
            symbols[symbol_id] = tuple(records)
            symbol_closures[symbol_id] = tuple(closure)

        source_contexts: list[tuple[str, Iterable[list[Any]]]] = [
            (sheet_member, sheet_records),
            *[(symbol_id, records) for symbol_id, records in symbol_closures.items()],
        ]
        required_blobs: set[str] = set()
        for context, records in source_contexts:
            for record in records:
                if record[0] != "OBJ":
                    continue
                source = record[9]
                if not isinstance(source, str):
                    raise MalformedSource(f"OBJ source must be a string in {context}")
                if source.startswith("blob:"):
                    required_blobs.add(source[5:])
                elif source.startswith("data:"):
                    _validate_data_url(source, f"OBJ in {context}")
                else:
                    raise UnsupportedSource(
                        f"Unsupported OBJ source in {context}: {source!r}",
                        record_type="OBJ",
                        context=context,
                    )
        blobs = _load_blobs(archive, members, required_blobs)

        counts = Counter(record[0] for record in sheet_records)
        for records in symbol_closures.values():
            counts.update(record[0] for record in records)

        return V22Archive(
            project=project,
            sheet_uuid=document_uuid,
            schematic_uuid=schematic_uuid,
            sheet_id=sheet_id,
            sheet_name=str(sheet.get("name") or sheet.get("display_title") or ""),
            sheet_records=tuple(sheet_records),
            symbols=symbols,
            blobs=blobs,
            referenced_symbol_ids=referenced_symbol_ids,
            record_counts=dict(sorted(counts.items())),
        )


@dataclass(frozen=True)
class SvgResult:
    svg: str
    width: float
    height: float
    view_box: tuple[float, float, float, float]
    primitive_count: int
    unsupported_records: tuple[str, ...]


@dataclass(frozen=True)
class PdfInfo:
    page_count: int
    extracted_text: str
    content_stream_bytes: int


@dataclass(frozen=True)
class PngInfo:
    width: int
    height: int
    bytes: int


@dataclass
class _Bounds:
    min_x: float = math.inf
    min_y: float = math.inf
    max_x: float = -math.inf
    max_y: float = -math.inf

    def add(self, x: float, y: float) -> None:
        if not math.isfinite(x) or not math.isfinite(y):
            raise MalformedSource("SVG bounding coordinate must be finite")
        self.min_x = min(self.min_x, x)
        self.min_y = min(self.min_y, y)
        self.max_x = max(self.max_x, x)
        self.max_y = max(self.max_y, y)

    def add_rect(self, x1: float, y1: float, x2: float, y2: float) -> None:
        self.add(x1, y1)
        self.add(x2, y2)

    @property
    def empty(self) -> bool:
        return self.min_x == math.inf


def _number(value: Any) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise MalformedSource(f"Expected numeric coordinate, got {value!r}")
    result = float(value)
    if not math.isfinite(result):
        raise MalformedSource("Coordinate must be finite")
    return result


def _fmt(value: Any) -> str:
    number = _number(value)
    if number == 0:
        return "0"
    return f"{number:.6f}".rstrip("0").rstrip(".")


def _escape(value: Any, *, quote: bool = False) -> str:
    return html.escape("" if value is None else str(value), quote=quote)


def _line_styles(records: Iterable[list[Any]]) -> dict[str, dict[str, Any]]:
    styles: dict[str, dict[str, Any]] = {}
    for record in records:
        if record[0] != "LINESTYLE":
            continue
        styles[str(record[1])] = {
            "stroke": record[2] or "#000000",
            "dash": record[3] if isinstance(record[3], int) else 0,
            "fill": record[4] or "none",
            "width": record[5] if isinstance(record[5], (int, float)) else 1,
        }
    return styles


def _font_styles(records: Iterable[list[Any]]) -> dict[str, dict[str, Any]]:
    styles: dict[str, dict[str, Any]] = {}
    for record in records:
        if record[0] != "FONTSTYLE":
            continue
        styles[str(record[1])] = {
            "color": record[2] or "#000000",
            "font": record[4] or "Arial, sans-serif",
            "size": record[5] if isinstance(record[5], (int, float)) else 7,
            "italic": bool(record[6]),
            "bold": bool(record[7]),
            "underline": bool(record[8]),
            "strike": bool(record[9]),
            "vertical": record[10] if isinstance(record[10], int) else 1,
            "horizontal": record[11] if isinstance(record[11], int) else 0,
        }
    return styles


def _line_attributes(style_id: Any, styles: dict[str, dict[str, Any]]) -> str:
    style = styles.get(str(style_id), {})
    stroke = _escape(style.get("stroke", "#000000"), quote=True)
    fill = _escape(style.get("fill", "none"), quote=True)
    width = _fmt(style.get("width", 1))
    dash = {1: "6 4", 2: "1 3", 3: "6 3 1 3"}.get(style.get("dash"))
    attributes = f'stroke="{stroke}" fill="{fill}" stroke-width="{width}"'
    if dash:
        attributes += f' stroke-dasharray="{dash}"'
    return attributes


def _text_attributes(style_id: Any, styles: dict[str, dict[str, Any]]) -> tuple[str, float]:
    style = styles.get(str(style_id), {})
    size = _number(style.get("size", 7))
    horizontal = style.get("horizontal", 0)
    vertical = style.get("vertical", 1)
    anchor = {0: "start", 1: "middle", 2: "end"}.get(horizontal, "start")
    baseline = {0: "hanging", 1: "central", 2: "text-after-edge"}.get(
        vertical, "central"
    )
    decoration: list[str] = []
    if style.get("underline"):
        decoration.append("underline")
    if style.get("strike"):
        decoration.append("line-through")
    attributes = [
        f'fill="{_escape(style.get("color", "#000000"), quote=True)}"',
        f'font-family="{_escape(style.get("font", "Arial, sans-serif"), quote=True)}"',
        f'font-size="{_fmt(size)}"',
        f'text-anchor="{anchor}"',
        f'dominant-baseline="{baseline}"',
    ]
    if style.get("italic"):
        attributes.append('font-style="italic"')
    if style.get("bold"):
        attributes.append('font-weight="bold"')
    if decoration:
        attributes.append(f'text-decoration="{" ".join(decoration)}"')
    return " ".join(attributes), size


def _text_local_bounds(
    style_id: Any, styles: dict[str, dict[str, Any]], text: str
) -> tuple[float, float, float, float]:
    """Estimate text bounds relative to its SVG anchor and dominant baseline."""
    style = styles.get(str(style_id), {})
    size = _number(style.get("size", 7))
    width = max(size * 0.6 * len(text), size)
    horizontal = style.get("horizontal", 0)
    if horizontal == 1:
        left, right = -width / 2, width / 2
    elif horizontal == 2:
        left, right = -width, 0.0
    else:
        left, right = 0.0, width

    vertical = style.get("vertical", 1)
    if vertical == 0:
        top, bottom = 0.0, size
    elif vertical == 2:
        top, bottom = -size, 0.0
    else:
        top, bottom = -size / 2, size / 2
    return left, top, right, bottom


def _component_transform(record: list[Any]) -> tuple[str, Any]:
    x, y, angle = (_number(record[3]), _number(record[4]), _number(record[5]))
    mirror = bool(record[6])
    parts = [f"translate({_fmt(x)} {_fmt(y)})"]
    if mirror:
        parts.append("scale(-1 1)")
    if angle:
        parts.append(f"rotate({_fmt(-angle)})")

    def transform(point_x: float, point_y: float) -> tuple[float, float]:
        theta = math.radians(-angle)
        rotated_x = point_x * math.cos(theta) - point_y * math.sin(theta)
        rotated_y = point_x * math.sin(theta) + point_y * math.cos(theta)
        if mirror:
            rotated_x = -rotated_x
        return rotated_x + x, rotated_y + y

    return " ".join(parts), transform


def _attribute_text(record: list[Any], values: dict[str, Any]) -> str:
    key = str(record[3])
    value = "" if record[4] is None else str(record[4])
    expression = re.fullmatch(r"=\{([^{}]+)\}", value)
    if expression:
        expression_key = expression.group(1)
        if expression_key not in values:
            raise MalformedSource(f"ATTR expression references missing key {expression_key!r}")
        value = "" if values[expression_key] is None else str(values[expression_key])
    show_key = bool(record[5])
    show_value = bool(record[6])
    if show_key and show_value:
        return f"{key}={value}"
    if show_key:
        return key
    return value if show_value else ""


def _attribute_svg(
    record: list[Any],
    values: dict[str, Any],
    font_styles: dict[str, dict[str, Any]],
    bounds: _Bounds,
    transform: Any | None = None,
) -> str | None:
    if record[7] is None or record[8] is None:
        return None
    text = _attribute_text(record, values)
    if not text:
        return None
    x, y, angle = _number(record[7]), _number(record[8]), _number(record[9])
    attributes, _ = _text_attributes(record[10], font_styles)
    left, top, right, bottom = _text_local_bounds(record[10], font_styles, text)
    theta = math.radians(-angle)
    for point_x, point_y in (
        (x + left, y + top),
        (x + right, y + top),
        (x + right, y + bottom),
        (x + left, y + bottom),
    ):
        delta_x, delta_y = point_x - x, point_y - y
        output_x = x + delta_x * math.cos(theta) - delta_y * math.sin(theta)
        output_y = y + delta_x * math.sin(theta) + delta_y * math.cos(theta)
        if transform:
            output_x, output_y = transform(output_x, output_y)
        bounds.add(output_x, output_y)
    rotate = f' transform="rotate({_fmt(-angle)} {_fmt(x)} {_fmt(y)})"' if angle else ""
    return (
        f'<text x="{_fmt(x)}" y="{_fmt(y)}" {attributes}{rotate}>'
        f"{_escape(text)}</text>"
    )


def _select_part_records(records: tuple[list[Any], ...], requested_part: str) -> list[list[Any]]:
    parts = [record for record in records if record[0] == "PART"]
    selected = requested_part
    if selected not in {str(record[1]) for record in parts} and len(parts) == 1 and parts[0][1] == "":
        selected = ""
    active = False
    output: list[list[Any]] = []
    for record in records:
        if record[0] == "PART":
            active = str(record[1]) == selected
            continue
        if active:
            output.append(record)
    return output


def _svg_element_count(value: str) -> int:
    return len(
        re.findall(
            r"<(?!/)(?:polyline|polygon|rect|circle|ellipse|path|line|text|image)\b",
            value,
        )
    )


def _arc_path(record: list[Any]) -> tuple[str, tuple[float, float, float, float]]:
    x1, y1, xr, yr, x2, y2 = map(_number, record[2:8])
    denominator = 2 * (x1 * (yr - y2) + xr * (y2 - y1) + x2 * (y1 - yr))
    if abs(denominator) < 1e-12:
        raise MalformedSource("ARC start/reference/end points are collinear")
    ux = (
        (x1 * x1 + y1 * y1) * (yr - y2)
        + (xr * xr + yr * yr) * (y2 - y1)
        + (x2 * x2 + y2 * y2) * (y1 - yr)
    ) / denominator
    uy = (
        (x1 * x1 + y1 * y1) * (x2 - xr)
        + (xr * xr + yr * yr) * (x1 - x2)
        + (x2 * x2 + y2 * y2) * (xr - x1)
    ) / denominator
    radius = math.hypot(x1 - ux, y1 - uy)
    start_angle = math.atan2(y1 - uy, x1 - ux)
    reference_angle = math.atan2(yr - uy, xr - ux)
    end_angle = math.atan2(y2 - uy, x2 - ux)
    positive_delta = (end_angle - start_angle) % (2 * math.pi)
    reference_delta = (reference_angle - start_angle) % (2 * math.pi)
    if reference_delta <= positive_delta + 1e-12:
        sweep = 1
        selected_delta = positive_delta
    else:
        sweep = 0
        selected_delta = (start_angle - end_angle) % (2 * math.pi)
    large_arc = 1 if selected_delta > math.pi + 1e-12 else 0
    path = (
        f"M {_fmt(x1)} {_fmt(y1)} A {_fmt(radius)} {_fmt(radius)} "
        f"0 {large_arc} {sweep} {_fmt(x2)} {_fmt(y2)}"
    )
    return path, (ux - radius, uy - radius, ux + radius, uy + radius)


def _primitive_svg(
    record: list[Any],
    line_styles: dict[str, dict[str, Any]],
    font_styles: dict[str, dict[str, Any]],
    blobs: dict[str, BlobData],
    bounds: _Bounds,
    transform: Any | None = None,
) -> str | None:
    record_type = record[0]

    def add_point(x: Any, y: Any) -> None:
        point_x, point_y = _number(x), _number(y)
        if transform:
            point_x, point_y = transform(point_x, point_y)
        bounds.add(point_x, point_y)

    def add_rotated_box(
        left: float,
        top: float,
        right: float,
        bottom: float,
        angle: float = 0,
        pivot_x: float | None = None,
        pivot_y: float | None = None,
    ) -> None:
        center_x = left if pivot_x is None else pivot_x
        center_y = top if pivot_y is None else pivot_y
        theta = math.radians(-angle)
        for point_x, point_y in (
            (left, top),
            (right, top),
            (right, bottom),
            (left, bottom),
        ):
            delta_x, delta_y = point_x - center_x, point_y - center_y
            rotated_x = center_x + delta_x * math.cos(theta) - delta_y * math.sin(theta)
            rotated_y = center_y + delta_x * math.sin(theta) + delta_y * math.cos(theta)
            add_point(rotated_x, rotated_y)

    if record_type in {"WIRE", "BUS"}:
        elements: list[str] = []
        for group in record[2]:
            _finite_numbers(group, record_type)
            points = " ".join(
                f"{_fmt(group[index])},{_fmt(group[index + 1])}"
                for index in range(0, len(group), 2)
            )
            for index in range(0, len(group), 2):
                add_point(group[index], group[index + 1])
            elements.append(
                f'<polyline points="{points}" {_line_attributes(record[3], line_styles)}/>'
            )
        return "\n".join(elements)
    if record_type == "RECT":
        x1, y1, x2, y2 = map(_number, record[2:6])
        x, y = min(x1, x2), min(y1, y2)
        width, height = abs(x2 - x1), abs(y2 - y1)
        add_rotated_box(x, y, x + width, y + height, _number(record[8]), x1, y1)
        rotate = (
            f' transform="rotate({_fmt(-record[8])} {_fmt(x1)} {_fmt(y1)})"'
            if record[8]
            else ""
        )
        return (
            f'<rect x="{_fmt(x)}" y="{_fmt(y)}" width="{_fmt(width)}" height="{_fmt(height)}" '
            f'rx="{_fmt(record[6])}" ry="{_fmt(record[7])}" '
            f'{_line_attributes(record[9], line_styles)}{rotate}/>'
        )
    if record_type == "POLY":
        points_data = record[2]
        for index in range(0, len(points_data), 2):
            add_point(points_data[index], points_data[index + 1])
        points = " ".join(
            f"{_fmt(points_data[index])},{_fmt(points_data[index + 1])}"
            for index in range(0, len(points_data), 2)
        )
        tag = "polygon" if record[3] else "polyline"
        return f'<{tag} points="{points}" {_line_attributes(record[4], line_styles)}/>'
    if record_type == "CIRCLE":
        cx, cy, radius = map(_number, record[2:5])
        add_rotated_box(cx - radius, cy - radius, cx + radius, cy + radius)
        return (
            f'<circle cx="{_fmt(cx)}" cy="{_fmt(cy)}" r="{_fmt(radius)}" '
            f'{_line_attributes(record[5], line_styles)}/>'
        )
    if record_type == "ELLIPSE":
        cx, cy, radius_x, radius_y, angle = map(_number, record[2:7])
        theta = math.radians(angle)
        extent_x = math.sqrt(
            (radius_x * math.cos(theta)) ** 2
            + (radius_y * math.sin(theta)) ** 2
        )
        extent_y = math.sqrt(
            (radius_x * math.sin(theta)) ** 2
            + (radius_y * math.cos(theta)) ** 2
        )
        add_rotated_box(
            cx - extent_x, cy - extent_y, cx + extent_x, cy + extent_y
        )
        rotate = (
            f' transform="rotate({_fmt(-angle)} {_fmt(cx)} {_fmt(cy)})"'
            if angle
            else ""
        )
        return (
            f'<ellipse cx="{_fmt(cx)}" cy="{_fmt(cy)}" '
            f'rx="{_fmt(radius_x)}" ry="{_fmt(radius_y)}" '
            f'{_line_attributes(record[7], line_styles)}{rotate}/>'
        )
    if record_type == "ARC":
        path, arc_bounds = _arc_path(record)
        add_rotated_box(*arc_bounds)
        return f'<path d="{path}" {_line_attributes(record[8], line_styles)}/>'
    if record_type == "PIN":
        x, y, length, angle = map(_number, record[4:8])
        theta = math.radians(-angle)
        x2 = x + length * math.cos(theta)
        y2 = y + length * math.sin(theta)
        add_point(x, y)
        add_point(x2, y2)
        color = _escape(record[8] or "#880000", quote=True)
        return (
            f'<line x1="{_fmt(x)}" y1="{_fmt(y)}" x2="{_fmt(x2)}" y2="{_fmt(y2)}" '
            f'stroke="{color}" stroke-width="1"/>'
        )
    if record_type == "TEXT":
        x, y, angle = map(_number, record[2:5])
        text = str(record[5])
        attributes, _ = _text_attributes(record[6], font_styles)
        left, top, right, bottom = _text_local_bounds(record[6], font_styles, text)
        add_rotated_box(
            x + left, y + top, x + right, y + bottom, angle, x, y
        )
        rotate = f' transform="rotate({_fmt(-angle)} {_fmt(x)} {_fmt(y)})"' if angle else ""
        return f'<text x="{_fmt(x)}" y="{_fmt(y)}" {attributes}{rotate}>{_escape(text)}</text>'
    if record_type == "OBJ":
        x, y, width, height, angle = map(_number, record[3:8])
        source = str(record[9])
        if source.startswith("blob:"):
            blob_hash = source[5:]
            if blob_hash not in blobs:
                raise MalformedSource(f"OBJ references missing BLOB {blob_hash}")
            source = blobs[blob_hash].data_url
        elif source.startswith("data:"):
            _validate_data_url(source, "OBJ")
        else:
            raise UnsupportedSource(
                f"Unsupported OBJ source: {source!r}", record_type="OBJ"
            )
        conservative_radius = math.hypot(width, height)
        add_rotated_box(
            x - conservative_radius,
            y - conservative_radius,
            x + conservative_radius,
            y + conservative_radius,
        )
        transforms: list[str] = []
        if record[8]:
            transforms.append(f"translate({_fmt(2 * x + width)} 0) scale(-1 1)")
        if angle:
            transforms.append(f"rotate({_fmt(-angle)} {_fmt(x)} {_fmt(y)})")
        transform_attr = (
            f' transform="{_escape(" ".join(transforms), quote=True)}"' if transforms else ""
        )
        return (
            f'<image x="{_fmt(x)}" y="{_fmt(y)}" width="{_fmt(width)}" height="{_fmt(height)}" '
            f'href="{_escape(source, quote=True)}"{transform_attr}/>'
        )
    if record_type == "BUSENTRY":
        x, y, angle = map(_number, record[4:7])
        theta = math.radians(-angle)
        x2, y2 = x + 10 * math.cos(theta), y + 10 * math.sin(theta)
        add_point(x, y)
        add_point(x2, y2)
        return (
            f'<line x1="{_fmt(x)}" y1="{_fmt(y)}" x2="{_fmt(x2)}" y2="{_fmt(y2)}" '
            'stroke="#008800" stroke-width="1"/>'
        )
    if record_type in {"DOCTYPE", "HEAD", "FONTSTYLE", "LINESTYLE", "PART", "GROUP", "ATTR", "COMPONENT"}:
        return None
    raise UnsupportedSource(
        f"Unsupported render record {record_type}",
        record_type=record_type,
        context="render",
    )


def render_svg(archive: V22Archive, margin: float = 20.0) -> SvgResult:
    """Render the active V2.2 sheet into deterministic standalone SVG."""
    margin_value = _number(margin)
    if margin_value < 0:
        raise MalformedSource("SVG margin cannot be negative")
    for record in archive.sheet_records:
        _validate_record(record, "active sheet")
        _validate_coordinates(record, "active sheet")

    sheet_lines = _line_styles(archive.sheet_records)
    sheet_fonts = _font_styles(archive.sheet_records)
    sheet_components = {
        str(record[1]): record for record in archive.sheet_records if record[0] == "COMPONENT"
    }
    sheet_attrs: dict[str, list[list[Any]]] = {}
    for record in archive.sheet_records:
        if record[0] == "ATTR":
            sheet_attrs.setdefault(str(record[2]), []).append(record)

    output: list[str] = []
    bounds = _Bounds()
    primitive_count = 0

    for record in archive.sheet_records:
        record_type = record[0]
        if record_type == "COMPONENT":
            component_id = str(record[1])
            attrs = sheet_attrs.get(component_id, [])
            instance_values = {str(attr[3]): attr[4] for attr in attrs}
            values: dict[str, Any] = {}
            device_id = instance_values.get("Device")
            devices = archive.project.get("devices", {})
            if not isinstance(devices, dict):
                raise MalformedSource("project.json devices must be an object")
            if isinstance(device_id, str) and device_id:
                device = devices.get(device_id)
                if device is not None:
                    if not isinstance(device, dict) or not isinstance(
                        device.get("attributes", {}), dict
                    ):
                        raise MalformedSource(
                            f"Project device {device_id} has malformed attributes"
                        )
                    values.update(device.get("attributes", {}))
            values.update(instance_values)
            symbol_id = values.get("Symbol")
            if not isinstance(symbol_id, str) or symbol_id not in archive.symbols:
                raise MalformedSource(f"Component {component_id} has no loaded Symbol")
            symbol_records = archive.symbols[symbol_id]
            part_records = _select_part_records(symbol_records, str(record[2]))
            if not part_records:
                raise MalformedSource(f"Component {component_id} selected an empty PART")
            symbol_lines = _line_styles(symbol_records)
            symbol_fonts = _font_styles(symbol_records)
            transform_text, transform_point = _component_transform(record)
            local_elements: list[str] = []
            external_elements: list[str] = []
            symbol_root_attrs = [
                item for item in part_records if item[0] == "ATTR" and item[2] == ""
            ]
            symbol_child_attrs = [
                item for item in part_records if item[0] == "ATTR" and item[2] != ""
            ]
            symbol_attr_keys = {str(item[3]) for item in symbol_root_attrs}

            for item in part_records:
                if item[0] == "ATTR":
                    continue
                element = _primitive_svg(
                    item,
                    symbol_lines,
                    symbol_fonts,
                    archive.blobs,
                    bounds,
                    transform_point,
                )
                if element:
                    local_elements.append(element)
                    primitive_count += _svg_element_count(element)

            for symbol_attr in symbol_root_attrs:
                key = str(symbol_attr[3])
                override = next((item for item in attrs if str(item[3]) == key), None)
                chosen = override if override is not None else symbol_attr
                attr_transform = None if override is not None else transform_point
                element = _attribute_svg(
                    chosen, values, sheet_fonts if override is not None else symbol_fonts, bounds, attr_transform
                )
                if element:
                    if override is None:
                        local_elements.append(element)
                    else:
                        external_elements.append(element)
                    primitive_count += 1

            for symbol_attr in symbol_child_attrs:
                parent_id = str(symbol_attr[2])
                overrides = sheet_attrs.get(component_id + parent_id, [])
                override = next(
                    (item for item in overrides if str(item[3]) == str(symbol_attr[3])),
                    None,
                )
                chosen = override if override is not None else symbol_attr
                child_values = dict(values)
                child_values[str(chosen[3])] = chosen[4]
                attr_transform = None if override is not None else transform_point
                element = _attribute_svg(
                    chosen,
                    child_values,
                    sheet_fonts if override is not None else symbol_fonts,
                    bounds,
                    attr_transform,
                )
                if element:
                    if override is None:
                        local_elements.append(element)
                    else:
                        external_elements.append(element)
                    primitive_count += 1

            for attr in attrs:
                if str(attr[3]) in symbol_attr_keys or attr[3] == "Symbol":
                    continue
                element = _attribute_svg(attr, values, sheet_fonts, bounds)
                if element:
                    external_elements.append(element)
                    primitive_count += 1

            if local_elements:
                output.append(
                    f'<g data-component="{_escape(component_id, quote=True)}" '
                    f'transform="{_escape(transform_text, quote=True)}">'
                    + "\n".join(local_elements)
                    + "</g>"
                )
            output.extend(external_elements)
            continue

        if record_type == "ATTR" and str(record[2]) in sheet_components:
            continue
        element = _primitive_svg(
            record, sheet_lines, sheet_fonts, archive.blobs, bounds
        )
        if element:
            output.append(element)
            primitive_count += _svg_element_count(element)

    if bounds.empty or primitive_count == 0:
        raise MalformedSource("Active sheet produced no visible SVG primitives")
    min_x = bounds.min_x - margin_value
    min_y = bounds.min_y - margin_value
    width = max(bounds.max_x - bounds.min_x + 2 * margin_value, 1.0)
    height = max(bounds.max_y - bounds.min_y + 2 * margin_value, 1.0)
    header = (
        '<svg xmlns="http://www.w3.org/2000/svg" '
        'xmlns:xlink="http://www.w3.org/1999/xlink" '
        f'width="{_fmt(width)}" height="{_fmt(height)}" '
        f'viewBox="{_fmt(min_x)} {_fmt(min_y)} {_fmt(width)} {_fmt(height)}">'
    )
    svg = header + "\n" + "\n".join(output) + "\n</svg>\n"
    try:
        ET.fromstring(svg)
    except ET.ParseError as exc:
        raise MalformedSource(f"Generated SVG is not well-formed XML: {exc}") from exc
    return SvgResult(
        svg=svg,
        width=width,
        height=height,
        view_box=(min_x, min_y, width, height),
        primitive_count=primitive_count,
        unsupported_records=(),
    )


def _svg_dimensions(path: Path) -> tuple[float, float]:
    try:
        prefix = path.read_text(encoding="utf-8")[:4096]
    except (OSError, UnicodeDecodeError) as exc:
        raise PdfConversionError(f"Cannot read SVG {path}: {exc}") from exc
    match = re.search(
        r"<svg\b[^>]*\bwidth=\"([0-9]+(?:\.[0-9]+)?)\"[^>]*\bheight=\"([0-9]+(?:\.[0-9]+)?)\"",
        prefix,
    )
    if not match:
        raise PdfConversionError("SVG root is missing numeric width and height")
    width, height = float(match.group(1)), float(match.group(2))
    if width <= 0 or height <= 0:
        raise PdfConversionError("SVG width and height must be positive")
    return width, height


def validate_pdf(path: Path) -> PdfInfo:
    """Require a readable one-page PDF with a nonempty page content stream."""
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise PdfConversionError(f"Cannot read PDF {path}: {exc}") from exc
    if not raw.startswith(b"%PDF-"):
        raise PdfConversionError(f"Output is not a PDF: {path}")
    try:
        from pypdf import PdfReader

        reader = PdfReader(str(path))
        if len(reader.pages) != 1:
            raise PdfConversionError(
                f"Source-rendered PDF must have one page, got {len(reader.pages)}"
            )
        page = reader.pages[0]
        contents = page.get_contents()
        content_bytes = len(contents.get_data()) if contents is not None else 0
        if content_bytes <= 0:
            raise PdfConversionError("Source-rendered PDF page has no content stream")
        extracted_text = page.extract_text() or ""
    except PdfConversionError:
        raise
    except Exception as exc:
        raise PdfConversionError(f"Cannot validate PDF {path}: {exc}") from exc
    return PdfInfo(
        page_count=1,
        extracted_text=extracted_text,
        content_stream_bytes=content_bytes,
    )


def _terminate_process_tree(process: subprocess.Popen[str]) -> None:
    """Terminate the Node helper and all browser descendants."""
    try:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
        else:
            os.killpg(os.getpgid(process.pid), signal.SIGKILL)
    except (OSError, subprocess.SubprocessError):
        try:
            process.kill()
        except OSError:
            pass
    try:
        process.wait(timeout=5)
    except (OSError, subprocess.SubprocessError):
        try:
            process.kill()
        except OSError:
            pass


def _run_chromium_process(
    command: list[str],
    cwd: Path,
    environment: dict[str, str],
    timeout: float,
    *,
    artifact: str,
) -> subprocess.CompletedProcess[str]:
    creation: dict[str, Any] = {}
    if os.name == "nt":
        creation["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        creation["start_new_session"] = True
    try:
        process = subprocess.Popen(
            command,
            cwd=str(cwd),
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            **creation,
        )
    except OSError as exc:
        error_type = PngConversionError if artifact == "PNG" else PdfConversionError
        raise error_type(f"Cannot start Chromium {artifact} converter: {exc}") from exc
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        _terminate_process_tree(process)
        error_type = PngConversionError if artifact == "PNG" else PdfConversionError
        raise error_type(
            f"Chromium {artifact} conversion exceeded {timeout:g} seconds"
        ) from exc
    except (OSError, subprocess.SubprocessError) as exc:
        _terminate_process_tree(process)
        error_type = PngConversionError if artifact == "PNG" else PdfConversionError
        raise error_type(
            f"Chromium {artifact} converter communication failed: {exc}"
        ) from exc
    except BaseException:
        _terminate_process_tree(process)
        raise
    return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)


def _run_pdf_process(
    command: list[str], cwd: Path, environment: dict[str, str], timeout: float
) -> subprocess.CompletedProcess[str]:
    """Backward-compatible PDF wrapper used by the existing test surface."""
    return _run_chromium_process(
        command, cwd, environment, timeout, artifact="PDF"
    )


def convert_svg_to_pdf(
    svg_path: Path,
    pdf_path: Path,
    *,
    node_executable: Path,
    node_path: Path | None,
    timeout: float,
) -> PdfInfo:
    """Print a local SVG through offline Playwright Chromium and atomically publish it."""
    svg = svg_path.resolve()
    pdf = pdf_path.resolve()
    if pdf.exists():
        raise OutputCollision(f"PDF output already exists: {pdf}")
    if not svg.is_file():
        raise PdfConversionError(f"SVG input does not exist: {svg}")
    node = node_executable.resolve()
    if not node.is_file():
        raise PdfConversionError(f"Node executable does not exist: {node}")
    if timeout <= 0:
        raise PdfConversionError("Conversion timeout must be positive")
    width, height = _svg_dimensions(svg)
    helper = Path(__file__).with_name("jlc_pdf_print.cjs")
    if not helper.is_file():
        raise PdfConversionError(f"PDF print helper does not exist: {helper}")
    temporary = pdf.with_name(f".tmp-{uuid.uuid4().hex[:16]}.pdf")
    environment = os.environ.copy()
    if node_path is not None:
        resolved_node_path = node_path.resolve()
        if not resolved_node_path.is_dir():
            raise PdfConversionError(f"NODE_PATH does not exist: {resolved_node_path}")
        environment["NODE_PATH"] = str(resolved_node_path)
    command = [
        str(node),
        str(helper),
        str(svg),
        str(temporary),
        _fmt(width),
        _fmt(height),
    ]
    try:
        completed = _run_pdf_process(command, helper.parent, environment, timeout)
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "unknown error").strip()
            raise PdfConversionError(
                f"Chromium PDF conversion failed ({completed.returncode}): {detail[:2000]}"
            )
        info = validate_pdf(temporary)
        try:
            os.link(temporary, pdf)
        except FileExistsError as exc:
            raise OutputCollision(
                f"PDF output appeared during atomic publication: {pdf}"
            ) from exc
        except OSError as exc:
            raise PdfConversionError(
                f"Cannot atomically publish PDF output {pdf}: {exc}"
            ) from exc
        return info
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def validate_png(path: Path) -> PngInfo:
    """Require a nonempty PNG with a valid IHDR and positive dimensions."""
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise PngConversionError(f"Cannot read PNG {path}: {exc}") from exc
    signature = b"\x89PNG\r\n\x1a\n"
    if len(raw) < 33 or not raw.startswith(signature):
        raise PngConversionError(f"Output is not a PNG: {path}")
    if raw[12:16] != b"IHDR":
        raise PngConversionError(f"PNG is missing its IHDR chunk: {path}")
    width = int.from_bytes(raw[16:20], "big")
    height = int.from_bytes(raw[20:24], "big")
    if width <= 0 or height <= 0:
        raise PngConversionError("PNG width and height must be positive")
    return PngInfo(width=width, height=height, bytes=len(raw))


def convert_svg_to_png(
    svg_path: Path,
    png_path: Path,
    *,
    node_executable: Path,
    node_path: Path | None,
    timeout: float,
) -> PngInfo:
    """Rasterize a local SVG through offline Playwright Chromium and publish atomically."""
    svg = svg_path.resolve()
    png = png_path.resolve()
    if png.exists():
        raise OutputCollision(f"PNG output already exists: {png}")
    if not svg.is_file():
        raise PngConversionError(f"SVG input does not exist: {svg}")
    node = node_executable.resolve()
    if not node.is_file():
        raise PngConversionError(f"Node executable does not exist: {node}")
    if timeout <= 0:
        raise PngConversionError("Conversion timeout must be positive")
    width, height = _svg_dimensions(svg)
    helper = Path(__file__).with_name("jlc_svg_png.cjs")
    if not helper.is_file():
        raise PngConversionError(f"PNG render helper does not exist: {helper}")
    temporary = png.with_name(f".tmp-{uuid.uuid4().hex[:16]}.png")
    environment = os.environ.copy()
    if node_path is not None:
        resolved_node_path = node_path.resolve()
        if not resolved_node_path.is_dir():
            raise PngConversionError(f"NODE_PATH does not exist: {resolved_node_path}")
        environment["NODE_PATH"] = str(resolved_node_path)
    command = [
        str(node),
        str(helper),
        str(svg),
        str(temporary),
        _fmt(width),
        _fmt(height),
    ]
    try:
        completed = _run_chromium_process(
            command, helper.parent, environment, timeout, artifact="PNG"
        )
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "unknown error").strip()
            raise PngConversionError(
                f"Chromium PNG conversion failed ({completed.returncode}): {detail[:2000]}"
            )
        info = validate_png(temporary)
        try:
            os.link(temporary, png)
        except FileExistsError as exc:
            raise OutputCollision(
                f"PNG output appeared during atomic publication: {png}"
            ) from exc
        except OSError as exc:
            raise PngConversionError(
                f"Cannot atomically publish PNG output {png}: {exc}"
            ) from exc
        return info
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
