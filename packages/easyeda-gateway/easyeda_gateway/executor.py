"""Validated plan compilation, execution, and immutable evidence recording."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Any
from uuid import uuid4

from .client import BridgeClient
from .contract import ApiRegistry, canonical_json, sha256_json
from .errors import AuthorizationError, BridgeError, ContractError
from .version import GATEWAY_VERSION

AUTH_SCHEMA_VERSION = "easyeda.hardware-lifecycle.authorization.v1"
ACCEPTANCE_SCHEMA_VERSION = "easyeda.hardware-lifecycle.acceptance-report.v1"
EVIDENCE_SCHEMA_VERSION = "easyeda.gateway.execution-evidence.v1"
JS_IDENTIFIER_RE = re.compile(r"^[A-Za-z_$][A-Za-z0-9_$]*$")


@dataclass(frozen=True)
class ExecutionResult:
    plan_id: str
    plan_digest: str
    bridge_url: str
    window_id: str
    result: Any
    evidence_path: Path

    def as_dict(self) -> dict[str, Any]:
        return {
            "schemaVersion": "easyeda.gateway.execution-result.v1",
            "planId": self.plan_id,
            "planDigest": self.plan_digest,
            "bridgeUrl": self.bridge_url,
            "windowId": self.window_id,
            "result": self.result,
            "evidencePath": str(self.evidence_path),
        }


class BridgeExecutor:
    """The only workbench component allowed to construct code or call /execute."""

    def __init__(
        self,
        registry: ApiRegistry,
        client: BridgeClient,
        bridge_runtime: dict[str, Any] | None = None,
    ):
        self.registry = registry
        self.client = client
        self.bridge_runtime = bridge_runtime

    def build_code(self, plan: dict[str, Any]) -> str:
        report = self.registry.validate_plan(plan)
        report.require_valid()
        expected = plan["identity"]
        statements = [
            "const __readIdentity=async()=>{const project=await eda.dmt_Project.getCurrentProjectInfo();const document=await eda.dmt_SelectControl.getCurrentDocumentInfo();return {projectUuid:project?.uuid??null,documentUuid:document?.uuid??null,documentType:document?.documentType??null};}",
            f"const __expected={canonical_json(_identity_subset(expected))}",
            "const __before=await __readIdentity()",
            "for(const key of ['projectUuid','documentUuid','documentType']){if(__expected[key]!==null&&__expected[key]!==__before[key]){throw new Error(`EasyEDA identity drift for ${key}: expected ${String(__expected[key])}, got ${String(__before[key])}`);}}",
            "const __results={}",
        ]
        for call_index, (call, descriptor) in enumerate(
            zip(plan["calls"], report.resolved_calls, strict=True),
        ):
            if not JS_IDENTIFIER_RE.fullmatch(descriptor.runtime_module):
                raise ContractError(f"Invalid runtime module in manifest: {descriptor.runtime_module}")
            if not JS_IDENTIFIER_RE.fullmatch(descriptor.method_name):
                raise ContractError(f"Invalid method name in manifest: {descriptor.method_name}")
            arguments = ",".join(_render_argument(value) for value in call["args"])
            result_key = json.dumps(call["resultKey"], ensure_ascii=False)
            invocation = f"await eda.{descriptor.runtime_module}.{descriptor.method_name}({arguments})"
            pick = call.get("pick")
            if pick:
                value_name = f"__value{call_index}"
                statements.append(f"const {value_name}={invocation}")
                projected = ",".join(
                    f"{json.dumps(field_name)}:{value_name}?.[{json.dumps(field_name)}]??null"
                    for field_name in pick
                )
                statements.append(f"__results[{result_key}]={{{projected}}}")
            else:
                statements.append(f"__results[{result_key}]={invocation}")
        statements.extend(
            [
                "const __after=await __readIdentity()",
                "for(const key of ['projectUuid','documentUuid','documentType']){if(__before[key]!==__after[key]){throw new Error(`EasyEDA identity changed during plan for ${key}`);}}",
                "return {schemaVersion:'easyeda.gateway.eda-result.v1',identityBefore:__before,identityAfter:__after,results:__results}",
            ],
        )
        return ";".join(statements) + ";"

    def execute(
        self,
        plan: dict[str, Any],
        evidence_root: str | Path,
        authorization: dict[str, Any] | None = None,
        acceptance: dict[str, Any] | None = None,
    ) -> ExecutionResult:
        report = self.registry.validate_plan(plan)
        report.require_valid()
        if plan["risk"] != "READ":
            self._validate_bridge_runtime(plan)
        if plan["risk"] == "PERSISTENT_WRITE":
            self._validate_persistent_evidence(plan, report.plan_digest, authorization, acceptance)

        code = self.build_code(plan)
        health_before = self.client.health()
        windows_before = self.client.windows()
        requested_window = plan["identity"].get("windowId")
        target_window = requested_window or windows_before.get("activeWindowId")
        if not target_window:
            raise BridgeError("No active EasyEDA window is available")
        connected_ids = {
            item.get("windowId")
            for item in windows_before.get("windows", [])
            if isinstance(item, dict) and item.get("connected") is True
        }
        if target_window not in connected_ids:
            raise BridgeError(f"Target EasyEDA window is not connected: {target_window}")

        started_at = _utc_now()
        response = self.client.execute_code(code, target_window)
        finished_at = _utc_now()
        health_after = self.client.health()

        evidence_path = self._record_evidence(
            evidence_root=Path(evidence_root),
            plan=plan,
            report=report.as_dict(),
            code=code,
            response=response,
            health_before=health_before,
            health_after=health_after,
            windows_before=windows_before,
            target_window=target_window,
            started_at=started_at,
            finished_at=finished_at,
            authorization=authorization,
            acceptance=acceptance,
        )
        return ExecutionResult(
            plan_id=plan["planId"],
            plan_digest=report.plan_digest,
            bridge_url=self.client.base_url,
            window_id=target_window,
            result=response.get("result"),
            evidence_path=evidence_path,
        )

    def _validate_bridge_runtime(self, plan: dict[str, Any]) -> None:
        runtime = self.bridge_runtime
        if not isinstance(runtime, dict):
            raise AuthorizationError("Write execution requires trusted bridge runtime metadata")
        expected = {
            "schemaVersion": "easyeda.gateway.bridge-runtime.v1",
            "service": "easyeda-bridge",
            "bridgeUrl": self.client.base_url,
            "gatewayVersion": GATEWAY_VERSION,
            "scriptSha256": plan["identity"].get("bridgeScriptSha256"),
        }
        for key, value in expected.items():
            if runtime.get(key) != value:
                raise AuthorizationError(
                    f"Bridge runtime metadata mismatch for {key}: expected {value!r}, got {runtime.get(key)!r}",
                )

    def _validate_persistent_evidence(
        self,
        plan: dict[str, Any],
        digest: str,
        authorization: dict[str, Any] | None,
        acceptance: dict[str, Any] | None,
    ) -> None:
        if not isinstance(authorization, dict):
            raise AuthorizationError("Persistent write requires a separate authorization artifact")
        if authorization.get("schemaVersion") != AUTH_SCHEMA_VERSION:
            raise AuthorizationError(f"Authorization schema must be {AUTH_SCHEMA_VERSION}")
        if authorization.get("approved") is not True or authorization.get("planDigest") != digest:
            raise AuthorizationError("Authorization must explicitly approve the current plan digest")
        if authorization.get("scope") != plan.get("scope"):
            raise AuthorizationError("Authorization scope does not exactly match the plan scope")
        if not isinstance(authorization.get("approvedAt"), str):
            raise AuthorizationError("Authorization requires approvedAt")

        if not isinstance(acceptance, dict):
            raise AuthorizationError("Persistent write requires a separate acceptance report")
        if acceptance.get("schemaVersion") != ACCEPTANCE_SCHEMA_VERSION:
            raise AuthorizationError(f"Acceptance schema must be {ACCEPTANCE_SCHEMA_VERSION}")
        required = {
            "status": "PASSED",
            "restorationVerified": True,
            "protectedFieldsVerified": True,
        }
        for key, expected in required.items():
            if acceptance.get(key) != expected:
                raise AuthorizationError(f"Acceptance report requires {key}={expected!r}")
        if acceptance.get("scope") != plan.get("scope"):
            raise AuthorizationError("Acceptance scope does not exactly match the plan scope")

    def _record_evidence(
        self,
        *,
        evidence_root: Path,
        plan: dict[str, Any],
        report: dict[str, Any],
        code: str,
        response: dict[str, Any],
        health_before: dict[str, Any],
        health_after: dict[str, Any],
        windows_before: dict[str, Any],
        target_window: str,
        started_at: str,
        finished_at: str,
        authorization: dict[str, Any] | None,
        acceptance: dict[str, Any] | None,
    ) -> Path:
        safe_plan_id = re.sub(r"[^A-Za-z0-9_-]+", "-", plan["planId"]).strip("-") or "plan"
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
        directory = evidence_root.resolve() / f"{stamp}-{safe_plan_id}-{uuid4().hex[:8]}"
        directory.mkdir(parents=True, exist_ok=False)

        request_record = {
            "plan": plan,
            "validation": report,
            "generatedCodeSha256": hashlib.sha256(code.encode("utf-8")).hexdigest(),
        }
        result_record = {
            "bridgeResponse": response,
            "bridgeResponseSha256": sha256_json(response),
        }
        _atomic_write_json(directory / "request.json", request_record)
        _atomic_write_json(directory / "result.json", result_record)
        if authorization is not None:
            _atomic_write_json(directory / "authorization.json", authorization)
        if acceptance is not None:
            _atomic_write_json(directory / "acceptance.json", acceptance)

        envelope = {
            "schemaVersion": EVIDENCE_SCHEMA_VERSION,
            "planId": plan["planId"],
            "planDigest": report["planDigest"],
            "risk": plan["risk"],
            "startedAt": started_at,
            "finishedAt": finished_at,
            "bridge": {
                "service": health_before.get("service"),
                "url": self.client.base_url,
                "windowId": target_window,
                "healthBefore": health_before,
                "healthAfter": health_after,
                "windowsBefore": windows_before,
                "runtime": self.bridge_runtime,
            },
            "registry": self.registry.identity,
            "gatewayVersion": GATEWAY_VERSION,
            "files": {},
        }
        for name in ("request.json", "result.json", "authorization.json", "acceptance.json"):
            path = directory / name
            if path.exists():
                envelope["files"][name] = _sha256_file(path)
        _atomic_write_json(directory / "envelope.json", envelope)
        return directory / "envelope.json"


def _identity_subset(identity: dict[str, Any]) -> dict[str, Any]:
    return {
        "projectUuid": identity.get("projectUuid"),
        "documentUuid": identity.get("documentUuid"),
        "documentType": identity.get("documentType"),
    }


def _render_argument(value: Any) -> str:
    if isinstance(value, dict):
        if set(value) == {"$undefined"} and value["$undefined"] is True:
            return "undefined"
        if set(value) == {"$enum"}:
            return value["$enum"]
        fields = ",".join(
            f"{json.dumps(str(key), ensure_ascii=False)}:{_render_argument(item)}"
            for key, item in value.items()
        )
        return "{" + fields + "}"
    if isinstance(value, list):
        return "[" + ",".join(_render_argument(item) for item in value) + "]"
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _atomic_write_json(path: Path, value: Any) -> None:
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
