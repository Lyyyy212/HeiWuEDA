"""Safe command handoff to the installed jlc-bom-sync skill."""

from __future__ import annotations

from pathlib import Path
from typing import Sequence


class JlcBomSyncAdapter:
    """Build argv lists without bypassing the authoritative four-step executor."""

    def __init__(self, skill_root: str | Path | None = None):
        self.skill_root = Path(skill_root or (Path.home() / ".codex" / "skills" / "jlc-bom-sync")).resolve()
        self.entrypoint = self.skill_root / "scripts" / "jlc_bom_sync.py"
        if not self.entrypoint.is_file():
            raise FileNotFoundError(f"jlc-bom-sync entrypoint not found: {self.entrypoint}")

    def _base(self) -> list[str]:
        return ["py", str(self.entrypoint)]

    @staticmethod
    def _path(value: str | Path) -> str:
        return str(Path(value).resolve())

    def freeze(self, *, bom: str | Path, sheet: str, output: str | Path) -> list[str]:
        return self._base() + ["freeze", "--bom", self._path(bom), "--sheet", sheet, "--output", self._path(output)]

    def plan(
        self,
        *,
        bom: str | Path,
        sheet: str,
        output: str | Path,
        evidence_dir: str | Path,
        bridge_url: str = "auto",
        critical_review: str | Path | None = None,
    ) -> list[str]:
        command = self._base() + [
            "plan", "--bom", self._path(bom), "--sheet", sheet,
            "--output", self._path(output), "--evidence-dir", self._path(evidence_dir),
            "--bridge-url", bridge_url,
        ]
        if critical_review is not None:
            command.extend(["--critical-review", self._path(critical_review)])
        return command

    def acceptance(
        self,
        *,
        plan: str | Path,
        evidence_dir: str | Path,
        bridge_url: str = "auto",
    ) -> list[str]:
        return self._base() + [
            "acceptance-test", "--plan", self._path(plan),
            "--evidence-dir", self._path(evidence_dir), "--bridge-url", bridge_url,
        ]

    def apply(
        self,
        *,
        plan: str | Path,
        acceptance_report: str | Path,
        evidence_dir: str | Path,
        explicit_save_authorization: bool,
        bridge_url: str = "auto",
    ) -> list[str]:
        if explicit_save_authorization is not True:
            raise PermissionError("persistent BOM writeback requires explicit_save_authorization=True")
        return self._base() + [
            "apply", "--plan", self._path(plan),
            "--acceptance-report", self._path(acceptance_report),
            "--evidence-dir", self._path(evidence_dir), "--bridge-url", bridge_url, "--save",
        ]

    @staticmethod
    def render_powershell(argv: Sequence[str]) -> str:
        def quote(value: str) -> str:
            return "'" + value.replace("'", "''") + "'"

        return " ".join(quote(str(item)) for item in argv)

