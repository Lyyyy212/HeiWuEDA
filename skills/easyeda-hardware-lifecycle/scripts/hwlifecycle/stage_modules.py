"""Deterministic validation gates for the five lifecycle stages."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .constants import BOM_WRITE_FIELDS, STAGES
from .io_utils import sha256_json


REQUIRED_ARTIFACTS: dict[str, tuple[str, ...]] = {
    "concept": ("requirements", "system-architecture", "verification-strategy"),
    "module_design": ("module-profile", "interfaces", "electrical-constraints"),
    "schematic_review": ("schematic-snapshot", "review-report", "review-actions", "release-gate"),
    "bom_selection": ("bom-requirements", "bom-candidates", "final-bom", "final-bom-digest"),
    "bom_writeback": (
        "write-plan",
        "acceptance-report",
        "fresh-write-plan",
        "apply-journal",
        "post-save-readback",
    ),
}


@dataclass(frozen=True)
class GateResult:
    stage: str
    status: str
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]
    evidence: tuple[str, ...]
    output_digest: str

    @property
    def passed(self) -> bool:
        return self.status == "passed"

    def as_dict(self) -> dict[str, Any]:
        return {
            "schemaVersion": "easyeda.hardware-lifecycle.gate-result.v1",
            "stage": self.stage,
            "status": self.status,
            "blockers": list(self.blockers),
            "warnings": list(self.warnings),
            "evidence": list(self.evidence),
            "outputDigest": self.output_digest,
        }


def _items(value: Any, key: str | None = None) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, dict) and key and isinstance(value.get(key), list):
        return value[key]
    return []


def _nonempty(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


class StageModule:
    name: str

    def validate(self, artifacts: dict[str, list[dict[str, Any]]], evidence: list[str]) -> GateResult:
        if self.name not in STAGES:
            raise ValueError(f"unknown lifecycle stage: {self.name}")
        blockers: list[str] = []
        warnings: list[str] = []
        for artifact_type in REQUIRED_ARTIFACTS[self.name]:
            if not artifacts.get(artifact_type):
                blockers.append(f"missing required artifact: {artifact_type}")
        if not blockers:
            self._validate(artifacts, blockers, warnings)
        digest_input = {
            key: [sha256_json(payload) for payload in values]
            for key, values in sorted(artifacts.items())
        }
        return GateResult(
            stage=self.name,
            status="blocked" if blockers else "passed",
            blockers=tuple(blockers),
            warnings=tuple(warnings),
            evidence=tuple(evidence),
            output_digest=sha256_json(digest_input),
        )

    def _one(self, artifacts: dict[str, list[dict[str, Any]]], artifact_type: str) -> dict[str, Any]:
        return artifacts[artifact_type][0]

    def _validate(
        self,
        artifacts: dict[str, list[dict[str, Any]]],
        blockers: list[str],
        warnings: list[str],
    ) -> None:
        raise NotImplementedError


class ConceptStage(StageModule):
    name = "concept"

    def _validate(self, artifacts, blockers, warnings) -> None:
        requirements = _items(self._one(artifacts, "requirements"), "requirements")
        if not requirements:
            blockers.append("requirements must contain at least one requirement")
        requirement_ids: set[str] = set()
        for index, requirement in enumerate(requirements):
            if not isinstance(requirement, dict):
                blockers.append(f"requirements[{index}] must be an object")
                continue
            required = ("id", "statement", "priority", "verificationMethod", "owner", "status", "source")
            missing = [field for field in required if not _nonempty(requirement.get(field))]
            acceptance = requirement.get("acceptance")
            if missing or not acceptance:
                blockers.append(f"requirement {requirement.get('id', index)} lacks measurable acceptance or ownership fields")
            if _nonempty(requirement.get("id")):
                if requirement["id"] in requirement_ids:
                    blockers.append(f"duplicate requirement ID: {requirement['id']}")
                requirement_ids.add(requirement["id"])

        architecture = self._one(artifacts, "system-architecture")
        for field in ("modules", "interfaces", "powerDomains", "alternatives"):
            if not _items(architecture.get(field)):
                blockers.append(f"system architecture requires non-empty {field}")
        unknowns = _items(architecture.get("unknowns"))
        for index, unknown in enumerate(unknowns):
            if not isinstance(unknown, dict) or not _nonempty(unknown.get("owner")) or not unknown.get("resolutionPlan"):
                blockers.append(f"architecture unknowns[{index}] requires owner and resolutionPlan")

        strategy = self._one(artifacts, "verification-strategy")
        coverage = {item.get("requirementId") for item in _items(strategy, "verifications") if isinstance(item, dict)}
        missing_coverage = sorted(requirement_ids - coverage)
        if missing_coverage:
            blockers.append("requirements missing verification coverage: " + ", ".join(missing_coverage))


class ModuleDesignStage(StageModule):
    name = "module_design"

    def _validate(self, artifacts, blockers, warnings) -> None:
        profiles = artifacts.get("module-profile", [])
        module_ids: set[str] = set()
        for index, module in enumerate(profiles):
            module_id = module.get("moduleId") if isinstance(module, dict) else None
            if not _nonempty(module_id):
                blockers.append(f"module-profile[{index}] requires moduleId")
                continue
            if module_id in module_ids:
                blockers.append(f"duplicate module ID: {module_id}")
            module_ids.add(module_id)
            for field in (
                "purpose",
                "owners",
                "inputs",
                "outputs",
                "tracedRequirementIds",
                "constraints",
                "implementationOptions",
                "verificationPlan",
                "invalidationTriggers",
            ):
                if not module.get(field):
                    blockers.append(f"module {module_id} requires {field}")
            if not module.get("calculations") and not module.get("evidence"):
                blockers.append(f"module {module_id} requires calculations or evidence")

        interfaces = _items(self._one(artifacts, "interfaces"), "interfaces")
        if not interfaces:
            blockers.append("interfaces artifact must contain at least one interface")
        for index, interface in enumerate(interfaces):
            if not isinstance(interface, dict):
                blockers.append(f"interfaces[{index}] must be an object")
                continue
            for field in ("id", "producer", "consumers", "electrical", "timing", "connectorOrNet"):
                if not interface.get(field):
                    blockers.append(f"interface {interface.get('id', index)} requires {field}")
            referenced = {interface.get("producer"), *interface.get("consumers", [])}
            unknown = sorted(item for item in referenced if item and item not in module_ids)
            if unknown:
                blockers.append(f"interface {interface.get('id', index)} references unknown modules: {', '.join(unknown)}")

        constraints = self._one(artifacts, "electrical-constraints")
        if not _items(constraints, "constraints"):
            blockers.append("electrical constraints must be explicit")


def _require_live_identity(payload: dict[str, Any], label: str, blockers: list[str]) -> None:
    identity = payload.get("sourceIdentity") or payload.get("identity")
    if not isinstance(identity, dict):
        blockers.append(f"{label} requires live source identity")
        return
    for field in ("projectUuid", "documentUuid", "documentType", "capturedAt"):
        if identity.get(field) in (None, ""):
            blockers.append(f"{label} identity requires {field}")


class SchematicReviewStage(StageModule):
    name = "schematic_review"

    def _validate(self, artifacts, blockers, warnings) -> None:
        snapshot = self._one(artifacts, "schematic-snapshot")
        _require_live_identity(snapshot, "schematic snapshot", blockers)
        if not _nonempty(snapshot.get("snapshotDigest")):
            blockers.append("schematic snapshot requires snapshotDigest")
        if not _nonempty(snapshot.get("moduleDigest")):
            blockers.append("schematic snapshot requires current moduleDigest")

        report = self._one(artifacts, "review-report")
        if report.get("snapshotDigest") != snapshot.get("snapshotDigest"):
            blockers.append("review report is not bound to the current schematic snapshot")
        findings = _items(report, "findings")
        for finding in findings:
            if not isinstance(finding, dict):
                blockers.append("review findings must be objects")
                continue
            severity = finding.get("severity")
            disposition = finding.get("disposition")
            if severity in {"P0", "P1"} and disposition not in {"resolved", "accepted"}:
                blockers.append(f"open {severity} finding: {finding.get('id', 'unknown')}")
            if severity == "P2" and not disposition:
                blockers.append(f"P2 finding lacks disposition: {finding.get('id', 'unknown')}")
            for field in ("id", "location", "evidence", "impact", "recommendation", "confidence"):
                if not finding.get(field):
                    blockers.append(f"finding {finding.get('id', 'unknown')} requires {field}")

        actions = self._one(artifacts, "review-actions")
        open_critical = [item for item in _items(actions, "actions") if isinstance(item, dict) and item.get("severity") in {"P0", "P1"} and item.get("status") != "closed"]
        if open_critical:
            blockers.append("review actions contain open P0/P1 items")
        release = self._one(artifacts, "release-gate")
        if release.get("status") != "PASSED" or release.get("snapshotDigest") != snapshot.get("snapshotDigest"):
            blockers.append("release gate must pass for the current schematic snapshot")


class BomSelectionStage(StageModule):
    name = "bom_selection"

    def _validate(self, artifacts, blockers, warnings) -> None:
        requirements = self._one(artifacts, "bom-requirements")
        if not _items(requirements, "requirements"):
            blockers.append("BOM selection requirements are missing")
        candidates = self._one(artifacts, "bom-candidates")
        if candidates.get("ambiguous") or candidates.get("unmatched"):
            blockers.append("BOM candidates contain ambiguous or unmatched rows")

        final_bom = self._one(artifacts, "final-bom")
        lines = _items(final_bom, "lines")
        if not lines:
            blockers.append("final BOM must contain lines")
        for index, line in enumerate(lines):
            label = line.get("references", [index]) if isinstance(line, dict) else [index]
            if not isinstance(line, dict):
                blockers.append(f"final BOM line {index} must be an object")
                continue
            for field in ("references", "quantity", "value", "footprint", "manufacturer", "manufacturerPart", "supplier", "supplierPart", "selectionRequirementIds", "rationale", "pageUuid"):
                if line.get(field) in (None, "", []):
                    blockers.append(f"final BOM line {label} requires {field}")
            for check in ("packageValidation", "specValidation"):
                if (line.get(check) or {}).get("status") != "PASSED":
                    blockers.append(f"final BOM line {label} requires passed {check}")
            if line.get("critical") is True and not line.get("alternates"):
                blockers.append(f"critical BOM line {label} requires an alternate")
            if not line.get("lifecycle"):
                blockers.append(f"final BOM line {label} requires lifecycle evidence")

        digest_artifact = self._one(artifacts, "final-bom-digest")
        expected = sha256_json(final_bom)
        if digest_artifact.get("sha256") != expected:
            blockers.append("final BOM digest does not match canonical final BOM")


class BomWritebackStage(StageModule):
    name = "bom_writeback"

    def _validate(self, artifacts, blockers, warnings) -> None:
        planned = self._one(artifacts, "write-plan")
        fresh = self._one(artifacts, "fresh-write-plan")
        for label, plan in (("write plan", planned), ("fresh write plan", fresh)):
            if plan.get("risk") != "PERSISTENT_WRITE" or plan.get("save") is not True:
                blockers.append(f"{label} must be a persistent save plan")
            scope = plan.get("scope") or {}
            fields = set(scope.get("allowedFields") or scope.get("fields") or [])
            if not fields or not fields.issubset(BOM_WRITE_FIELDS):
                blockers.append(f"{label} exceeds the four procurement-field boundary")
            if not scope.get("pageUuid") or not plan.get("finalBomDigest"):
                blockers.append(f"{label} requires pageUuid and finalBomDigest")
        if (planned.get("scope") or {}).get("pageUuid") != (fresh.get("scope") or {}).get("pageUuid"):
            blockers.append("fresh write plan page identity differs from accepted plan")
        if planned.get("finalBomDigest") != fresh.get("finalBomDigest"):
            blockers.append("fresh write plan final BOM digest differs from accepted plan")

        acceptance = self._one(artifacts, "acceptance-report")
        if acceptance.get("status") != "PASSED" or acceptance.get("restorationVerified") is not True or acceptance.get("protectedFieldsVerified") is not True:
            blockers.append("acceptance must pass and prove restoration/protected-field preservation")
        if acceptance.get("explicitAuthorization") is not True:
            blockers.append("exact persistent write plan lacks explicit authorization")

        journal = self._one(artifacts, "apply-journal")
        if journal.get("status") != "SUCCESS" or journal.get("saved") is not True:
            blockers.append("apply journal must prove successful save")
        readback = self._one(artifacts, "post-save-readback")
        for field in ("readbackVerified", "protectedFieldsUnchanged", "connectivityUnchanged"):
            if readback.get(field) is not True:
                blockers.append(f"post-save readback requires {field}=true")
        if readback.get("drcStatus") not in {"PASSED", "UNCHANGED"}:
            blockers.append("post-save DRC evidence is missing")
        if readback.get("exportComparison") not in {"MATCHED", "EXPECTED_FIELDS_ONLY"}:
            blockers.append("post-save export comparison is missing")


MODULES: dict[str, StageModule] = {
    module.name: module
    for module in (
        ConceptStage(),
        ModuleDesignStage(),
        SchematicReviewStage(),
        BomSelectionStage(),
        BomWritebackStage(),
    )
}


def get_stage_module(stage: str) -> StageModule:
    try:
        return MODULES[stage]
    except KeyError as exc:
        raise ValueError(f"unknown lifecycle stage: {stage}") from exc

