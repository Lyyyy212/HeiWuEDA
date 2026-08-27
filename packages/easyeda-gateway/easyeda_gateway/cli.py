"""Command-line interface for the guarded EasyEDA gateway."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from typing import Any, Mapping, Sequence
from uuid import uuid4

from .client import BridgeClient, BridgeError, discover_bridge
from .bom import compare_boms, load_bom
from .board_navigator import BoardDocumentNavigationSpec, EasyedaBoardDocumentNavigator
from .composite import CompositeReadExecutor
from .consistency import EasyedaEvidenceBundleAdapter
from .contract import ApiRegistry, load_json, plan_digest
from .drc import EasyedaDrcAdapter
from .device_match import DeviceMatchSpec, EasyedaDeviceMatchDryRunAdapter
from .evidence_archive import create_evidence_archive
from .errors import GatewayError
from .executor import BridgeExecutor
from .export_safety import ExportSafetyController, capability_report, refuse_epro_visual_render
from .exporter import EasyedaExportAdapter, SchematicExportSpec
from .formal_exporter import EasyedaFormalExportAdapter, FormalExportSpec
from .ibom import build_ibom_model, write_ibom_html
from .intelligence import analyze_schematic_snapshot, build_pcb_report
from .native_visual import normalize_existing_official_png_bundle
from .native_pdf_visual import render_existing_official_pdf
from .official_plugins import EasyedaOfficialPluginAdapter, OfficialPluginSpec, SUPPORTED_MATERIALS
from .page_navigator import EasyedaPageNavigator, SchematicPageNavigationSpec
from .source_render import (
    OfflineProjectSourceRenderAdapter,
    OfflineSourceRenderAdapter,
    SourceRenderSpec,
)
from .version import GATEWAY_VERSION


def main(argv: Sequence[str] | None = None) -> int:
    _configure_stdio_utf8()
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        result = args.handler(args)
    except (GatewayError, OSError, ValueError) as exc:
        _print_json({"success": False, "error": str(exc)}, stream=sys.stderr)
        return 1
    if result is not None:
        _print_json(result)
        if isinstance(result, dict) and result.get("success") is False:
            return 1
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Guarded API adapter for the official EasyEDA bridge")
    parser.add_argument("--version", action="version", version=GATEWAY_VERSION)
    parser.set_defaults(handler=lambda _: parser.print_help())
    subparsers = parser.add_subparsers(dest="command")

    identity = subparsers.add_parser("identity", help="print the locked API registry identity")
    _add_manifest(identity)
    identity.set_defaults(handler=_identity)

    validate = subparsers.add_parser("validate-plan", help="validate a typed API plan")
    _add_manifest(validate)
    validate.add_argument("--plan", required=True, type=Path)
    validate.set_defaults(handler=_validate_plan)

    digest = subparsers.add_parser("digest-plan", help="calculate or write planDigest")
    digest.add_argument("--plan", required=True, type=Path)
    digest.add_argument("--write", action="store_true")
    digest.set_defaults(handler=_digest_plan)

    discover = subparsers.add_parser("discover", help="discover and verify the official local bridge")
    discover.set_defaults(handler=_discover)

    windows = subparsers.add_parser("windows", help="list connected EasyEDA windows")
    _add_bridge_url(windows)
    windows.set_defaults(handler=_windows)

    select = subparsers.add_parser("select", help="select an active EasyEDA window")
    _add_bridge_url(select)
    select.add_argument("--window-id", required=True)
    select.set_defaults(handler=_select)

    probe = subparsers.add_parser("probe", help="run a guarded read-only context probe")
    _add_manifest(probe)
    _add_bridge_url(probe)
    probe.add_argument("--window-id")
    probe.add_argument("--evidence-dir", type=Path, default=Path("evidence/gateway"))
    probe.add_argument("--bridge-metadata", type=Path, default=Path(".runtime/easyeda-bridge.json"))
    probe.set_defaults(handler=_probe)

    execute = subparsers.add_parser("execute-plan", help="execute a validated typed API plan")
    _add_manifest(execute)
    _add_bridge_url(execute)
    execute.add_argument("--plan", required=True, type=Path)
    execute.add_argument("--evidence-dir", type=Path, default=Path("evidence/gateway"))
    execute.add_argument("--authorization", type=Path)
    execute.add_argument("--acceptance", type=Path)
    execute.add_argument("--bridge-metadata", type=Path, default=Path(".runtime/easyeda-bridge.json"))
    execute.set_defaults(handler=_execute_plan)

    schematic = subparsers.add_parser(
        "schematic-snapshot",
        help="capture and analyze the active schematic with a fixed read-only template",
    )
    _add_composite_options(schematic)
    schematic.add_argument("--output", type=Path, default=Path("artifacts/schematic-analysis.json"))
    schematic.set_defaults(handler=_schematic_snapshot)

    schematic_pages = subparsers.add_parser(
        "schematic-pages",
        help="list the ordered pages of the active schematic without switching tabs",
    )
    _add_composite_options(schematic_pages)
    schematic_pages.set_defaults(handler=_schematic_pages)

    schematic_page_activate = subparsers.add_parser(
        "schematic-page-activate",
        help="activate one page in the current schematic through guarded official APIs",
    )
    _add_composite_options(schematic_page_activate)
    schematic_page_activate.add_argument("--page-uuid", required=True)
    schematic_page_activate.set_defaults(handler=_schematic_page_activate)

    schematic_page_traverse = subparsers.add_parser(
        "schematic-page-traverse",
        help="visit every current-schematic page and restore the originally active page",
    )
    _add_composite_options(schematic_page_traverse)
    schematic_page_traverse.set_defaults(handler=_schematic_page_traverse)

    board_documents = subparsers.add_parser(
        "board-documents",
        help="list board-associated schematic pages and PCBs in the active project",
    )
    _add_composite_options(board_documents)
    board_documents.set_defaults(handler=_board_documents)

    board_document_activate = subparsers.add_parser(
        "board-document-activate",
        help="activate an exact board schematic page or PCB through guarded official APIs",
    )
    _add_composite_options(board_document_activate)
    board_document_activate.add_argument("--target-uuid", required=True)
    board_document_activate.add_argument(
        "--target-document-type", required=True, type=int, choices=(1, 3)
    )
    board_document_activate.set_defaults(handler=_board_document_activate)

    schematic_export = subparsers.add_parser(
        "schematic-export",
        help="export an official schematic artifact with a fixed compatibility adapter",
    )
    _add_composite_options(schematic_export)
    _add_export_safety(schematic_export)
    schematic_export.add_argument("--format", choices=("PNG", "PDF", "SVG"), default="PNG")
    schematic_export.add_argument(
        "--scope",
        choices=("current-page", "current-schematic"),
        default="current-schematic",
    )
    schematic_export.add_argument(
        "--theme",
        choices=("Default", "White on Black", "Black on White"),
        default="Black on White",
    )
    schematic_export.add_argument(
        "--line-width",
        choices=("Default", "Always 1px", "Follow the Zoom Change"),
        default="Always 1px",
    )
    schematic_export.add_argument(
        "--output",
        type=Path,
        help="optional non-existing published copy; the immutable artifact always remains in evidence-dir",
    )
    schematic_export.set_defaults(handler=_schematic_export)

    native_png_normalize = subparsers.add_parser(
        "schematic-native-png-normalize",
        help="locally normalize an already-issued official multi-page PNG bundle without another EasyEDA call",
    )
    native_png_normalize.add_argument("--source", required=True, type=Path)
    native_png_normalize.add_argument("--source-envelope", required=True, type=Path)
    native_png_normalize.add_argument("--identity-before", required=True, type=Path)
    native_png_normalize.add_argument("--identity-after", required=True, type=Path)
    native_png_normalize.add_argument("--evidence-dir", required=True, type=Path)
    native_png_normalize.add_argument("--output", required=True, type=Path)
    native_png_normalize.set_defaults(handler=_schematic_native_png_normalize)

    native_pdf_render = subparsers.add_parser(
        "schematic-native-pdf-render",
        help="locally render an admitted official current-schematic PDF into bounded high-resolution PNG pages",
    )
    native_pdf_render.add_argument("--source-execution", required=True, type=Path)
    native_pdf_render.add_argument("--identity-before", required=True, type=Path)
    native_pdf_render.add_argument("--identity-after", required=True, type=Path)
    native_pdf_render.add_argument("--evidence-dir", required=True, type=Path)
    native_pdf_render.add_argument("--output", required=True, type=Path)
    native_pdf_render.add_argument("--pdftoppm", type=Path)
    native_pdf_render.add_argument("--max-long-edge", type=int, default=6144)
    native_pdf_render.add_argument("--render-timeout", type=float, default=300.0)
    native_pdf_render.set_defaults(handler=_schematic_native_pdf_render)

    capabilities = subparsers.add_parser(
        "export-capabilities",
        help="show which EasyEDA exports are verified, blocked, or future work",
    )
    capabilities.set_defaults(handler=lambda _: {"success": True, **capability_report()})

    safety_status = subparsers.add_parser(
        "export-safety-status",
        help="show the persistent EasyEDA export circuit-breaker state",
    )
    _add_export_safety(safety_status)
    safety_status.set_defaults(handler=_export_safety_status)

    safety_reset = subparsers.add_parser(
        "export-safety-reset",
        help="reset the export breaker after EasyEDA has been recovered or restarted",
    )
    _add_export_safety(safety_reset)
    safety_reset.add_argument("--reason", required=True)
    safety_reset.set_defaults(handler=_export_safety_reset)

    bom_export = subparsers.add_parser(
        "schematic-bom-export",
        help="export one formal schematic BOM artifact",
    )
    _add_composite_options(bom_export)
    _add_export_safety(bom_export)
    bom_export.add_argument("--format", choices=("csv", "xlsx"), default="csv")
    bom_export.add_argument("--output", type=Path)
    bom_export.set_defaults(handler=_schematic_bom_export)

    netlist_export = subparsers.add_parser(
        "schematic-netlist-export",
        help="export one formal schematic netlist artifact",
    )
    _add_composite_options(netlist_export)
    _add_export_safety(netlist_export)
    netlist_export.add_argument("--format", choices=("jlceda", "protel2"), default="jlceda")
    netlist_export.add_argument("--output", type=Path)
    netlist_export.set_defaults(handler=_schematic_netlist_export)

    source_export = subparsers.add_parser(
        "schematic-source-export",
        help="export the active schematic document source archive",
    )
    _add_composite_options(source_export)
    _add_export_safety(source_export)
    source_export.add_argument("--format", choices=("epro", "epro2"), default="epro")
    source_export.add_argument("--output", type=Path)
    source_export.set_defaults(handler=_schematic_source_export)

    project_source_export = subparsers.add_parser(
        "schematic-project-source-export",
        help="export the active EasyEDA project as one guarded EPRO archive",
    )
    _add_composite_options(project_source_export)
    _add_export_safety(project_source_export)
    project_source_export.add_argument("--format", choices=("epro",), default="epro")
    project_source_export.add_argument("--output", type=Path)
    project_source_export.set_defaults(handler=_schematic_project_source_export)

    source_render = subparsers.add_parser(
        "schematic-source-render",
        help="disabled by policy: EPRO-derived visuals are not admitted; use official PNG/PDF export",
    )
    source_render.add_argument("--source", required=True, type=Path)
    source_render.add_argument("--document-uuid", required=True)
    source_render.add_argument("--evidence-dir", type=Path, default=Path("evidence/gateway"))
    source_render.add_argument("--margin", type=float, default=20.0)
    source_render.add_argument("--render-png", action="store_true")
    source_render.add_argument("--render-pdf", action="store_true")
    source_render.add_argument("--svg-output", type=Path)
    source_render.add_argument("--png-output", type=Path)
    source_render.add_argument("--pdf-output", type=Path)
    source_render.add_argument("--node-executable", type=Path)
    source_render.add_argument("--node-path", type=Path)
    source_render.add_argument("--conversion-timeout", type=float, default=45.0)
    source_render.set_defaults(handler=_schematic_source_render)

    project_source_render = subparsers.add_parser(
        "schematic-project-source-render",
        help="disabled by policy: EPRO all-page image rendering is not admitted",
    )
    project_source_render.add_argument("--source", required=True, type=Path)
    project_source_render.add_argument("--evidence-dir", type=Path, default=Path("evidence/gateway"))
    project_source_render.add_argument("--output-dir", required=True, type=Path)
    project_source_render.add_argument("--margin", type=float, default=20.0)
    project_source_render.add_argument("--node-executable", type=Path)
    project_source_render.add_argument("--node-path", type=Path)
    project_source_render.add_argument("--conversion-timeout", type=float, default=45.0)
    project_source_render.set_defaults(handler=_schematic_project_source_render)

    schematic_drc = subparsers.add_parser(
        "schematic-drc",
        help="run strict headless schematic DRC and export a JSON report",
    )
    _add_composite_options(schematic_drc)
    _add_export_safety(schematic_drc)
    schematic_drc.add_argument("--output", type=Path)
    schematic_drc.set_defaults(handler=_schematic_drc)

    evidence_bundle = subparsers.add_parser(
        "schematic-evidence-bundle",
        help="serially export PDF, BOM, netlist, EPRO, and DRC evidence",
    )
    _add_composite_options(evidence_bundle)
    _add_export_safety(evidence_bundle)
    evidence_bundle.add_argument("--required-ref", action="append", default=[])
    evidence_bundle.add_argument("--forbidden-ref", action="append", default=[])
    evidence_bundle.set_defaults(handler=_schematic_evidence_bundle)

    evidence_archive = subparsers.add_parser(
        "evidence-archive",
        help="create a no-overwrite ZIP with an internal SHA-256 evidence manifest",
    )
    evidence_archive.add_argument("--source-dir", required=True, type=Path)
    evidence_archive.add_argument("--output", required=True, type=Path)
    evidence_archive.set_defaults(handler=_evidence_archive)

    pcb_report = subparsers.add_parser(
        "pcb-report",
        help="capture the active PCB and generate a read-only design report",
    )
    _add_composite_options(pcb_report)
    pcb_report.add_argument("--output", type=Path, default=Path("artifacts/pcb-design-report.json"))
    pcb_report.set_defaults(handler=_pcb_report)

    pcb_dfm = subparsers.add_parser(
        "pcb-dfm-report",
        help="run the source-pinned official JLC 18-check PCB DFM adapter",
    )
    _add_composite_options(pcb_dfm)
    _add_export_safety(pcb_dfm)
    pcb_dfm.add_argument("--material", choices=SUPPORTED_MATERIALS, default="FR4")
    pcb_dfm.add_argument("--thickness-mm", type=float, default=1.6)
    pcb_dfm.add_argument("--output", type=Path)
    pcb_dfm.set_defaults(handler=_pcb_dfm_report)

    pcb_svg = subparsers.add_parser(
        "pcb-manufacturing-svg-export",
        help="export source-pinned official layered manufacturing SVG ZIP",
    )
    _add_composite_options(pcb_svg)
    _add_export_safety(pcb_svg)
    pcb_svg.add_argument("--output", type=Path)
    pcb_svg.set_defaults(handler=_pcb_manufacturing_svg_export)

    pcb_gencad = subparsers.add_parser(
        "pcb-gencad-export",
        help="export source-pinned official GenCAD 1.4",
    )
    _add_composite_options(pcb_gencad)
    _add_export_safety(pcb_gencad)
    pcb_gencad.add_argument("--output", type=Path)
    pcb_gencad.set_defaults(handler=_pcb_gencad_export)

    device_match = subparsers.add_parser(
        "device-match-dry-run",
        help="search and score official device candidates without binding or saving",
    )
    _add_composite_options(device_match)
    device_match.add_argument("--designator", action="append", default=[])
    device_match.add_argument("--max-components", type=int, default=25)
    device_match.add_argument("--max-candidates", type=int, default=5)
    device_match.add_argument("--output", type=Path)
    device_match.set_defaults(handler=_device_match_dry_run)

    bom_diff = subparsers.add_parser("bom-diff", help="normalize and compare two BOM files")
    bom_diff.add_argument("--old", required=True, type=Path)
    bom_diff.add_argument("--new", required=True, type=Path)
    bom_diff.add_argument("--output", type=Path, default=Path("artifacts/bom-diff.json"))
    bom_diff.set_defaults(handler=_bom_diff)

    ibom = subparsers.add_parser(
        "ibom-export",
        help="export a self-contained assembly-lite HTML BOM from the active PCB",
    )
    _add_composite_options(ibom)
    ibom.add_argument("--output", type=Path, default=Path("artifacts/interactive-bom.html"))
    ibom.set_defaults(handler=_ibom_export)

    start = subparsers.add_parser("start-bridge", help="start the official bridge script in background")
    start.add_argument("--script", type=Path, default=_default_bridge_script())
    start.add_argument("--log", type=Path, default=Path(".runtime/easyeda-bridge.log"))
    start.add_argument("--metadata", type=Path, default=Path(".runtime/easyeda-bridge.json"))
    start.set_defaults(handler=_start_bridge)
    return parser


def _add_manifest(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--manifest", type=Path, default=_default_manifest())


def _configure_stdio_utf8() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8", errors="backslashreplace")


def _add_bridge_url(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--bridge-url", help="verified localhost bridge URL; omitted means auto-discover")


def _add_composite_options(parser: argparse.ArgumentParser) -> None:
    _add_manifest(parser)
    _add_bridge_url(parser)
    parser.add_argument("--window-id")
    parser.add_argument("--project-uuid", help="optional expected project UUID guard")
    parser.add_argument("--document-uuid", help="optional expected document UUID guard")
    parser.add_argument(
        "--allow-window-rebind",
        action="store_true",
        help="after a bridge restart, rebind a stale window only when exactly one window is connected and exact project/document UUID guards are supplied",
    )
    parser.add_argument("--evidence-dir", type=Path, default=Path("evidence/gateway"))


def _add_export_safety(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--safety-state",
        type=Path,
        default=Path(".easyeda-hardware-workbench/export-safety.json"),
        help="persistent single-flight circuit-breaker state shared by all exports",
    )


def _identity(args: argparse.Namespace) -> dict[str, Any]:
    registry = ApiRegistry.from_file(args.manifest)
    return {
        "success": True,
        "manifest": str(args.manifest.resolve()),
        "identity": registry.identity,
        "executableMethodCount": registry.method_count,
    }


def _validate_plan(args: argparse.Namespace) -> dict[str, Any]:
    report = ApiRegistry.from_file(args.manifest).validate_plan(load_json(args.plan))
    result = report.as_dict()
    result["success"] = report.valid
    return result


def _digest_plan(args: argparse.Namespace) -> dict[str, Any]:
    plan = load_json(args.plan)
    digest = plan_digest(plan)
    if args.write:
        plan["planDigest"] = digest
        args.plan.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"success": True, "planDigest": digest, "written": bool(args.write)}


def _discover(_: argparse.Namespace) -> dict[str, Any]:
    client = discover_bridge()
    return {"success": True, "bridgeUrl": client.base_url, "health": client.health()}


def _windows(args: argparse.Namespace) -> dict[str, Any]:
    client = _client(args.bridge_url)
    return {"success": True, "bridgeUrl": client.base_url, **client.windows()}


def _select(args: argparse.Namespace) -> dict[str, Any]:
    client = _client(args.bridge_url)
    return {"success": True, "bridgeUrl": client.base_url, **client.select_window(args.window_id)}


def _probe(args: argparse.Namespace) -> dict[str, Any]:
    registry = ApiRegistry.from_file(args.manifest)
    client = _client(args.bridge_url)
    bridge_runtime = _load_optional_json(args.bridge_metadata)
    plan = {
        "schemaVersion": "easyeda.hardware-lifecycle.api-plan.v1",
        "planId": "read-current-context",
        "risk": "READ",
        "registry": registry.identity,
        "identity": {
            "projectUuid": None,
            "documentUuid": None,
            "documentType": None,
            "capturedAt": _utc_now(),
            "bridgeService": "easyeda-bridge",
            "windowId": args.window_id,
            "gatewayVersion": GATEWAY_VERSION,
            "bridgeScriptSha256": bridge_runtime.get("scriptSha256") if bridge_runtime else None,
        },
        "calls": [
            {
                "methodId": "DMT_Project.getCurrentProjectInfo#1",
                "effect": "READ",
                "purpose": "Capture current project identity",
                "args": [],
                "resultKey": "project",
                "pick": ["uuid", "friendlyName", "name", "teamUuid"],
            },
            {
                "methodId": "DMT_SelectControl.getCurrentDocumentInfo#1",
                "effect": "READ",
                "purpose": "Capture current document identity",
                "args": [],
                "resultKey": "document",
                "pick": ["documentType", "uuid", "tabId", "parentProjectUuid"],
            },
        ],
        "save": False,
    }
    plan["planDigest"] = plan_digest(plan)
    result = BridgeExecutor(registry, client, bridge_runtime=bridge_runtime).execute(plan, args.evidence_dir)
    return {"success": True, **result.as_dict()}


def _execute_plan(args: argparse.Namespace) -> dict[str, Any]:
    registry = ApiRegistry.from_file(args.manifest)
    client = _client(args.bridge_url)
    authorization = load_json(args.authorization) if args.authorization else None
    acceptance = load_json(args.acceptance) if args.acceptance else None
    bridge_runtime = _load_optional_json(args.bridge_metadata)
    result = BridgeExecutor(registry, client, bridge_runtime=bridge_runtime).execute(
        load_json(args.plan),
        args.evidence_dir,
        authorization=authorization,
        acceptance=acceptance,
    )
    return {"success": True, **result.as_dict()}


def _schematic_snapshot(args: argparse.Namespace) -> dict[str, Any]:
    executor = _composite_executor(args)
    result = executor.execute(
        "schematic.snapshot.v1",
        args.evidence_dir,
        identity=_expected_identity(args),
        window_id=args.window_id,
        postprocess=analyze_schematic_snapshot,
        allow_window_rebind=args.allow_window_rebind,
    )
    _atomic_write_json(args.output, result.derived)
    return _composite_summary(result, output=args.output, summary=result.derived["statistics"])


def _schematic_page_navigation(
    args: argparse.Namespace,
    action: str,
    target_page_uuid: str | None = None,
) -> dict[str, Any]:
    adapter = EasyedaPageNavigator(
        ApiRegistry.from_file(args.manifest),
        _client(args.bridge_url),
    )
    result = adapter.execute(
        SchematicPageNavigationSpec(action=action, target_page_uuid=target_page_uuid),
        args.evidence_dir,
        identity=_expected_identity(args),
        window_id=args.window_id,
        allow_window_rebind=args.allow_window_rebind,
    )
    return {"success": True, **result.as_dict()}


def _schematic_pages(args: argparse.Namespace) -> dict[str, Any]:
    return _schematic_page_navigation(args, "list")


def _schematic_page_activate(args: argparse.Namespace) -> dict[str, Any]:
    return _schematic_page_navigation(args, "activate", args.page_uuid)


def _schematic_page_traverse(args: argparse.Namespace) -> dict[str, Any]:
    return _schematic_page_navigation(args, "traverse")


def _board_document_navigation(
    args: argparse.Namespace,
    action: str,
    target_document_uuid: str | None = None,
    target_document_type: int | None = None,
) -> dict[str, Any]:
    adapter = EasyedaBoardDocumentNavigator(
        ApiRegistry.from_file(args.manifest),
        _client(args.bridge_url),
    )
    result = adapter.execute(
        BoardDocumentNavigationSpec(
            action=action,
            target_document_uuid=target_document_uuid,
            target_document_type=target_document_type,
        ),
        args.evidence_dir,
        identity=_expected_identity(args),
        window_id=args.window_id,
        allow_window_rebind=args.allow_window_rebind,
    )
    return {"success": True, **result.as_dict()}


def _board_documents(args: argparse.Namespace) -> dict[str, Any]:
    return _board_document_navigation(args, "list")


def _board_document_activate(args: argparse.Namespace) -> dict[str, Any]:
    return _board_document_navigation(
        args,
        "activate",
        args.target_uuid,
        args.target_document_type,
    )


def _schematic_export(args: argparse.Namespace) -> dict[str, Any]:
    adapter = EasyedaExportAdapter(
        ApiRegistry.from_file(args.manifest),
        _client(args.bridge_url),
    )
    result = adapter.execute(
        SchematicExportSpec(
            file_type=args.format,
            scope=args.scope,
            theme=args.theme,
            line_width=args.line_width,
        ),
        args.evidence_dir,
        identity=_expected_identity(args),
        window_id=args.window_id,
        output_path=args.output,
        safety_state_path=args.safety_state,
        allow_window_rebind=args.allow_window_rebind,
    )
    return {"success": True, **result.as_dict()}


def _schematic_native_png_normalize(args: argparse.Namespace) -> dict[str, Any]:
    result = normalize_existing_official_png_bundle(
        source=args.source,
        source_envelope_path=args.source_envelope,
        identity_before=load_json(args.identity_before),
        identity_after=load_json(args.identity_after),
        evidence_root=args.evidence_dir,
        output_path=args.output,
    )
    return {"success": True, **result}


def _schematic_native_pdf_render(args: argparse.Namespace) -> dict[str, Any]:
    result = render_existing_official_pdf(
        source_execution=load_json(args.source_execution),
        identity_before=load_json(args.identity_before),
        identity_after=load_json(args.identity_after),
        evidence_root=args.evidence_dir,
        output_path=args.output,
        pdftoppm_path=args.pdftoppm,
        max_long_edge=args.max_long_edge,
        timeout_seconds=args.render_timeout,
    )
    return {"success": True, **result}


def _export_safety_status(args: argparse.Namespace) -> dict[str, Any]:
    return {"success": True, **ExportSafetyController(args.safety_state).status()}


def _export_safety_reset(args: argparse.Namespace) -> dict[str, Any]:
    return {"success": True, **ExportSafetyController(args.safety_state).reset(args.reason)}


def _formal_export(args: argparse.Namespace, kind: str, variant: str) -> dict[str, Any]:
    adapter = EasyedaFormalExportAdapter(
        ApiRegistry.from_file(args.manifest),
        _client(args.bridge_url),
    )
    result = adapter.execute(
        FormalExportSpec(kind, variant),
        args.evidence_dir,
        identity=_expected_identity(args),
        window_id=args.window_id,
        output_path=args.output,
        safety_state_path=args.safety_state,
        allow_window_rebind=args.allow_window_rebind,
    )
    return {"success": True, **result.as_dict()}


def _schematic_bom_export(args: argparse.Namespace) -> dict[str, Any]:
    return _formal_export(args, "bom", args.format)


def _schematic_netlist_export(args: argparse.Namespace) -> dict[str, Any]:
    return _formal_export(args, "netlist", args.format)


def _schematic_source_export(args: argparse.Namespace) -> dict[str, Any]:
    return _formal_export(args, "source", args.format)


def _schematic_project_source_export(args: argparse.Namespace) -> dict[str, Any]:
    return _formal_export(args, "project-source", args.format)


def _schematic_source_render(args: argparse.Namespace) -> dict[str, Any]:
    refuse_epro_visual_render("schematic-source-render")
    result = OfflineSourceRenderAdapter().execute(
        SourceRenderSpec(
            document_uuid=args.document_uuid,
            margin=args.margin,
            render_png=args.render_png,
            render_pdf=args.render_pdf,
        ),
        args.source,
        args.evidence_dir,
        svg_output=args.svg_output,
        png_output=args.png_output,
        pdf_output=args.pdf_output,
        node_executable=args.node_executable,
        node_path=args.node_path,
        conversion_timeout=args.conversion_timeout,
    )
    return {"success": True, **result.as_dict()}


def _schematic_project_source_render(args: argparse.Namespace) -> dict[str, Any]:
    refuse_epro_visual_render("schematic-project-source-render")
    result = OfflineProjectSourceRenderAdapter().execute(
        args.source,
        args.evidence_dir,
        args.output_dir,
        margin=args.margin,
        node_executable=args.node_executable,
        node_path=args.node_path,
        conversion_timeout=args.conversion_timeout,
    )
    return {"success": True, **result.as_dict()}


def _schematic_drc(args: argparse.Namespace) -> dict[str, Any]:
    result = EasyedaDrcAdapter(
        ApiRegistry.from_file(args.manifest),
        _client(args.bridge_url),
    ).execute(
        args.evidence_dir,
        identity=_expected_identity(args),
        window_id=args.window_id,
        output_path=args.output,
        safety_state_path=args.safety_state,
        allow_window_rebind=args.allow_window_rebind,
    )
    return {"success": True, **result.as_dict()}


def _schematic_evidence_bundle(args: argparse.Namespace) -> dict[str, Any]:
    registry = ApiRegistry.from_file(args.manifest)
    client = _client(args.bridge_url)
    return EasyedaEvidenceBundleAdapter(
        EasyedaExportAdapter(registry, client),
        EasyedaFormalExportAdapter(registry, client),
        EasyedaDrcAdapter(registry, client),
    ).execute(
        args.evidence_dir,
        identity=_expected_identity(args),
        window_id=args.window_id,
        safety_state_path=args.safety_state,
        required_refs=args.required_ref,
        forbidden_refs=args.forbidden_ref,
        allow_window_rebind=args.allow_window_rebind,
    )


def _evidence_archive(args: argparse.Namespace) -> dict[str, Any]:
    return create_evidence_archive(args.source_dir, args.output)


def _pcb_report(args: argparse.Namespace) -> dict[str, Any]:
    executor = _composite_executor(args)
    result = executor.execute(
        "pcb.snapshot.v1",
        args.evidence_dir,
        identity=_expected_identity(args),
        window_id=args.window_id,
        postprocess=build_pcb_report,
        allow_window_rebind=args.allow_window_rebind,
    )
    _atomic_write_json(args.output, result.derived)
    return _composite_summary(result, output=args.output, summary=result.derived["statistics"])


def _official_plugin_export(args: argparse.Namespace, spec: OfficialPluginSpec) -> dict[str, Any]:
    result = EasyedaOfficialPluginAdapter(
        ApiRegistry.from_file(args.manifest),
        _client(args.bridge_url),
    ).export(
        spec,
        args.evidence_dir,
        output_path=args.output,
        identity=_expected_identity(args),
        window_id=args.window_id,
        safety_state_path=args.safety_state,
        allow_window_rebind=args.allow_window_rebind,
    )
    return {"success": True, **result.as_dict()}


def _pcb_dfm_report(args: argparse.Namespace) -> dict[str, Any]:
    return _official_plugin_export(
        args,
        OfficialPluginSpec("dfm", material=args.material, thickness_mm=args.thickness_mm),
    )


def _pcb_manufacturing_svg_export(args: argparse.Namespace) -> dict[str, Any]:
    return _official_plugin_export(args, OfficialPluginSpec("manufacturing-svg"))


def _pcb_gencad_export(args: argparse.Namespace) -> dict[str, Any]:
    return _official_plugin_export(args, OfficialPluginSpec("gencad"))


def _device_match_dry_run(args: argparse.Namespace) -> dict[str, Any]:
    result = EasyedaDeviceMatchDryRunAdapter(
        ApiRegistry.from_file(args.manifest),
        _client(args.bridge_url),
    ).run(
        DeviceMatchSpec(
            designators=tuple(args.designator),
            max_components=args.max_components,
            max_candidates=args.max_candidates,
        ),
        args.evidence_dir,
        output_path=args.output,
        identity=_expected_identity(args),
        window_id=args.window_id,
        allow_window_rebind=args.allow_window_rebind,
    )
    return {"success": True, **result.as_dict()}


def _bom_diff(args: argparse.Namespace) -> dict[str, Any]:
    old_bom = load_bom(args.old)
    new_bom = load_bom(args.new)
    result = compare_boms(old_bom, new_bom)
    _atomic_write_json(args.output, result)
    return {
        "success": True,
        "schemaVersion": result["schemaVersion"],
        "summary": result["summary"],
        "duplicateMappings": {
            "old": old_bom["duplicateMappings"],
            "new": new_bom["duplicateMappings"],
        },
        "output": str(args.output.resolve()),
    }


def _ibom_export(args: argparse.Namespace) -> dict[str, Any]:
    executor = _composite_executor(args)

    def derive(payload: dict[str, Any]) -> dict[str, Any]:
        project = dict(payload.get("project") or {})
        project["documentUuid"] = (payload.get("document") or {}).get("uuid")
        return build_ibom_model(payload, project=project)

    result = executor.execute(
        "pcb.snapshot.v1",
        args.evidence_dir,
        identity=_expected_identity(args),
        window_id=args.window_id,
        postprocess=derive,
        allow_window_rebind=args.allow_window_rebind,
    )
    output = write_ibom_html(args.output, result.derived)
    return _composite_summary(result, output=output, summary=result.derived["statistics"])


def _composite_executor(args: argparse.Namespace) -> CompositeReadExecutor:
    return CompositeReadExecutor(ApiRegistry.from_file(args.manifest), _client(args.bridge_url))


def _expected_identity(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "projectUuid": args.project_uuid,
        "documentUuid": args.document_uuid,
        "windowId": args.window_id,
    }


def _composite_summary(result: Any, *, output: Path, summary: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "success": True,
        "schemaVersion": "easyeda.gateway.read-artifact.v1",
        "templateId": result.template_id,
        "templateDigest": result.template_digest,
        "bridgeUrl": result.bridge_url,
        "windowId": result.window_id,
        "identity": result.identity,
        "summary": dict(summary),
        "output": str(Path(output).resolve()),
        "evidencePath": str(result.evidence_path),
    }


def _start_bridge(args: argparse.Namespace) -> dict[str, Any]:
    try:
        existing = discover_bridge(timeout=0.25)
    except BridgeError:
        existing = None
    if existing is not None:
        metadata = _load_optional_json(args.metadata)
        metadata_verified = bool(
            metadata
            and metadata.get("schemaVersion") == "easyeda.gateway.bridge-runtime.v1"
            and metadata.get("bridgeUrl") == existing.base_url
            and metadata.get("service") == "easyeda-bridge"
        )
        return {
            "success": True,
            "alreadyRunning": True,
            "bridgeUrl": existing.base_url,
            "metadataVerified": metadata_verified,
            "metadata": str(args.metadata.resolve()) if metadata_verified else None,
        }
    script = args.script.resolve()
    if not script.is_file():
        raise ValueError(f"Official bridge script not found: {script}")
    package_root = script.parent.parent
    if not (package_root / "node_modules" / "ws").exists():
        raise ValueError(
            f"Official bridge dependency 'ws' is not installed under {package_root}; "
            "use the installed easyeda-api skill or run npm install in a writable copy",
        )
    node = shutil.which("node")
    if not node:
        raise ValueError("Node.js is not available on PATH")
    args.log.parent.mkdir(parents=True, exist_ok=True)
    popen_args = _bridge_popen_options()
    with args.log.open("ab") as log_handle:
        process = subprocess.Popen(
            [node, str(script)],
            cwd=package_root,
            stdin=subprocess.DEVNULL,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            **popen_args,
        )
    deadline = time.monotonic() + 8.0
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise ValueError(f"Official bridge exited with code {process.returncode}; inspect {args.log}")
        try:
            client = discover_bridge(timeout=0.25)
            metadata = {
                "schemaVersion": "easyeda.gateway.bridge-runtime.v1",
                "service": "easyeda-bridge",
                "bridgeUrl": client.base_url,
                "gatewayVersion": GATEWAY_VERSION,
                "pid": process.pid,
                "scriptPath": str(script),
                "scriptSha256": _sha256_file(script),
                "startedAt": _utc_now(),
            }
            _atomic_write_json(args.metadata, metadata)
            return {
                "success": True,
                "alreadyRunning": False,
                "pid": process.pid,
                "bridgeUrl": client.base_url,
                "log": str(args.log.resolve()),
                "metadata": str(args.metadata.resolve()),
                "scriptSha256": metadata["scriptSha256"],
            }
        except BridgeError:
            time.sleep(0.25)
    raise ValueError(f"Official bridge did not become ready; inspect {args.log}")


def _bridge_popen_options(platform_name: str | None = None) -> dict[str, Any]:
    platform_name = os.name if platform_name is None else platform_name
    if platform_name == "nt":
        return {
            "creationflags": getattr(subprocess, "DETACHED_PROCESS", 0)
            | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
            "close_fds": True,
        }
    return {"start_new_session": True}


def _client(base_url: str | None) -> BridgeClient:
    client = BridgeClient(base_url) if base_url else discover_bridge()
    client.health()
    return client


def _default_manifest() -> Path:
    configured = os.environ.get("EASYEDA_API_MANIFEST")
    if configured:
        return Path(configured)
    workbench_manifest = _find_workbench_path(Path("materials/manifests/api-manifest.json"))
    if workbench_manifest.is_file():
        return workbench_manifest
    packaged_manifest = Path(__file__).resolve().with_name("api-manifest.json")
    if packaged_manifest.is_file():
        return packaged_manifest
    return workbench_manifest


def _default_bridge_script() -> Path:
    configured = os.environ.get("EASYEDA_BRIDGE_SCRIPT")
    if configured:
        return Path(configured)
    home = Path.home()
    installed_candidates = [
        home / ".codex" / "skills" / "easyeda-api-skill" / "scripts" / "bridge-server.mjs",
        home / ".agents" / "skills" / "easyeda-api" / "scripts" / "bridge-server.mjs",
        home / ".config" / "opencode" / "skills" / "easyeda-api" / "scripts" / "bridge-server.mjs",
    ]
    for candidate in installed_candidates:
        if candidate.is_file() and (candidate.parent.parent / "node_modules" / "ws").exists():
            return candidate
    return _find_workbench_path(Path("materials/sources/core/easyeda-api-skill/scripts/bridge-server.mjs"))


def _find_workbench_path(relative: Path) -> Path:
    candidates = [Path.cwd() / relative]
    candidates.extend(parent / relative for parent in Path(__file__).resolve().parents)
    for candidate in candidates:
        if candidate.exists():
            return candidate.resolve()
    return candidates[0]


def _load_optional_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    return load_json(path)


def _sha256_file(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _print_json(value: Any, stream: Any = sys.stdout) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, default=str), file=stream)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


if __name__ == "__main__":
    raise SystemExit(main())
