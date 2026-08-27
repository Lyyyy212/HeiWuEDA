"""Deterministic transport policy for JLC Hardware Learning visual imports."""

from __future__ import annotations

from typing import Any


VISUAL_IMPORT_ROUTE_SCHEMA = "learning.visual-import-route.v1"
DEFAULT_VISUAL_IMPORT_ROUTE = "pdf"
VISUAL_IMPORT_ROUTES: dict[str, dict[str, Any]] = {
    "pdf": {
        "exportFormat": "PDF",
        "localRenderRequired": True,
        "manifestCommand": "learning-pdf-visual-import-manifest",
        "evidenceSource": "official-easyeda-pdf-render",
        "maxLongEdge": 6144,
    },
    "png": {
        "exportFormat": "PNG",
        "localRenderRequired": False,
        "manifestCommand": "learning-native-visual-import-manifest",
        "evidenceSource": "official-easyeda-export",
        "maxLongEdge": None,
    },
}


def resolve_visual_import_route(requested_route: str | None = None) -> dict[str, Any]:
    """Resolve the default PDF route or an explicit supported override.

    Appearance mode is intentionally outside this policy: ``default`` and
    ``black-white`` select the EasyEDA theme, not the transport format.
    """

    requested = str(requested_route or "").strip().lower()
    route = requested or DEFAULT_VISUAL_IMPORT_ROUTE
    if route not in VISUAL_IMPORT_ROUTES:
        choices = ", ".join(VISUAL_IMPORT_ROUTES)
        raise ValueError(f"visual import route must be one of: {choices}")

    selected_by = "explicit-request" if requested else "default-policy"
    resolved = dict(VISUAL_IMPORT_ROUTES[route])
    return {
        "schemaVersion": VISUAL_IMPORT_ROUTE_SCHEMA,
        "route": route,
        "defaultRoute": DEFAULT_VISUAL_IMPORT_ROUTE,
        "selectedBy": selected_by,
        "requiresExplicitRequest": route != DEFAULT_VISUAL_IMPORT_ROUTE,
        **resolved,
    }
