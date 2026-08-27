"""Canonical editable templates for lifecycle project artifacts."""

from __future__ import annotations

from copy import deepcopy
from typing import Any


_TEMPLATES: dict[str, dict[str, dict[str, Any]]] = {
    "concept": {
        "requirements": {"schemaVersion": "easyeda.hardware-lifecycle.requirements.v1", "requirements": []},
        "system-architecture": {
            "schemaVersion": "easyeda.hardware-lifecycle.system-architecture.v1",
            "modules": [],
            "interfaces": [],
            "powerDomains": [],
            "alternatives": [],
            "unknowns": [],
        },
        "verification-strategy": {
            "schemaVersion": "easyeda.hardware-lifecycle.verification-strategy.v1",
            "verifications": [],
        },
    },
    "module_design": {
        "module-profile": {
            "schemaVersion": "easyeda.hardware-lifecycle.module-profile.v1",
            "moduleId": "",
            "purpose": "",
            "owners": [],
            "inputs": [],
            "outputs": [],
            "dependencies": [],
            "tracedRequirementIds": [],
            "constraints": {},
            "implementationOptions": [],
            "calculations": [],
            "evidence": [],
            "interfaceIdsOwned": [],
            "interfaceIdsConsumed": [],
            "failureBehavior": "",
            "safeState": "",
            "verificationPlan": [],
            "unresolvedQuestions": [],
            "invalidationTriggers": [],
        },
        "interfaces": {"schemaVersion": "easyeda.hardware-lifecycle.interfaces.v1", "interfaces": []},
        "electrical-constraints": {
            "schemaVersion": "easyeda.hardware-lifecycle.electrical-constraints.v1",
            "constraints": [],
        },
    },
    "schematic_review": {
        "schematic-snapshot": {
            "schemaVersion": "easyeda.hardware-lifecycle.schematic-snapshot.v1",
            "sourceIdentity": {},
            "snapshotDigest": "",
            "moduleDigest": "",
            "exports": [],
        },
        "review-report": {
            "schemaVersion": "easyeda.hardware-lifecycle.review-report.v1",
            "snapshotDigest": "",
            "findings": [],
        },
        "review-actions": {"schemaVersion": "easyeda.hardware-lifecycle.review-actions.v1", "actions": []},
        "release-gate": {
            "schemaVersion": "easyeda.hardware-lifecycle.release-gate.v1",
            "status": "BLOCKED",
            "snapshotDigest": "",
        },
    },
    "bom_selection": {
        "bom-requirements": {"schemaVersion": "easyeda.hardware-lifecycle.bom-requirements.v1", "requirements": []},
        "bom-candidates": {
            "schemaVersion": "easyeda.hardware-lifecycle.bom-candidates.v1",
            "candidates": [],
            "ambiguous": [],
            "unmatched": [],
        },
        "final-bom": {"schemaVersion": "easyeda.hardware-lifecycle.final-bom.v1", "lines": []},
        "final-bom-digest": {"schemaVersion": "easyeda.hardware-lifecycle.final-bom-digest.v1", "sha256": ""},
    },
    "bom_writeback": {
        "write-plan": {"schemaVersion": "easyeda.hardware-lifecycle.api-plan.v1", "risk": "PERSISTENT_WRITE", "save": True},
        "acceptance-report": {
            "schemaVersion": "easyeda.hardware-lifecycle.acceptance-report.v1",
            "status": "PENDING",
            "restorationVerified": False,
            "protectedFieldsVerified": False,
            "explicitAuthorization": False,
        },
        "fresh-write-plan": {"schemaVersion": "easyeda.hardware-lifecycle.api-plan.v1", "risk": "PERSISTENT_WRITE", "save": True},
        "apply-journal": {"schemaVersion": "easyeda.hardware-lifecycle.apply-journal.v1", "status": "PENDING", "saved": False},
        "post-save-readback": {
            "schemaVersion": "easyeda.hardware-lifecycle.post-save-readback.v1",
            "readbackVerified": False,
            "protectedFieldsUnchanged": False,
            "connectivityUnchanged": False,
            "drcStatus": "PENDING",
            "exportComparison": "PENDING",
        },
    },
}


def stage_templates(stage: str) -> dict[str, dict[str, Any]]:
    try:
        return deepcopy(_TEMPLATES[stage])
    except KeyError as exc:
        raise ValueError(f"unknown lifecycle stage: {stage}") from exc

