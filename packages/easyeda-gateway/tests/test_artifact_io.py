from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from easyeda_gateway.artifact_io import atomic_write_json


class ArtifactIoTests(unittest.TestCase):
    def test_atomic_json_write_uses_a_windows_safe_temporary_name(self) -> None:
        with TemporaryDirectory() as temporary:
            parent = Path(temporary)
            while len(str(parent)) < 220:
                parent /= "e" * min(40, 220 - len(str(parent)))
            target = parent / "request.json"

            atomic_write_json(target, {"status": "PASS"})

            self.assertEqual({"status": "PASS"}, json.loads(target.read_text(encoding="utf-8")))
            self.assertEqual([], list(parent.glob("*.tmp")))


if __name__ == "__main__":
    unittest.main()
