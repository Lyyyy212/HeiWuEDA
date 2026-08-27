"""Explicit and identity-guarded EasyEDA window resolution after bridge restarts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .errors import BridgeError


@dataclass(frozen=True)
class WindowResolution:
    requested_window_id: str | None
    resolved_window_id: str
    rebound: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "requestedWindowId": self.requested_window_id,
            "resolvedWindowId": self.resolved_window_id,
            "rebound": self.rebound,
            "policy": "EXPLICIT_SINGLE_CONNECTED_EXACT_IDENTITY_GUARD",
        }


def resolve_window(
    windows: Mapping[str, Any],
    *,
    requested_window_id: str | None,
    identity: Mapping[str, Any] | None,
    allow_rebind: bool = False,
) -> WindowResolution:
    """Resolve a stale window only when the subsequent API code has exact identity guards."""

    requested = requested_window_id or (identity or {}).get("windowId") or windows.get(
        "activeWindowId"
    )
    if not isinstance(requested, str) or not requested.strip():
        raise BridgeError("No active EasyEDA window is available")
    requested = requested.strip()
    connected = sorted(
        {
            str(item.get("windowId")).strip()
            for item in windows.get("windows", [])
            if isinstance(item, Mapping)
            and item.get("connected") is True
            and isinstance(item.get("windowId"), str)
            and str(item.get("windowId")).strip()
        }
    )
    if requested in connected:
        return WindowResolution(requested, requested, False)
    if not allow_rebind:
        raise BridgeError(f"Target EasyEDA window is not connected: {requested}")

    expected = dict(identity or {})
    project_uuid = expected.get("projectUuid")
    document_uuid = expected.get("documentUuid")
    if not isinstance(project_uuid, str) or not project_uuid.strip():
        raise BridgeError("Window rebind requires an exact expected project UUID")
    if not isinstance(document_uuid, str) or not document_uuid.strip():
        raise BridgeError("Window rebind requires an exact expected document UUID")
    if len(connected) != 1:
        raise BridgeError(
            "Window rebind requires exactly one connected EasyEDA window; "
            f"found {len(connected)}"
        )
    return WindowResolution(requested, connected[0], True)
