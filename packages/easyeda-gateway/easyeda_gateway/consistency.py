"""Serial full-schematic evidence bundle and cross-artifact consistency checks."""

from __future__ import annotations

from collections import Counter
import csv
import io
import json
from pathlib import Path
import re
from typing import Any, Iterable, Mapping

from .artifact_io import atomic_write_json, create_evidence_directory, sha256_file, utc_now
from .drc import EasyedaDrcAdapter
from .errors import BridgeError
from .exporter import EasyedaExportAdapter, SchematicExportSpec
from .formal_exporter import EasyedaFormalExportAdapter, FormalExportSpec
from .version import GATEWAY_VERSION


CONSISTENCY_SCHEMA = "easyeda.gateway.schematic-evidence-bundle.v2"


class EasyedaEvidenceBundleAdapter:
    """Run the retained jlc evidence set as isolated, serial bridge requests."""

    def __init__(
        self,
        visual: EasyedaExportAdapter,
        formal: EasyedaFormalExportAdapter,
        drc: EasyedaDrcAdapter,
    ):
        self.visual = visual
        self.formal = formal
        self.drc = drc

    def execute(
        self,
        evidence_root: str | Path,
        *,
        identity: Mapping[str, Any] | None = None,
        window_id: str | None = None,
        safety_state_path: str | Path | None = None,
        required_refs: Iterable[str] = (),
        forbidden_refs: Iterable[str] = (),
        allow_window_rebind: bool = False,
    ) -> dict[str, Any]:
        bundle_directory = create_evidence_directory(evidence_root, "schematic-evidence-bundle")
        safety_path = Path(safety_state_path).resolve() if safety_state_path else bundle_directory / "export-safety.json"
        started_at = utc_now()
        manifest = {
            "schemaVersion": "easyeda.gateway.schematic-evidence-bundle-request.v1",
            "executionModel": "SERIAL_ISOLATED_REQUESTS",
            "automaticRetry": False,
            "identity": dict(identity or {}),
            "windowId": window_id,
            "safetyStatePath": str(safety_path),
            "steps": [
                "visual.current-schematic.pdf",
                "bom.csv",
                "netlist.jlceda",
                "source.epro",
                "drc.strict",
            ],
            "requiredRefs": _normalize_refs(required_refs),
            "forbiddenRefs": _normalize_refs(forbidden_refs),
        }
        atomic_write_json(bundle_directory / "request.json", manifest)
        try:
            pdf = self.visual.execute(
                SchematicExportSpec(file_type="PDF", scope="current-schematic", theme="Default", line_width="Default"),
                bundle_directory / "pdf",
                identity=identity,
                window_id=window_id,
                safety_state_path=safety_path,
                allow_window_rebind=allow_window_rebind,
            )
            bom = self.formal.execute(
                FormalExportSpec("bom", "csv"),
                bundle_directory / "bom",
                identity=identity,
                window_id=window_id,
                safety_state_path=safety_path,
                allow_window_rebind=allow_window_rebind,
            )
            netlist = self.formal.execute(
                FormalExportSpec("netlist", "jlceda"),
                bundle_directory / "netlist",
                identity=identity,
                window_id=window_id,
                safety_state_path=safety_path,
                allow_window_rebind=allow_window_rebind,
            )
            source = self.formal.execute(
                FormalExportSpec("source", "epro"),
                bundle_directory / "source",
                identity=identity,
                window_id=window_id,
                safety_state_path=safety_path,
                allow_window_rebind=allow_window_rebind,
            )
            drc = self.drc.execute(
                bundle_directory / "drc",
                identity=identity,
                window_id=window_id,
                safety_state_path=safety_path,
                allow_window_rebind=allow_window_rebind,
            )
            report = build_consistency_report(
                pdf.artifact_path,
                bom.artifact_path,
                netlist.artifact_path,
                drc.report,
                required_refs=required_refs,
                forbidden_refs=forbidden_refs,
            )
            identities = [pdf.identity, bom.identity, netlist.identity, source.identity, drc.identity]
            report["identity"] = identities[0]
            report["identityStableAcrossSteps"] = all(item == identities[0] for item in identities[1:])
            if not report["identityStableAcrossSteps"]:
                report["status"] = "BLOCKED_IDENTITY_DRIFT"
                report["blockers"].append("Project or document identity changed between isolated export steps")
            report["artifacts"] = {
                "pdf": _artifact_record(pdf.artifact_path, pdf.evidence_path),
                "bom": _artifact_record(bom.artifact_path, bom.evidence_path),
                "netlist": _artifact_record(netlist.artifact_path, netlist.evidence_path),
                "source": _artifact_record(source.artifact_path, source.evidence_path),
                "drc": _artifact_record(drc.report_path, drc.evidence_path),
            }
            report["gatewayVersion"] = GATEWAY_VERSION
            report["startedAt"] = started_at
            report["finishedAt"] = utc_now()
            report["executionModel"] = "SERIAL_ISOLATED_REQUESTS"
            report["automaticRetry"] = False
            report["safetyStatePath"] = str(safety_path)
            report["artifactsComplete"] = True
            report["reviewStatus"] = report["status"]
            report["accepted"] = report["status"] == "PASS"
            atomic_write_json(bundle_directory / "bundle-report.json", report)
            envelope = {
                "schemaVersion": "easyeda.gateway.schematic-evidence-bundle-envelope.v1",
                "status": report["status"],
                "startedAt": started_at,
                "finishedAt": report["finishedAt"],
                "gatewayVersion": GATEWAY_VERSION,
                "identity": report["identity"],
                "files": {
                    "request.json": sha256_file(bundle_directory / "request.json"),
                    "bundle-report.json": sha256_file(bundle_directory / "bundle-report.json"),
                },
                "childEvidence": {
                    name: value["evidencePath"] for name, value in report["artifacts"].items()
                },
            }
            atomic_write_json(bundle_directory / "envelope.json", envelope)
            return {
                "success": report["accepted"],
                "transportSuccess": True,
                "artifactsComplete": True,
                "accepted": report["accepted"],
                "reviewStatus": report["status"],
                "bundleDirectory": str(bundle_directory),
                "reportPath": str(bundle_directory / "bundle-report.json"),
                "evidencePath": str(bundle_directory / "envelope.json"),
                "report": report,
            }
        except Exception as exc:
            failure = {
                "schemaVersion": "easyeda.gateway.schematic-evidence-bundle-failure.v1",
                "status": "FAIL",
                "startedAt": started_at,
                "finishedAt": utc_now(),
                "error": {"type": type(exc).__name__, "message": str(exc)},
                "automaticRetry": False,
                "safetyStatePath": str(safety_path),
            }
            atomic_write_json(bundle_directory / "failure.json", failure)
            atomic_write_json(
                bundle_directory / "envelope.json",
                {
                    **failure,
                    "schemaVersion": "easyeda.gateway.schematic-evidence-bundle-envelope.v1",
                    "files": {
                        "request.json": sha256_file(bundle_directory / "request.json"),
                        "failure.json": sha256_file(bundle_directory / "failure.json"),
                    },
                },
            )
            raise


def build_consistency_report(
    pdf_path: str | Path,
    bom_path: str | Path,
    netlist_path: str | Path,
    drc_report: Mapping[str, Any],
    *,
    required_refs: Iterable[str] = (),
    forbidden_refs: Iterable[str] = (),
) -> dict[str, Any]:
    pdf = Path(pdf_path)
    bom = parse_formal_bom(Path(bom_path))
    netlist = parse_jlceda_netlist(Path(netlist_path))
    required = set(_normalize_refs(required_refs))
    forbidden = set(_normalize_refs(forbidden_refs))
    pdf_text, pdf_validation = extract_pdf_text(pdf)
    pdf_present = {
        ref for ref in (bom["designators"] | required | forbidden)
        if pdf_text is not None and _pdf_ref_present(pdf_text, ref)
    }
    bom_minus_netlist = bom["designators"] - netlist["bomDesignators"]
    netlist_minus_bom = netlist["bomDesignators"] - bom["designators"]
    pdf_text_missing = bom["designators"] - pdf_present if pdf_text is not None else set()
    missing_required_by = {
        "bom": required - bom["designators"],
        "netlistBom": required - netlist["bomDesignators"],
        "pdf": required - pdf_present if pdf_text is not None else required,
    }
    present_forbidden_by = {
        "bom": forbidden & bom["designators"],
        "netlist": forbidden & netlist["designators"],
        "pdf": forbidden & pdf_present,
    }
    blockers: list[str] = []
    review_findings: list[dict[str, Any]] = []
    validation_blocked = False
    if bom_minus_netlist or netlist_minus_bom:
        blockers.append("Formal BOM and JLCEDA netlist Add into BOM designator sets differ")
    if bom["duplicates"] or netlist["duplicates"]:
        blockers.append("Duplicate designators exist in formal BOM or netlist")
    if bom["quantityMismatches"]:
        blockers.append("Formal BOM row quantities do not match designator counts")
    if netlist["missingDesignatorComponentCount"]:
        blockers.append("Formal netlist contains components without designators")
    if pdf_text is None:
        blockers.append(f"Native PDF reference coverage was not evaluated: {pdf_validation}")
        validation_blocked = True
    elif pdf_text_missing:
        review_findings.append(
            {
                "code": "PDF_TEXT_LAYER_INCOMPLETE",
                "severity": "REVIEW_REQUIRED",
                "refs": _natural_sorted(pdf_text_missing),
                "message": (
                    "Native PDF text extraction did not expose every BOM designator; "
                    "this is not proof that the references are visually absent"
                ),
            }
        )
    if missing_required_by["bom"] or missing_required_by["netlistBom"]:
        blockers.append("Required designators are missing from one or more artifacts")
    if missing_required_by["pdf"]:
        blockers.append("Required designators could not be verified in the native PDF text layer")
        validation_blocked = True
    if any(present_forbidden_by.values()):
        blockers.append("Forbidden designators are present in one or more artifacts")
    drc_status = str(drc_report.get("status") or "UNKNOWN")
    if drc_status == "BLOCKED_BY_DRC":
        status = "BLOCKED_BY_DRC"
    elif blockers:
        status = "BLOCKED_VALIDATION" if validation_blocked else "BLOCKED_MISMATCH"
    elif drc_status == "REVIEW_REQUIRED" or review_findings:
        status = "REVIEW_REQUIRED"
    else:
        status = "PASS"
    return {
        "schemaVersion": CONSISTENCY_SCHEMA,
        "status": status,
        "readOnly": True,
        "officialEasyEdaPdf": True,
        "scope": "Current Schematic",
        "comparison": {
            "bomDesignatorCount": len(bom["designators"]),
            "netlistDesignatorCount": len(netlist["designators"]),
            "netlistBomDesignatorCount": len(netlist["bomDesignators"]),
            "bomMinusNetlistBom": _natural_sorted(bom_minus_netlist),
            "netlistBomMinusBom": _natural_sorted(netlist_minus_bom),
            "pdfMissingBomRefs": _natural_sorted(pdf_text_missing),
            "pdfTextLayerMissingBomRefs": _natural_sorted(pdf_text_missing),
            "duplicateBomDesignators": bom["duplicates"],
            "duplicateNetlistDesignators": netlist["duplicates"],
            "bomQuantityMismatches": bom["quantityMismatches"],
            "bomNetlistSetMatch": not bom_minus_netlist and not netlist_minus_bom,
            "pdfReferenceCoverageComplete": (
                True if pdf_text is not None and not pdf_text_missing else None
            ),
            "pdfTextLayerCoverageComplete": (
                None if pdf_text is None else not pdf_text_missing
            ),
            "pdfReferenceCoverageStatus": (
                "UNAVAILABLE"
                if pdf_text is None
                else (
                    "VERIFIED_BY_TEXT_LAYER"
                    if not pdf_text_missing
                    else "TEXT_LAYER_INCOMPLETE_REVIEW_REQUIRED"
                )
            ),
            "pdfValidation": pdf_validation,
        },
        "constraints": {
            "requiredRefs": _natural_sorted(required),
            "forbiddenRefs": _natural_sorted(forbidden),
            "missingRequiredByArtifact": {
                key: _natural_sorted(value) for key, value in missing_required_by.items()
            },
            "presentForbiddenByArtifact": {
                key: _natural_sorted(value) for key, value in present_forbidden_by.items()
            },
        },
        "drc": dict(drc_report),
        "reviewFindings": review_findings,
        "blockers": blockers,
        "accepted": status == "PASS",
    }


def parse_formal_bom(path: Path) -> dict[str, Any]:
    data = path.read_bytes()
    codecs = ["utf-16"] if data.startswith((b"\xff\xfe", b"\xfe\xff")) else ["utf-8-sig", "utf-16"]
    text = None
    encoding = None
    for codec in codecs:
        try:
            text = data.decode(codec)
            encoding = codec
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        raise BridgeError(f"Formal BOM encoding is unsupported: {path}")
    first_line = next((line for line in text.splitlines() if line.strip()), "")
    delimiter = "\t" if first_line.count("\t") >= first_line.count(",") else ","
    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
    if not reader.fieldnames:
        raise BridgeError("Formal BOM has no header")
    aliases = {
        "designator": {"designator", "位号"},
        "quantity": {"quantity", "数量"},
    }
    field_map = {str(name).strip().casefold(): name for name in reader.fieldnames}
    designator_field = next((field_map[name] for name in aliases["designator"] if name in field_map), None)
    quantity_field = next((field_map[name] for name in aliases["quantity"] if name in field_map), None)
    if not designator_field or not quantity_field:
        raise BridgeError("Formal BOM must contain Designator/位号 and Quantity/数量 columns")
    refs: list[str] = []
    quantity_mismatches: list[dict[str, Any]] = []
    row_count = 0
    for row_count, row in enumerate(reader, start=1):
        row_refs = [
            value.upper() for value in re.split(r"[,;\s]+", str(row.get(designator_field) or "").strip()) if value
        ]
        refs.extend(row_refs)
        quantity_raw = str(row.get(quantity_field) or "").strip()
        try:
            quantity = int(float(quantity_raw))
        except ValueError:
            quantity = -1
        if quantity != len(row_refs):
            quantity_mismatches.append(
                {"row": row_count, "quantity": quantity_raw, "designatorCount": len(row_refs), "designators": _natural_sorted(row_refs)},
            )
    if not refs:
        raise BridgeError("Formal BOM contains no designators")
    counts = Counter(refs)
    return {
        "designators": set(refs),
        "duplicates": _natural_sorted(ref for ref, count in counts.items() if count > 1),
        "quantityMismatches": quantity_mismatches,
        "rowCount": row_count,
        "encoding": encoding,
        "delimiter": "tab" if delimiter == "\t" else "comma",
    }


def parse_jlceda_netlist(path: Path) -> dict[str, Any]:
    try:
        root = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BridgeError(f"Cannot parse JLCEDA netlist {path}: {exc}") from exc
    if not isinstance(root, dict) or not isinstance(root.get("components"), (dict, list)):
        raise BridgeError("JLCEDA netlist must contain a components object or array")
    components = root["components"]
    values = components.values() if isinstance(components, dict) else components
    refs: list[str] = []
    bom_refs: list[str] = []
    pcb_refs: list[str] = []
    missing = 0
    for component in values:
        if not isinstance(component, Mapping) or not isinstance(component.get("props"), Mapping):
            missing += 1
            continue
        props = component["props"]
        ref = str(props.get("Designator") or "").strip().upper()
        if not ref:
            missing += 1
            continue
        refs.append(ref)
        if _yes(props.get("Add into BOM")):
            bom_refs.append(ref)
        if _yes(props.get("Convert to PCB")):
            pcb_refs.append(ref)
    if not refs:
        raise BridgeError("JLCEDA netlist contains no component designators")
    counts = Counter(refs)
    return {
        "designators": set(refs),
        "bomDesignators": set(bom_refs),
        "pcbDesignators": set(pcb_refs),
        "duplicates": _natural_sorted(ref for ref, count in counts.items() if count > 1),
        "missingDesignatorComponentCount": missing,
    }


def extract_pdf_text(path: Path) -> tuple[str | None, str]:
    try:
        from pypdf import PdfReader
    except ImportError:
        return None, "PYPDF_UNAVAILABLE"
    try:
        reader = PdfReader(str(path))
        text = "\n".join((page.extract_text() or "") for page in reader.pages)
    except Exception as exc:
        return None, f"PDF_EXTRACTION_FAILED:{type(exc).__name__}:{exc}"
    if not text.strip():
        return None, "PDF_TEXT_EMPTY"
    return text, f"PASS:{len(reader.pages)}_PAGES"


def _artifact_record(path: Path, evidence_path: Path) -> dict[str, Any]:
    return {
        "path": str(path),
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
        "evidencePath": str(evidence_path),
    }


def _normalize_refs(values: Iterable[str]) -> list[str]:
    return _natural_sorted({str(value).strip().upper() for value in values if str(value).strip()})


def _natural_sorted(values: Iterable[str]) -> list[str]:
    def key(value: str) -> list[Any]:
        return [int(part) if part.isdigit() else part.casefold() for part in re.split(r"(\d+)", value)]

    return sorted(values, key=key)


def _yes(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().casefold() in {"yes", "true", "1"}


def _pdf_ref_present(text: str, ref: str) -> bool:
    return re.search(rf"(?<![A-Za-z0-9_]){re.escape(ref)}(?![A-Za-z0-9_])", text, flags=re.IGNORECASE) is not None
