"""Local HTTP client for the dedicated Hardware Workbench EasyEDA bridge."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from .contract import SERVICE_ID
from .errors import BridgeDiscoveryError, BridgeError, BridgeTimeoutError

DEFAULT_PORT_START = 49620
DEFAULT_PORT_END = 49629
WORKBENCH_GATEWAY_ID = "lyyyy.hardware-workbench"
WORKBENCH_PRODUCT_ID = "hardware-workbench"
WORKBENCH_PROTOCOL_VERSION = 2
WORKBENCH_CODE_OPERATION = "workbench.official-api.execute.v1"
WORKBENCH_CODE_PROFILE = "easyeda-gateway-generated.v1"
WORKBENCH_OPERATION_IDS = frozenset(
    {
        "workbench.catalog.read.v1",
        "workbench.context.read.v1",
        WORKBENCH_CODE_OPERATION,
        "workbench.schematic.index.read.v1",
    },
)
MAX_RESPONSE_BYTES = 16 * 1024 * 1024
DEFAULT_REQUEST_TIMEOUT = 30.0


class BridgeClient:
    """Minimal localhost client that enforces the workbench transport identity."""

    def __init__(self, base_url: str, timeout: float = DEFAULT_REQUEST_TIMEOUT):
        normalized = base_url.rstrip("/")
        parsed = urlparse(normalized)
        if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
            raise BridgeError("Bridge URL must be an http:// loopback localhost address")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise BridgeError("Bridge URL must not contain credentials, query, or fragment")
        self.base_url = normalized
        self.timeout = timeout

    @property
    def port(self) -> int | None:
        return urlparse(self.base_url).port

    def health(self) -> dict[str, Any]:
        response = self._request_json("GET", "/health")
        if response.get("service") != SERVICE_ID:
            raise BridgeError(
                f"Service identity mismatch at {self.base_url}: {response.get('service')!r}",
            )
        if response.get("gatewayId") != WORKBENCH_GATEWAY_ID:
            raise BridgeError(
                "Dedicated Hardware Workbench bridge required: "
                f"gatewayId={response.get('gatewayId')!r}",
            )
        if response.get("productId") != WORKBENCH_PRODUCT_ID:
            raise BridgeError(
                "Dedicated Hardware Workbench bridge required: "
                f"productId={response.get('productId')!r}",
            )
        if response.get("protocolVersion") != WORKBENCH_PROTOCOL_VERSION:
            raise BridgeError(
                "Dedicated Hardware Workbench bridge protocol mismatch: "
                f"{response.get('protocolVersion')!r}",
            )
        return response

    def windows(self) -> dict[str, Any]:
        self.health()
        response = self._request_json("GET", "/eda-windows")
        windows = response.get("windows")
        if not isinstance(windows, list) or not isinstance(response.get("count"), int):
            raise BridgeError("Bridge returned an invalid /eda-windows response")
        for window in windows:
            if not isinstance(window, dict) or not _has_workbench_identity(window):
                raise BridgeError(
                    "Bridge exposed a window that was not registered by the "
                    "Hardware Workbench extension",
                )
        return response

    def select_window(self, window_id: str) -> dict[str, Any]:
        if not window_id:
            raise BridgeError("window_id must be non-empty")
        self.health()
        response = self._request_json(
            "POST",
            "/eda-windows/select",
            {"windowId": window_id, **_workbench_identity()},
        )
        if response.get("success") is not True or response.get("activeWindowId") != window_id:
            raise BridgeError("Bridge did not confirm the requested active window")
        return response

    def execute_code(self, code: str, window_id: str | None = None) -> dict[str, Any]:
        if not isinstance(code, str) or not code.strip():
            raise BridgeError("Generated code must be a non-empty string")
        code_bytes = code.encode("utf-8")
        return self.execute_operation(
            WORKBENCH_CODE_OPERATION,
            {
                "code": code,
                "codeSha256": hashlib.sha256(code_bytes).hexdigest(),
                "profile": WORKBENCH_CODE_PROFILE,
            },
            window_id,
        )

    def execute_operation(
        self,
        operation: str,
        args: dict[str, Any] | None = None,
        window_id: str | None = None,
    ) -> dict[str, Any]:
        if operation not in WORKBENCH_OPERATION_IDS:
            raise BridgeError(f"Operation is not allowlisted: {operation!r}")
        if args is not None and not isinstance(args, dict):
            raise BridgeError("Operation args must be a JSON object")
        health = self.health()
        if health.get("edaConnected") is not True:
            raise BridgeError("No Hardware Workbench EasyEDA extension is connected")
        payload: dict[str, Any] = {
            "args": args or {},
            "operation": operation,
            **_workbench_identity(),
        }
        if window_id:
            payload["windowId"] = window_id
        response = self._request_json("POST", "/operations/execute", payload)
        if response.get("success") is not True:
            raise BridgeError(str(response.get("error") or "EasyEDA operation failed"))
        return response

    def _request_json(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        body = None
        headers = {"Accept": "application/json"}
        if payload is not None:
            body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = Request(f"{self.base_url}{path}", data=body, headers=headers, method=method)
        try:
            with urlopen(request, timeout=self.timeout) as response:
                raw = response.read(MAX_RESPONSE_BYTES + 1)
        except HTTPError as exc:
            raw_error = exc.read(4096).decode("utf-8", errors="replace")
            if path == "/operations/execute" and "timed out after" in raw_error.casefold():
                raise BridgeTimeoutError(
                    f"Bridge execution timed out; the EasyEDA operation may still be running: {raw_error}",
                ) from exc
            raise BridgeError(f"Bridge HTTP {exc.code} for {path}: {raw_error}") from exc
        except TimeoutError as exc:
            raise BridgeTimeoutError(
                f"Bridge request timed out for {path}; the EasyEDA operation may still be running",
            ) from exc
        except URLError as exc:
            if isinstance(exc.reason, TimeoutError):
                raise BridgeTimeoutError(
                    f"Bridge request timed out for {path}; the EasyEDA operation may still be running",
                ) from exc
            raise BridgeError(f"Bridge request failed for {path}: {exc}") from exc
        except OSError as exc:
            raise BridgeError(f"Bridge request failed for {path}: {exc}") from exc
        if len(raw) > MAX_RESPONSE_BYTES:
            raise BridgeError(f"Bridge response exceeded {MAX_RESPONSE_BYTES} bytes")
        try:
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise BridgeError(f"Bridge returned invalid JSON for {path}") from exc
        if not isinstance(value, dict):
            raise BridgeError(f"Bridge returned a non-object JSON value for {path}")
        return value


def discover_bridge(
    port_start: int = DEFAULT_PORT_START,
    port_end: int = DEFAULT_PORT_END,
    timeout: float = 0.8,
) -> BridgeClient:
    """Discover only the project-dedicated bridge; generic bridges are rejected."""
    if port_start < 1 or port_end > 65535 or port_start > port_end:
        raise BridgeDiscoveryError("Invalid bridge port range")

    def probe(port: int) -> tuple[int, BridgeClient, dict[str, Any]] | None:
        client = BridgeClient(f"http://127.0.0.1:{port}", timeout=timeout)
        try:
            health = client.health()
        except BridgeError:
            return None
        if not _has_workbench_identity(health):
            return None
        return port, client, health

    found: list[tuple[int, BridgeClient, dict[str, Any]]] = []
    with ThreadPoolExecutor(max_workers=min(10, port_end - port_start + 1)) as executor:
        futures = [executor.submit(probe, port) for port in range(port_start, port_end + 1)]
        for future in as_completed(futures):
            result = future.result()
            if result is not None:
                found.append(result)
    if not found:
        raise BridgeDiscoveryError(
            "No dedicated Hardware Workbench EasyEDA bridge found on "
            f"127.0.0.1:{port_start}-{port_end}",
        )
    discovered = min(found, key=lambda item: item[0])[1]
    return BridgeClient(discovered.base_url, timeout=DEFAULT_REQUEST_TIMEOUT)


def _workbench_identity() -> dict[str, Any]:
    return {
        "gatewayId": WORKBENCH_GATEWAY_ID,
        "productId": WORKBENCH_PRODUCT_ID,
        "protocolVersion": WORKBENCH_PROTOCOL_VERSION,
    }


def _has_workbench_identity(value: dict[str, Any]) -> bool:
    return all(value.get(key) == expected for key, expected in _workbench_identity().items())
