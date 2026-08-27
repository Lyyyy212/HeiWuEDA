from __future__ import annotations

import base64
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
import zipfile

from easyeda_gateway.native_visual import (
    NATIVE_PNG_BUNDLE_EXECUTION_SCHEMA,
    normalize_existing_official_png_bundle,
)


PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


class NativeVisualNormalizationTests(unittest.TestCase):
    def test_normalizes_sealed_official_png_bundle_without_easyeda_call(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            source_dir = root / "source-evidence"
            source_dir.mkdir()
            source = source_dir / "current-schematic.png"
            with zipfile.ZipFile(source, "w", compression=zipfile.ZIP_STORED) as archive:
                archive.writestr("page-1.png", PNG_1X1)
                archive.writestr("page-2.png", PNG_1X1)
            import hashlib

            digest = hashlib.sha256(source.read_bytes()).hexdigest()
            identity = {
                "projectUuid": "project-1",
                "documentUuid": "document-1",
                "documentType": 1,
            }
            envelope = source_dir / "envelope.json"
            envelope.write_text(json.dumps({
                "schemaVersion": "easyeda.gateway.schematic-export-evidence.v1",
                "status": "FAIL",
                "expectedIdentity": {
                    "projectUuid": "project-1",
                    "documentUuid": "document-1",
                },
                "spec": {"fileType": "PNG", "scope": "current-schematic"},
                "error": {"message": "Schematic PNG export has an invalid PNG signature or IHDR"},
                "files": {source.name: digest},
            }), encoding="utf-8")
            output = root / "normalization.json"

            result = normalize_existing_official_png_bundle(
                source=source,
                source_envelope_path=envelope,
                identity_before=identity,
                identity_after=identity.copy(),
                evidence_root=root / "derived-evidence",
                output_path=output,
            )

            self.assertEqual(NATIVE_PNG_BUNDLE_EXECUTION_SCHEMA, result["schemaVersion"])
            self.assertEqual(2, result["pageCount"])
            self.assertEqual(0, result["easyedaApiCallCount"])
            self.assertFalse(result["automaticRetry"])
            self.assertTrue(all(Path(item["path"]).is_file() for item in result["pages"]))
            derived = json.loads(Path(result["evidencePath"]).read_text(encoding="utf-8"))
            self.assertEqual("PASS", derived["status"])
            self.assertFalse(derived["safety"]["officialCallRepeated"])

    def test_rejects_unsafe_bundle_entry(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            source_dir = root / "source-evidence"
            source_dir.mkdir()
            source = source_dir / "current-schematic.png"
            with zipfile.ZipFile(source, "w", compression=zipfile.ZIP_STORED) as archive:
                archive.writestr("../escape.png", PNG_1X1)
            import hashlib

            digest = hashlib.sha256(source.read_bytes()).hexdigest()
            identity = {"projectUuid": "project-1", "documentUuid": "document-1", "documentType": 1}
            envelope = source_dir / "envelope.json"
            envelope.write_text(json.dumps({
                "schemaVersion": "easyeda.gateway.schematic-export-evidence.v1",
                "status": "FAIL",
                "expectedIdentity": {"projectUuid": "project-1", "documentUuid": "document-1"},
                "spec": {"fileType": "PNG", "scope": "current-schematic"},
                "error": {"message": "Schematic PNG export has an invalid PNG signature or IHDR"},
                "files": {source.name: digest},
            }), encoding="utf-8")
            with self.assertRaisesRegex(Exception, "unsafe entry"):
                normalize_existing_official_png_bundle(
                    source=source,
                    source_envelope_path=envelope,
                    identity_before=identity,
                    identity_after=identity,
                    evidence_root=root / "derived-evidence",
                    output_path=root / "normalization.json",
                )


if __name__ == "__main__":
    unittest.main()
