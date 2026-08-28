"""Locate the canonical EasyEDA gateway package without duplicating it in the skill."""

from __future__ import annotations

from importlib import metadata
import os
from pathlib import Path
import sys


GATEWAY_DISTRIBUTION = "easyeda-workbench-gateway"


def find_workbench_root() -> Path:
    """Resolve the workbench containing locked materials for tests and tooling."""

    candidates: list[Path] = []
    configured_root = os.environ.get("EASYEDA_WORKBENCH_ROOT")
    if configured_root:
        candidates.append(Path(configured_root))
    candidates.extend((Path.cwd(), *Path(__file__).resolve().parents))
    for candidate in candidates:
        resolved = candidate.resolve()
        if (resolved / "materials" / "manifests" / "api-manifest.json").is_file():
            return resolved
    raise RuntimeError(
        "EasyEDA workbench materials are unavailable; set EASYEDA_WORKBENCH_ROOT "
        "to the HeiWuEDA checkout"
    )


def activate_gateway() -> Path:
    """Put the canonical gateway package root ahead of this skill's entrypoints.

    Development checkouts use ``packages/easyeda-gateway``.  A copied Codex
    skill falls back to the normally installed Python distribution.  Keeping
    that package separate preserves a single API/transport implementation and
    avoids vendoring a second, drifting copy into the orchestrator skill.
    """

    candidates: list[Path] = []
    configured_root = os.environ.get("EASYEDA_WORKBENCH_ROOT")
    if configured_root:
        candidates.append(Path(configured_root) / "packages" / "easyeda-gateway")

    script = Path(__file__).resolve()
    candidates.extend(parent / "packages" / "easyeda-gateway" for parent in script.parents)

    try:
        distribution = metadata.distribution(GATEWAY_DISTRIBUTION)
    except metadata.PackageNotFoundError:
        distribution = None
    if distribution is not None:
        candidates.append(Path(distribution.locate_file("")))

    for candidate in candidates:
        resolved = candidate.resolve()
        if (resolved / "easyeda_gateway" / "__init__.py").is_file():
            root = str(resolved)
            if root in sys.path:
                sys.path.remove(root)
            sys.path.insert(0, root)
            return resolved

    raise RuntimeError(
        "easyeda-workbench-gateway is unavailable; install it with "
        "'py -m pip install --user --no-deps <workbench>\\packages\\easyeda-gateway' "
        "or set EASYEDA_WORKBENCH_ROOT"
    )
