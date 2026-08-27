"""Serial export admission and persistent circuit breaking for EasyEDA."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

from .artifact_io import atomic_write_json, utc_now
from .client import BridgeClient
from .errors import BridgeError, BridgeTimeoutError, ContractError


CAPABILITY_SCHEMA = "easyeda.gateway.export-capabilities.v1"
SAFETY_STATE_SCHEMA = "easyeda.gateway.export-safety-state.v1"
ALLOWED_STATUS = "VERIFIED_SERIAL"
EPRO_VISUAL_POLICY_STATUS = "DISABLED_BY_POLICY"
EPRO_VISUAL_POLICY_REASON = (
    "EPRO-derived schematic images are disabled because their visual fidelity is not acceptable; "
    "use an official EasyEDA Current Schematic PNG or PDF export instead"
)


@dataclass(frozen=True)
class ExportCapability:
    capability_id: str
    artifact: str
    status: str
    ui_blocking_risk: str
    default_timeout_seconds: int
    retry_policy: str
    evidence: str
    reason: str

    @property
    def executable(self) -> bool:
        return self.status == ALLOWED_STATUS

    def as_dict(self) -> dict[str, Any]:
        return {
            "capabilityId": self.capability_id,
            "artifact": self.artifact,
            "status": self.status,
            "uiBlockingRisk": self.ui_blocking_risk,
            "defaultTimeoutSeconds": self.default_timeout_seconds,
            "retryPolicy": self.retry_policy,
            "evidence": self.evidence,
            "reason": self.reason,
            "executable": self.executable,
        }


_CAPABILITIES = (
    ExportCapability("visual.current-schematic.png", "PNG", ALLOWED_STATUS, "medium", 30, "NEVER", "live-verified-2026-08-24", "Current Schematic PNG completed with stable identity."),
    ExportCapability("visual.current-schematic.pdf", "PDF", ALLOWED_STATUS, "medium", 30, "NEVER", "legacy-and-live-verified", "Native whole-schematic PDF is the retained jlc compatibility route."),
    ExportCapability("visual.current-schematic.svg", "SVG", "DOCUMENTED_UNVERIFIED", "high", 30, "NEVER", "official-documentation-only", "Native SVG has not been verified on the installed client."),
    ExportCapability("visual.current-page.png", "PNG", "BLOCKED_KNOWN_HANG", "critical", 30, "NEVER", "live-timeout-2026-08-24", "Current Schematic Page timed out and can hold the EasyEDA page."),
    ExportCapability("visual.current-page.pdf", "PDF", "BLOCKED_KNOWN_HANG", "critical", 30, "NEVER", "same-scope-runtime-failure", "The page scope is blocked for every visual format until the client is re-qualified."),
    ExportCapability("visual.current-page.svg", "SVG", "BLOCKED_KNOWN_HANG", "critical", 30, "NEVER", "same-scope-runtime-failure", "The page scope is blocked for every visual format until the client is re-qualified."),
    ExportCapability("bom.csv", "BOM CSV", ALLOWED_STATUS, "medium", 30, "NEVER", "retained-jlc-repeated-live-evidence", "Formal UTF-16/tab CSV export is repeatedly verified by the retained jlc workflow."),
    ExportCapability("bom.xlsx", "BOM XLSX", "DOCUMENTED_UNVERIFIED", "high", 30, "NEVER", "official-documentation-only", "XLSX is documented but not qualified in the retained evidence workflow."),
    ExportCapability("netlist.jlceda", "JLCEDA Pro netlist", ALLOWED_STATUS, "medium", 30, "NEVER", "retained-jlc-repeated-live-evidence", "JLCEDA JSON netlist is the consistency-audit baseline."),
    ExportCapability("netlist.protel2", "Protel2 netlist", "DOCUMENTED_UNVERIFIED", "high", 30, "NEVER", "official-documentation-and-prior-project-evidence", "Cross-tool output is useful but not qualified for this integrated runtime."),
    ExportCapability("source.epro", "EPRO document", ALLOWED_STATUS, "medium", 30, "NEVER", "retained-jlc-live-evidence", "The retained source-rendered-PDF route captured EPRO without document mutation."),
    ExportCapability("source.epro2", "EPRO2 document", "DOCUMENTED_UNVERIFIED", "high", 30, "NEVER", "official-documentation-only", "EPRO2 is documented but not qualified in the retained workflow."),
    ExportCapability("project-source.epro", "EPRO project", ALLOWED_STATUS, "medium", 60, "NEVER", "live-verified-2026-08-24", "One guarded project EPRO call preserves the active identity and exact schematic page UUID tree."),
    ExportCapability("drc.strict", "Strict schematic DRC JSON", ALLOWED_STATUS, "high", 30, "NEVER", "retained-jlc-repeated-live-evidence", "Strict headless DRC is verified but can be slow on large schematics."),
    ExportCapability("pcb.dfm-report", "JLC official PCB DFM JSON", ALLOWED_STATUS, "high", 30, "NEVER", "live-qualified-2026-08-24", "The source-pinned 18-check adapter completed on a real PCB with stable identity and a structurally valid zero-error report."),
    ExportCapability("pcb.manufacturing-svg", "Layered manufacturing SVG ZIP", ALLOWED_STATUS, "high", 30, "NEVER", "live-qualified-2026-08-24", "The source-pinned Gerber-to-SVG adapter completed on a real PCB with 13 valid SVG entries and stable identity."),
    ExportCapability("pcb.gencad", "GenCAD 1.4", ALLOWED_STATUS, "high", 30, "NEVER", "live-qualified-2026-08-24", "The source-pinned GenCAD adapter completed on a real PCB with all required sections and stable identity."),
    ExportCapability("simulation.spice", "Simulation netlist", "NOT_IMPLEMENTED", "unknown", 30, "NEVER", "future-extension", "Add only with a simulation-stage consumer and an exact enum contract."),
    ExportCapability("pcb.fabrication", "Gerber/drill/fabrication package", "NOT_IMPLEMENTED", "unknown", 120, "NEVER", "future-pcb-stage", "Belongs to a PCB fabrication adapter and must not be inferred from schematic exports."),
    ExportCapability("pcb.assembly", "PCB BOM/CPL/assembly package", "NOT_IMPLEMENTED", "unknown", 120, "NEVER", "future-pcb-stage", "Requires a PCB-bound assembly contract and placement validation."),
)
CAPABILITIES = {item.capability_id: item for item in _CAPABILITIES}


def capability_report() -> dict[str, Any]:
    return {
        "schemaVersion": CAPABILITY_SCHEMA,
        "executionModel": "ONE_OFFICIAL_CALL_PER_BRIDGE_REQUEST",
        "concurrency": 1,
        "automaticRetry": False,
        "timeoutCancelsEasyEdaOperation": False,
        "derivedVisualPolicy": {
            "status": EPRO_VISUAL_POLICY_STATUS,
            "reason": EPRO_VISUAL_POLICY_REASON,
            "blockedCommands": [
                "schematic-source-render",
                "schematic-project-source-render",
            ],
            "admittedOfficialSources": [
                "visual.current-schematic.png",
                "visual.current-schematic.pdf",
            ],
            "eproArchiveStillAvailable": True,
        },
        "capabilities": [item.as_dict() for item in _CAPABILITIES],
    }


def refuse_epro_visual_render(command: str) -> None:
    """Reject product-facing EPRO image rendering before reading the source archive."""

    if command not in {"schematic-source-render", "schematic-project-source-render"}:
        raise ContractError(f"Unknown EPRO visual-render command: {command}")
    raise ContractError(
        f"{command} is {EPRO_VISUAL_POLICY_STATUS}: {EPRO_VISUAL_POLICY_REASON}",
    )


def default_safety_state_path(evidence_root: str | Path) -> Path:
    return Path(evidence_root).resolve().parent / "export-safety.json"


class ExportSafetyController:
    """Allow one qualified export and trip persistently when transport times out."""

    def __init__(self, state_path: str | Path):
        self.state_path = Path(state_path).resolve()
        self.lock_path = self.state_path.with_suffix(self.state_path.suffix + ".lock")
        self._active: dict[str, Any] | None = None

    def status(self) -> dict[str, Any]:
        if not self.state_path.is_file():
            return {
                "schemaVersion": SAFETY_STATE_SCHEMA,
                "status": "CLOSED",
                "statePath": str(self.state_path),
                "lockPresent": self.lock_path.exists(),
            }
        try:
            value = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ContractError(f"Cannot read export safety state {self.state_path}: {exc}") from exc
        if not isinstance(value, dict) or value.get("schemaVersion") != SAFETY_STATE_SCHEMA:
            raise ContractError(f"Invalid export safety state: {self.state_path}")
        value["statePath"] = str(self.state_path)
        value["lockPresent"] = self.lock_path.exists()
        return value

    def acquire(self, capability_id: str, client: BridgeClient, window_id: str) -> dict[str, Any]:
        capability = CAPABILITIES.get(capability_id)
        if capability is None:
            raise ContractError(f"Unknown EasyEDA export capability: {capability_id}")
        if not capability.executable:
            raise ContractError(
                f"EasyEDA export capability {capability_id} is {capability.status}: {capability.reason}",
            )
        state = self.status()
        if state.get("status") == "OPEN":
            raise BridgeError(
                "EasyEDA export circuit breaker is OPEN after a possible UI-blocking operation; "
                "recover/restart EasyEDA, then explicitly reset the breaker before another export",
            )
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        active = {
            "schemaVersion": SAFETY_STATE_SCHEMA,
            "status": "ACTIVE",
            "capabilityId": capability_id,
            "bridgeUrl": client.base_url,
            "windowId": window_id,
            "startedAt": utc_now(),
            "automaticRetry": False,
        }
        try:
            with self.lock_path.open("x", encoding="utf-8") as handle:
                json.dump(active, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
        except FileExistsError as exc:
            raise BridgeError(
                f"Another EasyEDA export is active or left an unresolved lock: {self.lock_path}",
            ) from exc
        try:
            health = client.health()
            pending = health.get("pendingRequests")
            if pending not in (0, None):
                raise BridgeError(f"Bridge already has {pending} pending EasyEDA request(s); export refused")
            atomic_write_json(self.state_path, active)
            self._active = active
            return health
        except Exception:
            self._release_lock()
            raise

    def finish(self, *, success: bool, error: Exception | None = None) -> None:
        if self._active is None:
            return
        timed_out = isinstance(error, BridgeTimeoutError)
        state = {
            **self._active,
            "status": "OPEN" if timed_out else "CLOSED",
            "finishedAt": utc_now(),
            "lastResult": "PASS" if success else "FAIL",
            "error": (
                {"type": type(error).__name__, "message": str(error)}
                if error is not None
                else None
            ),
            "recoveryRequired": timed_out,
        }
        atomic_write_json(self.state_path, state)
        self._active = None
        self._release_lock()

    def reset(self, reason: str) -> dict[str, Any]:
        if not reason.strip():
            raise ContractError("Export breaker reset requires a non-empty recovery reason")
        previous = self.status()
        if self.lock_path.exists():
            self.lock_path.unlink()
        state = {
            "schemaVersion": SAFETY_STATE_SCHEMA,
            "status": "CLOSED",
            "resetAt": utc_now(),
            "resetReason": reason.strip(),
            "previous": {
                "status": previous.get("status"),
                "capabilityId": previous.get("capabilityId"),
                "finishedAt": previous.get("finishedAt"),
                "error": previous.get("error"),
            },
        }
        atomic_write_json(self.state_path, state)
        return self.status()

    def _release_lock(self) -> None:
        try:
            self.lock_path.unlink(missing_ok=True)
        except OSError:
            pass
