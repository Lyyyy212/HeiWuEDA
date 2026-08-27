from __future__ import annotations

from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from hwlifecycle.bom_sync_adapter import JlcBomSyncAdapter
from workbench import main as workbench_main


class BomSyncAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.skill_root = Path(temporary.name) / "jlc-bom-sync"
        entrypoint = self.skill_root / "scripts" / "jlc_bom_sync.py"
        entrypoint.parent.mkdir(parents=True)
        entrypoint.write_text("# test fixture\n", encoding="utf-8")
        self.adapter = JlcBomSyncAdapter(self.skill_root)

    def test_plan_and_acceptance_never_add_save(self) -> None:
        freeze = self.adapter.freeze(bom="final.xlsx", sheet="BOM", output="frozen.json")
        plan = self.adapter.plan(
            bom="final.xlsx", sheet="BOM", output="plan.json", evidence_dir="evidence/plan",
        )
        acceptance = self.adapter.acceptance(plan="plan.json", evidence_dir="evidence/acceptance")
        self.assertNotIn("--save", freeze)
        self.assertNotIn("--save", plan)
        self.assertNotIn("--save", acceptance)

    def test_workbench_exposes_bom_freeze_without_evidence_or_save(self) -> None:
        with TemporaryDirectory() as temporary:
            stdout = StringIO()
            with patch("workbench.JlcBomSyncAdapter", return_value=self.adapter):
                with redirect_stdout(stdout):
                    result = workbench_main([
                        "bom-sync-command",
                        "--project", temporary,
                        "--phase", "freeze",
                        "--bom", str(Path(temporary) / "final.xlsx"),
                        "--sheet", "BOM",
                        "--output", str(Path(temporary) / "frozen.json"),
                    ])
            payload = json.loads(stdout.getvalue())

        self.assertEqual(0, result)
        self.assertEqual("freeze", payload["phase"])
        self.assertEqual("freeze", payload["argv"][2])
        self.assertNotIn("--save", payload["argv"])

    def test_apply_requires_explicit_authorization_and_adds_save(self) -> None:
        with self.assertRaises(PermissionError):
            self.adapter.apply(
                plan="plan.json", acceptance_report="acceptance.json",
                evidence_dir="evidence/apply", explicit_save_authorization=False,
            )
        command = self.adapter.apply(
            plan="plan.json", acceptance_report="acceptance.json",
            evidence_dir="evidence/apply", explicit_save_authorization=True,
        )
        self.assertEqual("--save", command[-1])
        self.assertIn("jlc_bom_sync.py", Path(command[1]).name)


if __name__ == "__main__":
    unittest.main()
