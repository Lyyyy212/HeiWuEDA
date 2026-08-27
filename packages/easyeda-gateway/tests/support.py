from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from threading import Thread
from typing import Any


class MockBridge:
    def __init__(
        self,
        execute_result: dict[str, Any] | None = None,
        execute_error: tuple[int, str] | None = None,
    ):
        self.requests: list[dict[str, Any]] = []
        self.execute_result = execute_result
        self.execute_error = execute_error
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                if self.path == "/health":
                    self._send(
                        200,
                        {
                            "service": "easyeda-bridge",
                            "status": "ok",
                            "edaConnected": True,
                            "edaWindowCount": 1,
                            "activeWindowId": "window-1",
                            "pendingRequests": 0,
                            "timestamp": 1,
                        },
                    )
                    return
                if self.path == "/eda-windows":
                    self._send(
                        200,
                        {
                            "windows": [{"windowId": "window-1", "connected": True, "active": True}],
                            "activeWindowId": "window-1",
                            "count": 1,
                        },
                    )
                    return
                self._send(404, {"error": "Not found"})

            def do_POST(self) -> None:
                length = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
                owner.requests.append({"path": self.path, "payload": payload})
                if self.path == "/eda-windows/select":
                    self._send(200, {"success": True, "activeWindowId": payload["windowId"]})
                    return
                if self.path == "/execute":
                    if owner.execute_error is not None:
                        status, message = owner.execute_error
                        self._send(status, {"success": False, "error": message})
                        return
                    result = owner.execute_result or {
                        "schemaVersion": "easyeda.gateway.eda-result.v1",
                        "identityBefore": {
                            "projectUuid": "project-1",
                            "documentUuid": "document-1",
                            "documentType": 1,
                        },
                        "identityAfter": {
                            "projectUuid": "project-1",
                            "documentUuid": "document-1",
                            "documentType": 1,
                        },
                        "results": {"project": {"uuid": "project-1"}},
                    }
                    self._send(
                        200,
                        {
                            "success": True,
                            "windowId": payload.get("windowId", "window-1"),
                            "result": result,
                        },
                    )
                    return
                self._send(404, {"error": "Not found"})

            def log_message(self, format: str, *args: Any) -> None:
                return

            def _send(self, status: int, value: dict[str, Any]) -> None:
                body = json.dumps(value).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = Thread(target=self.server.serve_forever, daemon=True)

    @property
    def port(self) -> int:
        return int(self.server.server_address[1])

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def __enter__(self) -> "MockBridge":
        self.thread.start()
        return self

    def __exit__(self, *_: Any) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
