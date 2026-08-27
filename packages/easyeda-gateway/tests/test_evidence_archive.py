from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from zipfile import ZipFile

from easyeda_gateway.evidence_archive import create_evidence_archive


class EvidenceArchiveTests(unittest.TestCase):
    def test_creates_deterministic_archive_with_internal_hash_manifest(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "证据"
            (source / "nested").mkdir(parents=True)
            (source / "报告.json").write_text('{"状态":"复核"}\n', encoding="utf-8")
            (source / "nested" / "artifact.bin").write_bytes(b"artifact")

            first = create_evidence_archive(source, root / "first.zip")
            second = create_evidence_archive(source, root / "second.zip")

            self.assertEqual(first["archive"]["sha256"], second["archive"]["sha256"])
            with ZipFile(first["archive"]["path"]) as archive:
                manifest = json.loads(archive.read("evidence-manifest.json"))
                self.assertEqual(manifest["fileCount"], 2)
                self.assertEqual(
                    [item["path"] for item in manifest["files"]],
                    ["nested/artifact.bin", "报告.json"],
                )

    def test_refuses_overwrite_and_output_inside_source(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "evidence"
            source.mkdir()
            (source / "item.txt").write_text("keep", encoding="utf-8")
            output = root / "archive.zip"
            output.write_bytes(b"keep")

            with self.assertRaisesRegex(Exception, "already exists"):
                create_evidence_archive(source, output)
            with self.assertRaisesRegex(Exception, "outside"):
                create_evidence_archive(source, source / "archive.zip")
            self.assertEqual(output.read_bytes(), b"keep")


if __name__ == "__main__":
    unittest.main()
