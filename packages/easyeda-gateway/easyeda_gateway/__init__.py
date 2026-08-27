"""Guarded API access to the official EasyEDA bridge."""

from .client import BridgeClient, BridgeDiscoveryError, discover_bridge
from .bom import compare_boms, load_bom, normalize_bom_rows
from .board_navigator import (
    BoardDocumentNavigationResult,
    BoardDocumentNavigationSpec,
    EasyedaBoardDocumentNavigator,
)
from .composite import CompositeReadExecutor, CompositeReadResult
from .consistency import EasyedaEvidenceBundleAdapter, build_consistency_report
from .contract import ApiRegistry, ValidationReport, load_json, plan_digest
from .drc import EasyedaDrcAdapter, SchematicDrcResult
from .device_match import DeviceMatchResult, DeviceMatchSpec, EasyedaDeviceMatchDryRunAdapter
from .executor import BridgeExecutor, ExecutionResult
from .export_safety import ExportSafetyController, capability_report
from .exporter import EasyedaExportAdapter, SchematicExportResult, SchematicExportSpec
from .native_pdf_visual import render_existing_official_pdf
from .formal_exporter import EasyedaFormalExportAdapter, FormalExportResult, FormalExportSpec
from .ibom import build_ibom_model, render_ibom_html, write_ibom_html
from .intelligence import analyze_netlist, analyze_schematic_snapshot, build_pcb_report
from .official_plugins import EasyedaOfficialPluginAdapter, OfficialPluginResult, OfficialPluginSpec
from .page_navigator import (
    EasyedaPageNavigator,
    SchematicPageNavigationResult,
    SchematicPageNavigationSpec,
)
from .source_render import OfflineSourceRenderAdapter, SourceRenderResult, SourceRenderSpec
from .version import GATEWAY_VERSION

__all__ = [
    "ApiRegistry",
    "BoardDocumentNavigationResult",
    "BoardDocumentNavigationSpec",
    "BridgeClient",
    "BridgeDiscoveryError",
    "BridgeExecutor",
    "CompositeReadExecutor",
    "CompositeReadResult",
    "ExecutionResult",
    "EasyedaExportAdapter",
    "render_existing_official_pdf",
    "EasyedaBoardDocumentNavigator",
    "EasyedaEvidenceBundleAdapter",
    "EasyedaFormalExportAdapter",
    "EasyedaPageNavigator",
    "EasyedaDrcAdapter",
    "EasyedaDeviceMatchDryRunAdapter",
    "EasyedaOfficialPluginAdapter",
    "ExportSafetyController",
    "GATEWAY_VERSION",
    "ValidationReport",
    "SchematicExportResult",
    "SchematicExportSpec",
    "FormalExportResult",
    "FormalExportSpec",
    "DeviceMatchResult",
    "DeviceMatchSpec",
    "OfficialPluginResult",
    "OfficialPluginSpec",
    "SchematicPageNavigationResult",
    "SchematicPageNavigationSpec",
    "OfflineSourceRenderAdapter",
    "SourceRenderResult",
    "SourceRenderSpec",
    "SchematicDrcResult",
    "analyze_netlist",
    "analyze_schematic_snapshot",
    "build_ibom_model",
    "build_pcb_report",
    "build_consistency_report",
    "capability_report",
    "compare_boms",
    "discover_bridge",
    "load_json",
    "load_bom",
    "normalize_bom_rows",
    "plan_digest",
    "render_ibom_html",
    "write_ibom_html",
]

__version__ = GATEWAY_VERSION
