from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from hwlifecycle.artifact_store import ArtifactStore
from hwlifecycle.io_utils import load_json, sha256_json, write_json_atomic
from hwlifecycle.orchestrator import LifecycleOrchestrator
from hwlifecycle.stage_modules import get_stage_module
from hwlifecycle.state import advance, new_state, record_artifact


IDENTITY = {
    "projectUuid": "project-1",
    "documentUuid": "page-1",
    "documentType": 1,
    "capturedAt": "2026-08-24T00:00:00Z",
}


def concept_artifacts() -> dict:
    return {
        "requirements": [{"requirements": [{
            "id": "REQ-PERF-001", "statement": "measure input", "priority": "P0",
            "verificationMethod": "bench", "owner": "hardware", "status": "active",
            "source": "brief", "acceptance": {"maxErrorPercent": 1},
        }]}],
        "system-architecture": [{
            "modules": ["power", "acquisition"], "interfaces": ["analog-in"],
            "powerDomains": ["3V3"], "alternatives": [{"options": ["A", "B"], "selected": "A"}],
            "unknowns": [{"question": "sensor", "owner": "hardware", "resolutionPlan": "bench test"}],
        }],
        "verification-strategy": [{"verifications": [{"requirementId": "REQ-PERF-001", "method": "bench"}]}],
    }


def complete_lifecycle_artifacts() -> dict[str, dict[str, dict]]:
    final_bom = {"lines": [{
        "references": ["U1"], "quantity": 1, "value": "MCU", "footprint": "QFN-32",
        "manufacturer": "Vendor", "manufacturerPart": "ABC", "supplier": "LCSC",
        "supplierPart": "C1", "selectionRequirementIds": ["SEL-1"], "rationale": "fit",
        "pageUuid": "page-1", "packageValidation": {"status": "PASSED"},
        "specValidation": {"status": "PASSED"}, "lifecycle": {"status": "active"},
        "critical": True, "alternates": ["DEF"],
    }]}
    write_plan = {
        "risk": "PERSISTENT_WRITE",
        "save": True,
        "scope": {"allowedFields": ["Manufacturer"], "pageUuid": "page-1"},
        "finalBomDigest": sha256_json(final_bom),
    }
    return {
        "concept": {key: values[0] for key, values in concept_artifacts().items()},
        "module_design": {
            "module-profile": {
                "moduleId": "power", "purpose": "supply", "owners": ["hw"], "inputs": ["VIN"],
                "outputs": ["3V3"], "tracedRequirementIds": ["REQ-PERF-001"],
                "constraints": {"vin": "5V"}, "implementationOptions": ["LDO"],
                "verificationPlan": ["load test"], "invalidationTriggers": ["input range"],
                "calculations": [{"name": "thermal"}],
            },
            "interfaces": {"interfaces": [{
                "id": "IF-PWR", "producer": "power", "consumers": ["power"],
                "electrical": {"voltage": 3.3}, "timing": {"startupMs": 10},
                "connectorOrNet": "3V3",
            }]},
            "electrical-constraints": {"constraints": [{"id": "EC-1", "limit": 3.3}]},
        },
        "schematic_review": {
            "schematic-snapshot": {
                "sourceIdentity": IDENTITY, "snapshotDigest": "snap", "moduleDigest": "module",
            },
            "review-report": {"snapshotDigest": "snap", "findings": []},
            "review-actions": {"actions": []},
            "release-gate": {"status": "PASSED", "snapshotDigest": "snap"},
        },
        "bom_selection": {
            "bom-requirements": {"requirements": [{"id": "SEL-1"}]},
            "bom-candidates": {"candidates": [], "ambiguous": [], "unmatched": []},
            "final-bom": final_bom,
            "final-bom-digest": {"sha256": sha256_json(final_bom)},
        },
        "bom_writeback": {
            "write-plan": write_plan,
            "acceptance-report": {
                "status": "PASSED", "restorationVerified": True,
                "protectedFieldsVerified": True, "explicitAuthorization": True,
            },
            "fresh-write-plan": dict(write_plan),
            "apply-journal": {"status": "SUCCESS", "saved": True},
            "post-save-readback": {
                "readbackVerified": True, "protectedFieldsUnchanged": True,
                "connectivityUnchanged": True, "drcStatus": "UNCHANGED",
                "exportComparison": "EXPECTED_FIELDS_ONLY",
            },
        },
    }


class StageModuleTests(unittest.TestCase):
    def test_concept_gate_passes_complete_traceability(self) -> None:
        result = get_stage_module("concept").validate(concept_artifacts(), ["design/requirements.json"])
        self.assertTrue(result.passed, result.as_dict())

    def test_concept_gate_blocks_missing_verification(self) -> None:
        artifacts = concept_artifacts()
        artifacts["verification-strategy"][0]["verifications"] = []
        result = get_stage_module("concept").validate(artifacts, [])
        self.assertFalse(result.passed)
        self.assertIn("verification coverage", " ".join(result.blockers))

    def test_module_design_gate(self) -> None:
        module = {
            "moduleId": "power", "purpose": "supply", "owners": ["hw"], "inputs": ["VIN"],
            "outputs": ["3V3"], "tracedRequirementIds": ["REQ-PWR-001"],
            "constraints": {"vin": "5V"}, "implementationOptions": ["LDO"],
            "verificationPlan": ["load test"], "invalidationTriggers": ["input range"],
            "calculations": [{"name": "thermal"}],
        }
        artifacts = {
            "module-profile": [module],
            "interfaces": [{"interfaces": [{
                "id": "IF-PWR", "producer": "power", "consumers": ["power"],
                "electrical": {"voltage": 3.3}, "timing": {"startupMs": 10}, "connectorOrNet": "3V3",
            }]}],
            "electrical-constraints": [{"constraints": [{"id": "EC-1", "limit": 3.3}]}],
        }
        self.assertTrue(get_stage_module("module_design").validate(artifacts, []).passed)

    def test_schematic_review_gate(self) -> None:
        artifacts = {
            "schematic-snapshot": [{"sourceIdentity": IDENTITY, "snapshotDigest": "snap", "moduleDigest": "module"}],
            "review-report": [{"snapshotDigest": "snap", "findings": []}],
            "review-actions": [{"actions": []}],
            "release-gate": [{"status": "PASSED", "snapshotDigest": "snap"}],
        }
        self.assertTrue(get_stage_module("schematic_review").validate(artifacts, []).passed)

    def test_bom_selection_gate_and_digest(self) -> None:
        final_bom = {"lines": [{
            "references": ["U1"], "quantity": 1, "value": "MCU", "footprint": "QFN-32",
            "manufacturer": "Vendor", "manufacturerPart": "ABC", "supplier": "LCSC",
            "supplierPart": "C1", "selectionRequirementIds": ["SEL-1"], "rationale": "fit",
            "pageUuid": "page-1", "packageValidation": {"status": "PASSED"},
            "specValidation": {"status": "PASSED"}, "lifecycle": {"status": "active"},
            "critical": True, "alternates": ["DEF"],
        }]}
        artifacts = {
            "bom-requirements": [{"requirements": [{"id": "SEL-1"}]}],
            "bom-candidates": [{"candidates": [], "ambiguous": [], "unmatched": []}],
            "final-bom": [final_bom],
            "final-bom-digest": [{"sha256": sha256_json(final_bom)}],
        }
        self.assertTrue(get_stage_module("bom_selection").validate(artifacts, []).passed)

    def test_bom_writeback_gate(self) -> None:
        plan = {"risk": "PERSISTENT_WRITE", "save": True, "scope": {"allowedFields": ["Manufacturer"], "pageUuid": "page-1"}, "finalBomDigest": "bom"}
        artifacts = {
            "write-plan": [plan], "fresh-write-plan": [dict(plan)],
            "acceptance-report": [{"status": "PASSED", "restorationVerified": True, "protectedFieldsVerified": True, "explicitAuthorization": True}],
            "apply-journal": [{"status": "SUCCESS", "saved": True}],
            "post-save-readback": [{"readbackVerified": True, "protectedFieldsUnchanged": True, "connectivityUnchanged": True, "drcStatus": "UNCHANGED", "exportComparison": "EXPECTED_FIELDS_ONLY"}],
        }
        self.assertTrue(get_stage_module("bom_writeback").validate(artifacts, []).passed)


class ArtifactStoreTests(unittest.TestCase):
    def test_content_addressed_artifact_detects_tamper(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            store = ArtifactStore(root)
            stored = store.put_json(
                project_id="project:test", artifact_type="requirements",
                relative_path="design/requirements.json", payload={"requirements": []},
                producer_module="concept-design",
            )
            record = stored.state_record()
            self.assertEqual([], store.verify_record(record))
            (root / stored.payload_path).write_text("{}\n", encoding="utf-8")
            self.assertIn("digest mismatch", " ".join(store.verify_record(record)))

    def test_orchestrator_records_a_verified_concept_gate(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            state_path = root / ".hardware-lifecycle" / "project-state.json"
            state = new_state("orchestrator", "project:test")
            write_json_atomic(state_path, state)
            store = ArtifactStore(root)
            payloads = {key: values[0] for key, values in concept_artifacts().items()}
            for artifact_type, payload in payloads.items():
                stored = store.put_json(
                    project_id="project:test", artifact_type=artifact_type,
                    relative_path=f"design/{artifact_type}.json", payload=payload,
                    producer_module="concept-design",
                )
                state = record_artifact(
                    state, "concept", path=stored.payload_path,
                    sha256=stored.sha256, artifact_type=artifact_type,
                )
                state["stages"]["concept"]["artifacts"][-1]["envelope"] = stored.envelope_path
            write_json_atomic(state_path, state)
            result = LifecycleOrchestrator(root).evaluate(record=True)
            self.assertTrue(result.passed, result.as_dict())
            saved = load_json(state_path)
            self.assertEqual("passed", saved["stages"]["concept"]["gate"]["status"])
            self.assertEqual("completed", saved["stages"]["concept"]["status"])

    def test_complete_five_stage_lifecycle_records_all_gates(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            state_path = root / ".hardware-lifecycle" / "project-state.json"
            write_json_atomic(state_path, new_state("full lifecycle", "project:full"))
            store = ArtifactStore(root)
            stages = complete_lifecycle_artifacts()
            stage_names = list(stages)

            for stage_index, stage in enumerate(stage_names):
                state = load_json(state_path)
                self.assertEqual(stage, state["currentStage"])
                for artifact_type, payload in stages[stage].items():
                    stored = store.put_json(
                        project_id="project:full",
                        artifact_type=artifact_type,
                        relative_path=f"e2e/{stage}/{artifact_type}.json",
                        payload=payload,
                        producer_module=f"{stage}-test",
                    )
                    state = record_artifact(
                        state,
                        stage,
                        path=stored.payload_path,
                        sha256=stored.sha256,
                        artifact_type=artifact_type,
                    )
                    state["stages"][stage]["artifacts"][-1]["envelope"] = stored.envelope_path
                write_json_atomic(state_path, state)

                result = LifecycleOrchestrator(root).evaluate(record=True)
                self.assertTrue(result.passed, result.as_dict())
                state = load_json(state_path)
                if stage_index + 1 < len(stage_names):
                    write_json_atomic(state_path, advance(state, stage_names[stage_index + 1]))

            final_state = load_json(state_path)
            self.assertEqual("bom_writeback", final_state["currentStage"])
            self.assertTrue(all(
                record["status"] == "completed" and record["gate"]["status"] == "passed"
                for record in final_state["stages"].values()
            ))


if __name__ == "__main__":
    unittest.main()
