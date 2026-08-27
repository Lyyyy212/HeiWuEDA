from __future__ import annotations

import argparse
from contextlib import redirect_stdout
from io import StringIO
import unittest

from workbench import build_parser


class WorkbenchCliSurfaceTests(unittest.TestCase):
    def test_every_registered_command_exposes_help(self) -> None:
        parser = build_parser()
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


if __name__ == "__main__":
    unittest.main()
