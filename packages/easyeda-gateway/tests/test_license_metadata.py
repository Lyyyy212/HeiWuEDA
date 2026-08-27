from __future__ import annotations

from pathlib import Path
import tomllib
import unittest


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


class LicenseMetadataTests(unittest.TestCase):
    def test_gateway_metadata_uses_lyyyy_noncommercial_identity(self) -> None:
        metadata = tomllib.loads(
            (PACKAGE_ROOT / "pyproject.toml").read_text(encoding="utf-8")
        )["project"]

        self.assertEqual(metadata["license"], "PolyForm-Noncommercial-1.0.0")
        self.assertEqual(metadata["authors"], [{"name": "Lyyyy"}])
        self.assertEqual(
            metadata["license-files"],
            ["LICENSE", "THIRD_PARTY_NOTICES.md", "LICENSES/*.txt"],
        )

    def test_gateway_distribution_contains_required_license_sources(self) -> None:
        required = (
            PACKAGE_ROOT / "LICENSE",
            PACKAGE_ROOT / "THIRD_PARTY_NOTICES.md",
            PACKAGE_ROOT / "LICENSES" / "Apache-2.0.txt",
            PACKAGE_ROOT / "LICENSES" / "JSZip-MIT.txt",
            PACKAGE_ROOT / "LICENSES" / "tracespace-MIT.txt",
        )
        for path in required:
            with self.subTest(path=path):
                self.assertTrue(path.is_file())

        license_text = required[0].read_text(encoding="utf-8")
        self.assertIn("Required Notice: Copyright 2026 Lyyyy.", license_text)

    def test_repository_declares_third_party_exceptions(self) -> None:
        scope = (REPOSITORY_ROOT / "LICENSE_SCOPE.md").read_text(encoding="utf-8")
        publishing = (REPOSITORY_ROOT / "PUBLISHING.md").read_text(encoding="utf-8")

        self.assertIn("source-available", scope)
        self.assertIn("official_runtime/*.min.js", scope)
        self.assertIn("Copyright holder: `Lyyyy`", publishing)
        self.assertIn("Commercial licensing: not offered", publishing)


if __name__ == "__main__":
    unittest.main()
