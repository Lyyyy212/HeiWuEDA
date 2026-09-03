from __future__ import annotations

import argparse
from contextlib import redirect_stdout
import hashlib
from io import StringIO
import os
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from easyeda_gateway.cli import (
    _bridge_popen_options,
    _build_parser,
    _default_manifest,
    _find_workbench_path,
)
from easyeda_gateway.version import GATEWAY_VERSION


class CliTests(unittest.TestCase):
    def test_default_manifest_falls_back_to_packaged_resource(self) -> None:
        with TemporaryDirectory() as temporary:
            missing = Path(temporary) / "materials" / "manifests" / "api-manifest.json"
            with patch.dict(os.environ, {}, clear=True):
                with patch("easyeda_gateway.cli._find_workbench_path", return_value=missing):
                    manifest = _default_manifest()

        self.assertEqual("api-manifest.json", manifest.name)
        self.assertTrue(manifest.is_file())

    def test_packaged_manifest_matches_locked_workbench_manifest(self) -> None:
        package_manifest = Path(__file__).resolve().parents[1] / "easyeda_gateway" / "api-manifest.json"
        workbench_manifest = Path(__file__).resolve().parents[3] / "materials" / "manifests" / "api-manifest.json"

        self.assertEqual(
            hashlib.sha256(workbench_manifest.read_bytes()).hexdigest(),
            hashlib.sha256(package_manifest.read_bytes()).hexdigest(),
        )

    def test_find_workbench_path_honors_explicit_root(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary) / "checkout"
            relative = Path("sentinel") / "bridge.mjs"
            target = root / relative
            target.parent.mkdir(parents=True)
            target.write_text("// bridge", encoding="utf-8")
            with patch.dict(os.environ, {"EASYEDA_WORKBENCH_ROOT": str(root)}, clear=True):
                found = _find_workbench_path(relative)

        self.assertEqual(target.resolve(), found)

    def test_find_workbench_path_accepts_named_child_checkout(self) -> None:
        for checkout_name in ("easyeda-hardware-workbench", "HeiWuEDA"):
            with self.subTest(checkout_name=checkout_name), TemporaryDirectory() as temporary:
                parent = Path(temporary)
                relative = Path("sentinel") / "bridge.mjs"
                target = parent / checkout_name / relative
                target.parent.mkdir(parents=True)
                target.write_text("// bridge", encoding="utf-8")
                with (
                    patch.dict(os.environ, {}, clear=True),
                    patch("easyeda_gateway.cli.Path.cwd", return_value=parent),
                ):
                    found = _find_workbench_path(relative)

                self.assertEqual(target.resolve(), found)

    def test_every_registered_command_exposes_help(self) -> None:
        parser = _build_parser()
        subparsers = next(
            action
            for action in parser._actions
            if isinstance(action, argparse._SubParsersAction)
        )

        self.assertGreater(len(subparsers.choices), 0)
        for command in sorted(subparsers.choices):
            with self.subTest(command=command):
                stdout = StringIO()
                with self.assertRaises(SystemExit) as raised:
                    with redirect_stdout(stdout):
                        parser.parse_args([command, "--help"])
                self.assertEqual(0, raised.exception.code)
                self.assertIn("usage:", stdout.getvalue())

    def test_version_flag_reports_package_version(self) -> None:
        stdout = StringIO()
        with self.assertRaises(SystemExit) as raised:
            with redirect_stdout(stdout):
                _build_parser().parse_args(["--version"])

        self.assertEqual(0, raised.exception.code)
        self.assertEqual(GATEWAY_VERSION, stdout.getvalue().strip())

    def test_windows_bridge_process_is_detached_from_parent_job(self) -> None:
        with (
            patch.object(subprocess, "DETACHED_PROCESS", 0x00000008, create=True),
            patch.object(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200, create=True),
            patch.object(subprocess, "CREATE_NO_WINDOW", 0x08000000, create=True),
        ):
            options = _bridge_popen_options("nt")

        self.assertTrue(options["creationflags"] & 0x00000008)
        self.assertTrue(options["creationflags"] & 0x00000200)
        self.assertFalse(options["creationflags"] & 0x08000000)
        self.assertTrue(options["close_fds"])

    def test_posix_bridge_process_starts_a_new_session(self) -> None:
        self.assertEqual({"start_new_session": True}, _bridge_popen_options("posix"))


if __name__ == "__main__":
    unittest.main()
