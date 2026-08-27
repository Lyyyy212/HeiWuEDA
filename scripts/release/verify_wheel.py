#!/usr/bin/env python3
"""Verify public metadata and license payloads in a gateway wheel."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
from zipfile import ZipFile


REQUIRED_LICENSE_SUFFIXES = (
    ".dist-info/licenses/LICENSE",
    ".dist-info/licenses/THIRD_PARTY_NOTICES.md",
    ".dist-info/licenses/LICENSES/Apache-2.0.txt",
    ".dist-info/licenses/LICENSES/JSZip-MIT.txt",
    ".dist-info/licenses/LICENSES/tracespace-MIT.txt",
)
REQUIRED_METADATA = (
    "Name: easyeda-workbench-gateway",
    "Author: Lyyyy",
    "License-Expression: PolyForm-Noncommercial-1.0.0",
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    wheel = Path(sys.argv[1] if len(sys.argv) > 1 else "").resolve()
    if not wheel.is_file() or wheel.suffix != ".whl":
        raise SystemExit("usage: verify_wheel.py <gateway-wheel.whl>")

    with ZipFile(wheel) as archive:
        names = archive.namelist()
        for suffix in REQUIRED_LICENSE_SUFFIXES:
            if not any(name.endswith(suffix) for name in names):
                raise SystemExit(f"wheel is missing required license payload: {suffix}")
        metadata_names = [name for name in names if name.endswith(".dist-info/METADATA")]
        if len(metadata_names) != 1:
            raise SystemExit(f"expected one METADATA file, found {len(metadata_names)}")
        metadata = archive.read(metadata_names[0]).decode("utf-8")
        for field in REQUIRED_METADATA:
            if field not in metadata:
                raise SystemExit(f"wheel metadata is missing: {field}")

    print(
        json.dumps(
            {
                "status": "PASS",
                "wheel": str(wheel),
                "sha256": sha256_file(wheel),
                "licensePayloads": len(REQUIRED_LICENSE_SUFFIXES),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
