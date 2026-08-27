"""Deterministic BOM normalization and comparison derived from EasyEDA's BOM Compare extension."""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path
import re
from typing import Any, Iterable, Mapping

from .errors import ContractError


BOM_SCHEMA_VERSION = "easyeda.gateway.normalized-bom.v1"
BOM_DIFF_SCHEMA_VERSION = "easyeda.gateway.bom-diff.v1"

FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "designator": (
        "designator",
        "位号",
        "refdes",
        "ref des",
        "reference",
        "ref",
        "reference designator",
        "id",
    ),
    "footprint": ("footprint", "封装", "package", "case", "decal", "pcb footprint", "pcb package"),
    "quantity": ("quantity", "数量", "qty", "count", "amount"),
    "manufacturer": ("manufacturer", "制造商", "mfg", "vendor", "brand"),
    "partNumber": (
        "partnumber",
        "part number",
        "manufacturer part",
        "manufacturer part number",
        "型号",
        "pn",
        "mpn",
        "part no",
        "lcsc part number",
        "lcsc",
        "supplier and ref",
        "mfg part number",
        "mfg part",
        "part type",
    ),
    "supplierPart": ("supplier part", "supplier part number", "supplier id", "lcsc part", "立创编号"),
    "value": ("value", "值", "val", "comment", "designation", "resistance", "capacitance"),
    "description": ("description", "描述", "说明", "desc", "note", "libref"),
}

COMPARE_FIELDS = (
    "footprint",
    "quantity",
    "manufacturer",
    "partNumber",
    "supplierPart",
    "value",
    "description",
)


def load_bom(path: str | Path) -> dict[str, Any]:
    """Load CSV, TSV/TXT, or JSON BOM data and normalize its columns."""
    source = Path(path).resolve()
    if not source.is_file():
        raise ContractError(f"BOM file does not exist: {source}")
    suffix = source.suffix.lower()
    if suffix == ".json":
        try:
            value = json.loads(source.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ContractError(f"Cannot parse JSON BOM {source}: {exc}") from exc
        if isinstance(value, Mapping):
            rows = value.get("rows") or value.get("bom") or value.get("components")
        else:
            rows = value
        if not isinstance(rows, list) or not all(isinstance(row, Mapping) for row in rows):
            raise ContractError("JSON BOM must be an array of objects or contain rows/bom/components")
        return normalize_bom_rows(rows, source=str(source))
    if suffix not in {".csv", ".tsv", ".txt"}:
        raise ContractError("Supported BOM formats are CSV, TSV/TXT, and JSON")
    raw = source.read_bytes()
    text = _decode_text(raw)
    delimiter = "\t" if suffix == ".tsv" else _sniff_delimiter(text)
    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
    if not reader.fieldnames:
        raise ContractError(f"BOM file has no header row: {source}")
    return normalize_bom_rows(list(reader), source=str(source))


def normalize_bom_rows(rows: Iterable[Mapping[str, Any]], *, source: str = "memory") -> dict[str, Any]:
    materialized = [dict(row) for row in rows]
    headers: list[str] = []
    for row in materialized:
        for key in row:
            if str(key) not in headers:
                headers.append(str(key))
    mappings, duplicates = map_columns(headers)
    designator_source = next((item["sourceColumn"] for item in mappings if item["targetField"] == "designator"), None)
    if not designator_source:
        raise ContractError("BOM requires a Designator/位号/RefDes column")
    normalized: list[dict[str, str]] = []
    for row_index, row in enumerate(materialized, start=2):
        record = {field: "" for field in FIELD_ALIASES}
        for mapping in mappings:
            target = mapping["targetField"]
            if target == "ignore":
                continue
            record[target] = _clean_cell(row.get(mapping["sourceColumn"]))
        record["designator"] = _normalize_designators(record["designator"])
        if not record["designator"]:
            raise ContractError(f"BOM row {row_index} has an empty designator")
        if not record["quantity"]:
            record["quantity"] = str(max(1, len(_split_designators(record["designator"]))))
        normalized.append(record)
    normalized.sort(key=lambda row: _natural_key(row["designator"]))
    return {
        "schemaVersion": BOM_SCHEMA_VERSION,
        "source": source,
        "headers": headers,
        "columnMappings": mappings,
        "duplicateMappings": duplicates,
        "rows": normalized,
        "rowCount": len(normalized),
    }


def map_columns(headers: Iterable[str]) -> tuple[list[dict[str, str]], list[dict[str, Any]]]:
    mappings: list[dict[str, str]] = []
    selected: dict[str, str] = {}
    duplicates: list[dict[str, Any]] = []
    for raw_header in headers:
        header = str(raw_header)
        target = _match_column(header)
        if target is None:
            mappings.append({"sourceColumn": header, "targetField": "ignore"})
            continue
        if target in selected:
            mappings.append({"sourceColumn": header, "targetField": "ignore"})
            duplicate = next((item for item in duplicates if item["targetField"] == target), None)
            if duplicate is None:
                duplicate = {
                    "sourceColumn": selected[target],
                    "targetField": target,
                    "conflictWith": [],
                }
                duplicates.append(duplicate)
            duplicate["conflictWith"].append(header)
            continue
        selected[target] = header
        mappings.append({"sourceColumn": header, "targetField": target})
    return mappings, duplicates


def compare_boms(old_bom: Mapping[str, Any], new_bom: Mapping[str, Any]) -> dict[str, Any]:
    old_rows = _require_normalized_rows(old_bom, "old")
    new_rows = _require_normalized_rows(new_bom, "new")
    old_map = _rows_by_designator(old_rows)
    new_map = _rows_by_designator(new_rows)
    results: list[dict[str, Any]] = []
    for designator in sorted(set(old_map) | set(new_map), key=_natural_key):
        old_group = old_map.get(designator, [])
        new_group = new_map.get(designator, [])
        for index in range(max(len(old_group), len(new_group))):
            old_row = old_group[index] if index < len(old_group) else None
            new_row = new_group[index] if index < len(new_group) else None
            if old_row is None:
                results.append({"type": "added", "oldRow": None, "newRow": new_row, "cellDiffs": []})
                continue
            if new_row is None:
                results.append({"type": "removed", "oldRow": old_row, "newRow": None, "cellDiffs": []})
                continue
            diffs = [
                {"field": field, "oldValue": old_row.get(field, ""), "newValue": new_row.get(field, "")}
                for field in COMPARE_FIELDS
                if old_row.get(field, "").strip() != new_row.get(field, "").strip()
            ]
            results.append(
                {
                    "type": "changed" if diffs else "same",
                    "oldRow": old_row,
                    "newRow": new_row,
                    "cellDiffs": diffs,
                },
            )
    order = {"same": 0, "changed": 0, "removed": 1, "added": 2}
    results.sort(
        key=lambda item: (
            order[item["type"]],
            _natural_key((item["oldRow"] or item["newRow"])["designator"]),
        ),
    )
    summary = {kind: sum(item["type"] == kind for item in results) for kind in ("same", "changed", "added", "removed")}
    summary["total"] = len(results)
    return {
        "schemaVersion": BOM_DIFF_SCHEMA_VERSION,
        "oldSource": old_bom.get("source"),
        "newSource": new_bom.get("source"),
        "comparedColumns": list(COMPARE_FIELDS),
        "summary": summary,
        "rows": results,
    }


def _require_normalized_rows(value: Mapping[str, Any], label: str) -> list[dict[str, str]]:
    rows = value.get("rows")
    if value.get("schemaVersion") != BOM_SCHEMA_VERSION or not isinstance(rows, list):
        raise ContractError(f"{label} BOM is not a {BOM_SCHEMA_VERSION} document")
    if not all(isinstance(row, dict) for row in rows):
        raise ContractError(f"{label} BOM rows must be objects")
    return rows


def _rows_by_designator(rows: Iterable[dict[str, str]]) -> dict[str, list[dict[str, str]]]:
    result: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        result.setdefault(row["designator"].strip(), []).append(row)
    return result


def _match_column(header: str) -> str | None:
    normalized = re.sub(r"\s+", " ", header.strip().lower())
    for field, aliases in FIELD_ALIASES.items():
        if normalized in aliases:
            return field
    return None


def _decode_text(raw: bytes) -> str:
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        try:
            return raw.decode("utf-16")
        except UnicodeDecodeError:
            pass
    for encoding in ("utf-8-sig", "gb18030"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ContractError("BOM text encoding is not UTF-16 with BOM, UTF-8, or GB18030")


def _sniff_delimiter(text: str) -> str:
    try:
        return csv.Sniffer().sniff(text[:8192], delimiters=",\t;").delimiter
    except csv.Error:
        return ","


def _clean_cell(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _split_designators(value: str) -> list[str]:
    return [item for item in re.split(r"[,;\s]+", value.strip()) if item]


def _normalize_designators(value: str) -> str:
    return ",".join(sorted(dict.fromkeys(_split_designators(value)), key=_natural_key))


def _natural_key(value: str) -> tuple[Any, ...]:
    return tuple(int(part) if part.isdigit() else part.casefold() for part in re.split(r"(\d+)", value))
