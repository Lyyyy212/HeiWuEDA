from __future__ import annotations

import unittest

from hwlifecycle.api_registry import plan_digest, registry_identity, validate_api_plan
from hwlifecycle.state import (
    advance,
    invalidate,
    mark_gate,
    new_state,
    record_artifact,
    validate_state,
)


SHA_A = "a" * 64
SHA_B = "b" * 64


def manifest_fixture() -> dict:
    return {
        "schemaVersion": "easyeda.api-manifest.v1",
        "canonicalSource": {
            "package": "@jlceda/pro-api-types",
            "version": "0.4.15",
            "declarationSha256": SHA_A,
        },
        "declarations": {
            "classes": {
                "DMT_SelectControl": {
                    "releaseTag": "public",
                    "documentationPath": "references/classes/DMT_SelectControl.md",
                    "methods": [
                        {
                            "id": "DMT_SelectControl.getCurrentDocumentInfo#1",
                            "name": "getCurrentDocumentInfo",
                            "signature": "public getCurrentDocumentInfo(): Promise<object>;",
                            "deprecated": False,
                        }
                    ],
                },
                "SCH_PrimitiveComponent": {
                    "releaseTag": "public",
                    "documentationPath": "references/classes/SCH_PrimitiveComponent.md",
                    "methods": [
                        {
                            "id": "SCH_PrimitiveComponent.modify#1",
                            "name": "modify",
                            "signature": "public modify(id: string, property: object): Promise<object>;",
                            "deprecated": False,
                        }
                    ],
                },
            }
        },
    }


def base_plan(manifest: dict) -> dict:
    return {
        "schemaVersion": "easyeda.hardware-lifecycle.api-plan.v1",
        "planId": "plan:test",
        "risk": "READ",
        "registry": registry_identity(manifest),
        "identity": {
            "projectUuid": "project-uuid",
            "documentUuid": "document-uuid",
            "documentType": "SCHEMATIC_PAGE",
            "capturedAt": "2026-08-24T00:00:00Z",
            "bridge": {"service": "easyeda-bridge", "windowId": "window-1"},
        },
        "calls": [
            {
                "methodId": "DMT_SelectControl.getCurrentDocumentInfo#1",
                "effect": "READ",
                "purpose": "verify active document identity",
            }
        ],
        "save": False,
    }


class LifecycleStateTests(unittest.TestCase):
    def test_gate_and_one_stage_advance(self) -> None:
        state = new_state("test-project", "project:test")
        self.assertEqual([], validate_state(state))
        gated = mark_gate(
            state,
            "concept",
            "passed",
            evidence=["design/system-architecture.json"],
            output_digest=SHA_A,
        )
        advanced = advance(gated, "module_design")
        self.assertEqual("module_design", advanced["currentStage"])
        self.assertEqual([], validate_state(advanced))

    def test_cannot_skip_a_stage(self) -> None:
        state = mark_gate(
            new_state("test-project"),
            "concept",
            "passed",
            evidence=["design/system-architecture.json"],
            output_digest=SHA_A,
        )
        with self.assertRaisesRegex(ValueError, "next stage must be module_design"):
            advance(state, "schematic_review")

    def test_invalidation_resets_downstream(self) -> None:
        state = new_state("test-project")
        state = record_artifact(
            state,
            "concept",
            path="design/system-architecture.json",
            sha256=SHA_A,
            artifact_type="system-architecture",
        )
        state = mark_gate(
            state,
            "concept",
            "passed",
            evidence=["design/system-architecture.json"],
            output_digest=SHA_A,
        )
        state = advance(state, "module_design")
        invalidated = invalidate(state, "concept", "power budget changed")
        self.assertEqual("concept", invalidated["currentStage"])
        self.assertEqual("in_progress", invalidated["stages"]["concept"]["status"])
        self.assertEqual("pending", invalidated["stages"]["module_design"]["status"])
        self.assertEqual([], invalidated["stages"]["concept"]["artifacts"])
        self.assertEqual(1, len(invalidated["stages"]["concept"]["staleArtifacts"]))
        self.assertEqual([], validate_state(invalidated))


class ApiContractTests(unittest.TestCase):
    def test_valid_read_plan(self) -> None:
        manifest = manifest_fixture()
        result = validate_api_plan(base_plan(manifest), manifest)
        self.assertTrue(result["valid"])
        self.assertTrue(result["executable"])

    def test_unknown_method_is_blocked(self) -> None:
        manifest = manifest_fixture()
        plan = base_plan(manifest)
        plan["calls"][0]["methodId"] = "DMT_SelectControl.notReal#1"
        result = validate_api_plan(plan, manifest)
        self.assertFalse(result["valid"])
        self.assertIn("absent from the locked manifest", " ".join(result["errors"]))

    def test_persistent_write_requires_exact_authorization(self) -> None:
        manifest = manifest_fixture()
        plan = base_plan(manifest)
        plan.update(
            {
                "risk": "PERSISTENT_WRITE",
                "calls": [
                    {
                        "methodId": "SCH_PrimitiveComponent.modify#1",
                        "effect": "WRITE",
                        "purpose": "write one approved procurement field",
                    }
                ],
                "scope": {
                    "fields": ["Manufacturer", "Manufacturer Part"],
                    "protectedFieldsDigest": SHA_A,
                },
                "finalBomDigest": SHA_B,
                "save": False,
            }
        )
        planned = validate_api_plan(plan, manifest)
        self.assertTrue(planned["valid"])
        self.assertFalse(planned["executable"])

        plan["save"] = True
        accepted_digest = plan_digest(plan)
        plan["authorization"] = {
            "explicit": True,
            "acceptedAt": "2026-08-24T00:01:00Z",
            "acceptedPlanDigest": accepted_digest,
            "acceptanceReportSha256": SHA_A,
        }
        accepted = validate_api_plan(plan, manifest)
        self.assertTrue(accepted["valid"])
        self.assertTrue(accepted["executable"])

    def test_read_effect_cannot_mask_modify(self) -> None:
        manifest = manifest_fixture()
        plan = base_plan(manifest)
        plan["calls"][0] = {
            "methodId": "SCH_PrimitiveComponent.modify#1",
            "effect": "READ",
            "purpose": "incorrect classification",
        }
        result = validate_api_plan(plan, manifest)
        self.assertFalse(result["valid"])
        self.assertIn("conflicts with inferred WRITE", " ".join(result["errors"]))


if __name__ == "__main__":
    unittest.main()
