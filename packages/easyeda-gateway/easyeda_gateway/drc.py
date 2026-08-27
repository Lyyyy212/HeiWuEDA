"""Strict headless schematic DRC through the official EasyEDA bridge."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
from typing import Any, Mapping

from .artifact_io import (
    atomic_write_json,
    create_evidence_directory,
    identity_subset,
    publish_copy_no_overwrite,
    sha256_file,
    sha256_json,
    utc_now,
)
from .client import BridgeClient
from .contract import ApiRegistry, canonical_json
from .errors import BridgeError, ContractError
from .export_safety import ExportSafetyController, default_safety_state_path
from .version import GATEWAY_VERSION
from .window_guard import resolve_window


DRC_RESULT_SCHEMA = "easyeda.gateway.schematic-drc-result.v1"
DRC_REPORT_SCHEMA = "easyeda.gateway.schematic-drc-report.v1"
DRC_EVIDENCE_SCHEMA = "easyeda.gateway.schematic-drc-evidence.v1"
DRC_ADAPTER_VERSION = "1.0.0"
METHOD_IDS = (
    "DMT_Project.getCurrentProjectInfo#1",
    "DMT_SelectControl.getCurrentDocumentInfo#1",
    "SCH_Drc.check#2",
)


@dataclass(frozen=True)
class SchematicDrcResult:
    bridge_url: str
    window_id: str
    identity: dict[str, Any]
    report: dict[str, Any]
    report_path: Path
    evidence_path: Path
    published_output: Path | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "schemaVersion": "easyeda.gateway.schematic-drc-execution.v1",
            "adapterVersion": DRC_ADAPTER_VERSION,
            "bridgeUrl": self.bridge_url,
            "windowId": self.window_id,
            "identity": self.identity,
            "report": self.report,
            "reportPath": str(self.report_path),
            "publishedOutput": str(self.published_output) if self.published_output else None,
            "evidencePath": str(self.evidence_path),
        }


class EasyedaDrcAdapter:
    def __init__(self, registry: ApiRegistry, client: BridgeClient):
        self.registry = registry
        self.client = client
        for method_id in METHOD_IDS:
            descriptor = registry.resolve_method(method_id)
            if descriptor.deprecated:
                raise ContractError(f"DRC adapter references deprecated method: {method_id}")

    def build_code(self, identity: Mapping[str, Any] | None = None) -> str:
        expected = {
            "projectUuid": (identity or {}).get("projectUuid"),
            "documentUuid": (identity or {}).get("documentUuid"),
            "documentType": 1,
        }
        statements = [
            "const __readIdentity=async()=>{const project=await eda.dmt_Project.getCurrentProjectInfo();const document=await eda.dmt_SelectControl.getCurrentDocumentInfo();return {projectUuid:project?.uuid??document?.parentProjectUuid??null,documentUuid:document?.uuid??null,documentType:document?.documentType??null,project,document}}",
            f"const __expected={canonical_json(expected)}",
            "const __before=await __readIdentity()",
            "for(const key of ['projectUuid','documentUuid','documentType']){if(__expected[key]!==null&&__expected[key]!==__before[key]){throw new Error(`EasyEDA identity mismatch for ${key}: expected ${String(__expected[key])}, got ${String(__before[key])}`)}}",
            "const __errors=await eda.sch_Drc.check(true,false,true)",
            "if(!Array.isArray(__errors)){throw new Error('EasyEDA strict DRC did not return a verbose error array')}",
            "const __after=await __readIdentity()",
            "for(const key of ['projectUuid','documentUuid','documentType']){if(__before[key]!==__after[key]){throw new Error(`EasyEDA identity changed during strict DRC for ${key}`)}}",
            f"return {{schemaVersion:'{DRC_RESULT_SCHEMA}',adapterVersion:'{DRC_ADAPTER_VERSION}',identityBefore:__before,identityAfter:__after,errors:__errors}}",
        ]
        code = ";".join(statements) + ";"
        if "//" in code or "/*" in code:
            raise ContractError("DRC compilation produced a JavaScript comment")
        return code

    def execute(
        self,
        evidence_root: str | Path,
        *,
        identity: Mapping[str, Any] | None = None,
        window_id: str | None = None,
        output_path: str | Path | None = None,
        safety_state_path: str | Path | None = None,
        allow_window_rebind: bool = False,
    ) -> SchematicDrcResult:
        published = _validate_output(output_path)
        evidence_directory = create_evidence_directory(evidence_root, "schematic-drc")
        report_path = evidence_directory / "schematic-drc.json"
        safety_path = Path(safety_state_path).resolve() if safety_state_path else default_safety_state_path(evidence_root)
        started_at = utc_now()
        code = self.build_code(identity)
        request = {
            "schemaVersion": "easyeda.gateway.schematic-drc-request.v1",
            "adapterVersion": DRC_ADAPTER_VERSION,
            "registry": self.registry.identity,
            "expectedIdentity": dict(identity or {}),
            "capabilityId": "drc.strict",
            "safetyStatePath": str(safety_path),
            "generatedCodeSha256": hashlib.sha256(code.encode("utf-8")).hexdigest(),
            "methods": list(METHOD_IDS),
            "strict": True,
            "userInterface": False,
            "includeVerboseError": True,
        }
        atomic_write_json(evidence_directory / "request.json", request)
        try:
            health_before = self.client.health()
            windows_before = self.client.windows()
            window_resolution = resolve_window(
                windows_before,
                requested_window_id=window_id,
                identity=identity,
                allow_rebind=allow_window_rebind,
            )
            target_window = window_resolution.resolved_window_id
            safety = ExportSafetyController(safety_path)
            safety.acquire("drc.strict", self.client, str(target_window))
            try:
                response = self.client.execute_code(code, str(target_window))
                health_after = self.client.health()
            except Exception as exc:
                safety.finish(success=False, error=exc)
                raise
            else:
                safety.finish(success=True)
            result = response.get("result")
            if not isinstance(result, Mapping) or result.get("schemaVersion") != DRC_RESULT_SCHEMA:
                raise BridgeError("Strict DRC returned an invalid result envelope")
            if result.get("adapterVersion") != DRC_ADAPTER_VERSION:
                raise BridgeError("Strict DRC adapter identity mismatch")
            before = identity_subset(result.get("identityBefore"))
            after = identity_subset(result.get("identityAfter"))
            if before != after or before.get("documentType") != 1:
                raise BridgeError("EasyEDA identity changed or is not a schematic during DRC")
            errors = result.get("errors")
            if not isinstance(errors, list):
                raise BridgeError("Strict DRC errors must be an array")
            report = build_drc_report(errors, before)
            atomic_write_json(report_path, report)
            published_output = None
            if published is not None:
                publish_copy_no_overwrite(report_path, published)
                published_output = published
            result_record = {
                "bridgeResponse": response,
                "bridgeResponseSha256": sha256_json(response),
                "report": report,
                "publishedOutput": str(published_output) if published_output else None,
            }
            atomic_write_json(evidence_directory / "result.json", result_record)
            envelope = {
                "schemaVersion": DRC_EVIDENCE_SCHEMA,
                "status": "PASS",
                "risk": "READ_WITH_LOCAL_ARTIFACT",
                "startedAt": started_at,
                "finishedAt": utc_now(),
                "gatewayVersion": GATEWAY_VERSION,
                "adapterVersion": DRC_ADAPTER_VERSION,
                "registry": self.registry.identity,
                "identity": before,
                "bridge": {
                    "service": health_before.get("service"),
                    "url": self.client.base_url,
                    "windowId": str(target_window),
                    "healthBefore": health_before,
                    "healthAfter": health_after,
                    "windowsBefore": windows_before,
                    "windowResolution": window_resolution.as_dict(),
                },
                "safety": {
                    "capabilityId": "drc.strict",
                    "statePath": str(safety_path),
                    "automaticRetry": False,
                },
                "files": {
                    "request.json": sha256_file(evidence_directory / "request.json"),
                    "result.json": sha256_file(evidence_directory / "result.json"),
                    report_path.name: sha256_file(report_path),
                },
            }
            atomic_write_json(evidence_directory / "envelope.json", envelope)
            return SchematicDrcResult(
                bridge_url=self.client.base_url,
                window_id=str(target_window),
                identity=before,
                report=report,
                report_path=report_path,
                evidence_path=evidence_directory / "envelope.json",
                published_output=published_output,
            )
        except Exception as exc:
            try:
                _record_failure(evidence_directory, self.registry.identity, identity, started_at, exc)
            except OSError:
                pass
            raise


def build_drc_report(errors: list[Any], identity: Mapping[str, Any]) -> dict[str, Any]:
    counts = {"error": 0, "warning": 0, "other": 0}
    detailed_entry_count = 0
    summary_only_entry_count = 0
    for item in errors:
        item_type = str(item.get("type", "") if isinstance(item, Mapping) else "").strip().lower()
        raw_count = item.get("count") if isinstance(item, Mapping) else None
        count = raw_count if isinstance(raw_count, int) and not isinstance(raw_count, bool) and raw_count >= 0 else 1
        if isinstance(item, Mapping) and any(
            key in item for key in ("rule", "net", "primitives")
        ):
            detailed_entry_count += 1
        else:
            summary_only_entry_count += 1
        if item_type in {"error", "fatal", "fatalerror"}:
            counts["error"] += count
        elif item_type in {"warn", "warning"}:
            counts["warning"] += count
        else:
            counts["other"] += count
    status = "BLOCKED_BY_DRC" if counts["error"] else ("REVIEW_REQUIRED" if errors else "PASS")
    if not errors:
        detail_availability = "NOT_APPLICABLE"
    elif detailed_entry_count and summary_only_entry_count:
        detail_availability = "PARTIAL"
    elif detailed_entry_count:
        detail_availability = "FULL"
    else:
        detail_availability = "SUMMARY_ONLY"
    limitations = []
    if detail_availability in {"PARTIAL", "SUMMARY_ONLY"}:
        limitations.append(
            "Official EasyEDA DRC returned aggregate entries without complete rule/net/primitive details"
        )
    return {
        "schemaVersion": DRC_REPORT_SCHEMA,
        "generatedAt": utc_now(),
        "readOnly": True,
        "status": status,
        "strict": True,
        "userInterface": False,
        "includeVerboseError": True,
        "passed": not errors,
        "summaryEntryCount": len(errors),
        "issueCount": sum(counts.values()),
        "errorCount": counts["error"],
        "warningCount": counts["warning"],
        "otherCount": counts["other"],
        "detailAvailability": detail_availability,
        "detailedEntryCount": detailed_entry_count,
        "summaryOnlyEntryCount": summary_only_entry_count,
        "limitations": limitations,
        "errors": errors,
        "identity": dict(identity),
    }


def _validate_output(output_path: str | Path | None) -> Path | None:
    if output_path is None:
        return None
    target = Path(output_path).resolve()
    if target.suffix.lower() != ".json":
        raise ContractError("Published DRC report must use the .json suffix")
    if target.exists():
        raise ContractError(f"Published DRC report already exists: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    return target


def _record_failure(
    evidence_directory: Path,
    registry: dict[str, Any],
    identity: Mapping[str, Any] | None,
    started_at: str,
    error: Exception,
) -> None:
    failure = {
        "schemaVersion": "easyeda.gateway.schematic-drc-failure.v1",
        "status": "FAIL",
        "startedAt": started_at,
        "finishedAt": utc_now(),
        "gatewayVersion": GATEWAY_VERSION,
        "adapterVersion": DRC_ADAPTER_VERSION,
        "registry": registry,
        "expectedIdentity": dict(identity or {}),
        "error": {"type": type(error).__name__, "message": str(error)},
    }
    atomic_write_json(evidence_directory / "failure.json", failure)
    files = {
        item.name: sha256_file(item)
        for item in sorted(evidence_directory.iterdir(), key=lambda candidate: candidate.name)
        if item.is_file() and item.name != "envelope.json"
    }
    atomic_write_json(
        evidence_directory / "envelope.json",
        {
            "schemaVersion": DRC_EVIDENCE_SCHEMA,
            "status": "FAIL",
            "risk": "READ_WITH_LOCAL_ARTIFACT",
            "startedAt": started_at,
            "finishedAt": failure["finishedAt"],
            "gatewayVersion": GATEWAY_VERSION,
            "adapterVersion": DRC_ADAPTER_VERSION,
            "registry": registry,
            "expectedIdentity": dict(identity or {}),
            "error": failure["error"],
            "files": files,
        },
    )
