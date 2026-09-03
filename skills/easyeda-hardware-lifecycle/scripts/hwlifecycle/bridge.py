"""Compatibility facade over the workbench's single EasyEDA bridge transport."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from _gateway_bootstrap import activate_gateway


activate_gateway()

from easyeda_gateway.client import BridgeClient, discover_bridge as _discover_bridge
from easyeda_gateway.errors import BridgeError


@dataclass(frozen=True)
class BridgeEndpoint:
    base_url: str
    health: dict[str, Any]


class OfficialBridgeClient:
    """Legacy lifecycle API backed by the guarded gateway transport."""

    def __init__(self, base_url: str, *, timeout: float = 30.0) -> None:
        self._client = BridgeClient(base_url, timeout=timeout)
        self.base_url = self._client.base_url
        self.timeout = timeout

    def health(self) -> dict[str, Any]:
        return self._client.health()

    def windows(self) -> dict[str, Any]:
        return self._client.windows()

    def resolve_window(self, requested_window_id: str | None = None) -> str:
        result = self.windows()
        connected = [
            item
            for item in result["windows"]
            if isinstance(item, Mapping)
            and item.get("connected") is True
            and isinstance(item.get("windowId"), str)
            and item.get("windowId")
        ]
        if requested_window_id:
            if any(item["windowId"] == requested_window_id for item in connected):
                return requested_window_id
            raise BridgeError(f"requested EasyEDA window is not connected: {requested_window_id}")
        if not connected:
            raise BridgeError("no EasyEDA window is connected to the dedicated Hardware Workbench bridge")
        if len(connected) > 1:
            window_ids = ", ".join(item["windowId"] for item in connected)
            raise BridgeError(
                "multiple EasyEDA windows are connected; specify --window-id from: "
                + window_ids
            )
        return connected[0]["windowId"]

    def execute(self, code: str, *, window_id: str) -> Any:
        """Run audited generated code through the protocol-v2 local-only operation."""
        response = self._client.execute_code(code, window_id)
        returned_window = response.get("windowId")
        if returned_window not in (None, window_id):
            raise BridgeError(
                f"bridge executed on unexpected window: {returned_window!r} != {window_id!r}"
            )
        return response.get("result")

    def execute_operation(
        self,
        operation: str,
        *,
        args: dict[str, Any] | None = None,
        window_id: str,
    ) -> Any:
        """Execute one protocol-v2 operation from the fixed store-safe catalog."""
        response = self._client.execute_operation(operation, args, window_id)
        returned_window = response.get("windowId")
        if returned_window not in (None, window_id):
            raise BridgeError(
                f"bridge operated on unexpected window: {returned_window!r} != {window_id!r}"
            )
        return response.get("result")


def discover_bridge(
    bridge_url: str = "auto",
    *,
    port_start: int = 49620,
    port_end: int = 49629,
    timeout: float = 0.8,
) -> BridgeEndpoint:
    if bridge_url == "auto":
        client = _discover_bridge(port_start=port_start, port_end=port_end, timeout=timeout)
    else:
        client = BridgeClient(bridge_url, timeout=timeout)
        client.health()
    return BridgeEndpoint(client.base_url, client.health())
