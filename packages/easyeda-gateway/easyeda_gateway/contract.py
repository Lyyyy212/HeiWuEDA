"""Locked API registry and typed-plan validation."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Iterable

from .errors import ContractError
from .version import GATEWAY_VERSION

PLAN_SCHEMA_VERSION = "easyeda.hardware-lifecycle.api-plan.v1"
SERVICE_ID = "easyeda-bridge"
SUPPORTED_RISKS = {"READ", "EPHEMERAL_WRITE", "PERSISTENT_WRITE"}
SUPPORTED_EFFECTS = {"READ", "WRITE"}
PERSISTENT_WRITE_FIELDS = {
    "Manufacturer",
    "Manufacturer Part",
    "Supplier",
    "Supplier Part",
}
PROCUREMENT_FIELD_TO_API_PROPERTY = {
    "Manufacturer": "manufacturer",
    "Manufacturer Part": "manufacturerId",
    "Supplier": "supplier",
    "Supplier Part": "supplierId",
}
COMPONENT_MODIFY_METHOD_ID = "SCH_PrimitiveComponent.modify#1"
SCHEMATIC_SAVE_METHOD_ID = "SCH_Document.save#1"
SCHEMATIC_PAGE_DOCUMENT_TYPE = 1

READ_PREFIXES = (
    "get",
    "is",
    "has",
    "check",
    "compare",
    "query",
    "search",
    "find",
    "list",
    "export",
    "calculate",
    "convert",
    "parse",
    "validate",
)
WRITE_PREFIXES = (
    "create",
    "delete",
    "remove",
    "modify",
    "set",
    "add",
    "insert",
    "update",
    "open",
    "close",
    "activate",
    "save",
    "import",
    "paste",
    "cut",
    "copy",
    "move",
    "rotate",
    "flip",
    "rename",
    "select",
    "clear",
    "reload",
    "switch",
    "apply",
    "register",
    "unregister",
    "show",
    "hide",
    "toggle",
    "lock",
    "unlock",
)
RESULT_KEY_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,63}$")
ENUM_REFERENCE_RE = re.compile(r"^[A-Z][A-Za-z0-9_]*\.[A-Z][A-Z0-9_]*$")
PICK_FIELD_RE = re.compile(r"^[A-Za-z_$][A-Za-z0-9_$]*$")


def load_json(path: str | Path) -> dict[str, Any]:
    """Load a UTF-8 JSON object."""
    source = Path(path)
    try:
        value = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractError(f"Cannot load JSON from {source}: {exc}") from exc
    if not isinstance(value, dict):
        raise ContractError(f"Expected a JSON object in {source}")
    return value


def canonical_json(value: Any) -> str:
    """Return deterministic UTF-8 JSON used by all gateway digests."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def plan_digest(plan: dict[str, Any]) -> str:
    """Hash a plan with its self-referential planDigest field removed."""
    canonical_plan = deepcopy(plan)
    canonical_plan.pop("planDigest", None)
    return sha256_json(canonical_plan)


@dataclass(frozen=True)
class MethodDescriptor:
    method_id: str
    class_name: str
    runtime_module: str
    method_name: str
    parameters: tuple[dict[str, Any], ...]
    returns_promise: bool
    release_tag: str | None
    deprecated: bool
    signature: str


@dataclass(frozen=True)
class ValidationIssue:
    code: str
    message: str
    path: str
    severity: str = "ERROR"

    def as_dict(self) -> dict[str, str]:
        return {
            "severity": self.severity,
            "code": self.code,
            "path": self.path,
            "message": self.message,
        }


@dataclass
class ValidationReport:
    valid: bool
    executable: bool
    plan_digest: str
    registry: dict[str, Any]
    issues: list[ValidationIssue] = field(default_factory=list)
    resolved_calls: list[MethodDescriptor] = field(default_factory=list, repr=False)

    def as_dict(self) -> dict[str, Any]:
        return {
            "schemaVersion": "easyeda.gateway.validation-report.v1",
            "valid": self.valid,
            "executable": self.executable,
            "planDigest": self.plan_digest,
            "registry": self.registry,
            "issues": [issue.as_dict() for issue in self.issues],
            "resolvedCalls": [
                {
                    "methodId": method.method_id,
                    "runtimeModule": method.runtime_module,
                    "signature": method.signature,
                }
                for method in self.resolved_calls
            ],
        }

    def require_valid(self) -> None:
        if self.valid:
            return
        detail = "; ".join(f"{issue.path}: {issue.message}" for issue in self.issues)
        raise ContractError(f"API plan validation failed: {detail}")


class ApiRegistry:
    """Read the locked API manifest and resolve canonical method IDs."""

    def __init__(self, manifest: dict[str, Any], source: Path | None = None):
        self.manifest = manifest
        self.source = source
        self._methods: dict[str, MethodDescriptor] = {}
        self._enums: dict[str, set[str]] = {}
        self._build_indexes()

    @classmethod
    def from_file(cls, path: str | Path) -> "ApiRegistry":
        source = Path(path).resolve()
        return cls(load_json(source), source)

    @property
    def identity(self) -> dict[str, Any]:
        canonical = self.manifest.get("canonicalSource") or {}
        return {
            "schemaVersion": self.manifest.get("schemaVersion"),
            "package": canonical.get("package"),
            "version": canonical.get("version"),
            "declarationSha256": canonical.get("declarationSha256"),
        }

    @property
    def method_count(self) -> int:
        return len(self._methods)

    def resolve_method(self, method_id: str) -> MethodDescriptor:
        try:
            return self._methods[method_id]
        except KeyError as exc:
            raise ContractError(f"Method ID is not present in the locked manifest: {method_id}") from exc

    def validate_enum_reference(self, reference: str) -> bool:
        if not ENUM_REFERENCE_RE.fullmatch(reference):
            return False
        enum_name, member_name = reference.split(".", 1)
        return member_name in self._enums.get(enum_name, set())

    def validate_plan(self, plan: dict[str, Any]) -> ValidationReport:
        issues: list[ValidationIssue] = []
        resolved: list[MethodDescriptor] = []
        digest = plan_digest(plan)

        def error(code: str, message: str, path: str) -> None:
            issues.append(ValidationIssue(code=code, message=message, path=path))

        if plan.get("schemaVersion") != PLAN_SCHEMA_VERSION:
            error("PLAN_SCHEMA", f"Expected {PLAN_SCHEMA_VERSION}", "$.schemaVersion")
        if not isinstance(plan.get("planId"), str) or not plan.get("planId", "").strip():
            error("PLAN_ID", "planId must be a non-empty string", "$.planId")

        risk = plan.get("risk")
        if risk not in SUPPORTED_RISKS:
            error("RISK", f"risk must be one of {sorted(SUPPORTED_RISKS)}", "$.risk")

        registry = plan.get("registry")
        if not isinstance(registry, dict):
            error("REGISTRY", "registry must be an object", "$.registry")
        else:
            for key, expected in self.identity.items():
                if registry.get(key) != expected:
                    error(
                        "REGISTRY_DRIFT",
                        f"Expected {key}={expected!r}, got {registry.get(key)!r}",
                        f"$.registry.{key}",
                    )

        identity = plan.get("identity")
        if not isinstance(identity, dict):
            error("IDENTITY", "identity must be an object", "$.identity")
        else:
            self._validate_identity(identity, risk, error)

        calls = plan.get("calls")
        if not isinstance(calls, list) or not calls:
            error("CALLS", "calls must be a non-empty array", "$.calls")
            calls = []

        seen_result_keys: set[str] = set()
        for index, call in enumerate(calls):
            path = f"$.calls[{index}]"
            if not isinstance(call, dict):
                error("CALL", "call must be an object", path)
                continue
            method_id = call.get("methodId")
            if not isinstance(method_id, str):
                error("METHOD_ID", "methodId must be a string", f"{path}.methodId")
                continue
            try:
                descriptor = self.resolve_method(method_id)
            except ContractError as exc:
                error("UNKNOWN_METHOD", str(exc), f"{path}.methodId")
                continue
            resolved.append(descriptor)
            if descriptor.deprecated:
                error("DEPRECATED_METHOD", f"{method_id} is deprecated", f"{path}.methodId")

            effect = call.get("effect")
            if effect not in SUPPORTED_EFFECTS:
                error("EFFECT", f"effect must be one of {sorted(SUPPORTED_EFFECTS)}", f"{path}.effect")
            classified = classify_method_effect(descriptor.method_name)
            if classified is None:
                review = call.get("effectReview")
                if not isinstance(review, dict) or review.get("classification") != effect:
                    error(
                        "EFFECT_REVIEW_REQUIRED",
                        "Unknown-effect method requires effectReview.classification matching effect",
                        f"{path}.effectReview",
                    )
                elif not all(isinstance(review.get(key), str) and review[key].strip() for key in ("reviewer", "rationale")):
                    error(
                        "EFFECT_REVIEW_INCOMPLETE",
                        "effectReview requires non-empty reviewer and rationale",
                        f"{path}.effectReview",
                    )
            elif effect != classified:
                error(
                    "EFFECT_MISMATCH",
                    f"{descriptor.method_name} is conservatively classified as {classified}",
                    f"{path}.effect",
                )

            if not isinstance(call.get("purpose"), str) or not call.get("purpose", "").strip():
                error("PURPOSE", "purpose must be a non-empty string", f"{path}.purpose")

            result_key = call.get("resultKey")
            if not isinstance(result_key, str) or not RESULT_KEY_RE.fullmatch(result_key):
                error("RESULT_KEY", "resultKey must be a simple unique identifier", f"{path}.resultKey")
            elif result_key in seen_result_keys:
                error("RESULT_KEY_DUPLICATE", f"Duplicate resultKey: {result_key}", f"{path}.resultKey")
            else:
                seen_result_keys.add(result_key)

            pick = call.get("pick")
            if pick is not None:
                if not isinstance(pick, list) or not pick:
                    error("PICK", "pick must be a non-empty array when supplied", f"{path}.pick")
                elif len(pick) > 64:
                    error("PICK", "pick is limited to 64 top-level fields", f"{path}.pick")
                else:
                    seen_pick: set[str] = set()
                    for pick_index, field_name in enumerate(pick):
                        if not isinstance(field_name, str) or not PICK_FIELD_RE.fullmatch(field_name):
                            error(
                                "PICK_FIELD",
                                "pick entries must be safe top-level property names",
                                f"{path}.pick[{pick_index}]",
                            )
                        elif field_name in seen_pick:
                            error("PICK_FIELD_DUPLICATE", f"Duplicate pick field: {field_name}", f"{path}.pick[{pick_index}]")
                        else:
                            seen_pick.add(field_name)

            args = call.get("args")
            if not isinstance(args, list):
                error("ARGS", "args must be an array", f"{path}.args")
            else:
                self._validate_argument_count(args, descriptor, path, error)
                for argument_index, argument in enumerate(args):
                    parameter = descriptor.parameters[argument_index] if argument_index < len(descriptor.parameters) else {}
                    self._validate_argument_values(
                        argument,
                        f"{path}.args[{argument_index}]",
                        error,
                        allow_undefined=parameter.get("optional") is True,
                    )

        save = plan.get("save")
        if not isinstance(save, bool):
            error("SAVE", "save must be a boolean", "$.save")
        self._validate_risk_rules(plan, calls, risk, save, error)

        recorded_digest = plan.get("planDigest")
        if not isinstance(recorded_digest, str):
            error("PLAN_DIGEST", "planDigest is required", "$.planDigest")
        elif recorded_digest.lower() != digest:
            error("PLAN_DIGEST_MISMATCH", f"Expected {digest}", "$.planDigest")

        valid = not any(issue.severity == "ERROR" for issue in issues)
        executable = valid and risk != "PERSISTENT_WRITE"
        return ValidationReport(
            valid=valid,
            executable=executable,
            plan_digest=digest,
            registry=self.identity,
            issues=issues,
            resolved_calls=resolved,
        )

    def _build_indexes(self) -> None:
        if self.manifest.get("schemaVersion") != "easyeda.api-manifest.v1":
            raise ContractError("Unsupported or missing API manifest schemaVersion")
        declarations = self.manifest.get("declarations") or {}
        classes = declarations.get("classes") or {}
        runtime_modules = self.manifest.get("runtimeModules") or {}
        class_to_runtime = {class_name: module for module, class_name in runtime_modules.items()}
        for class_name, declaration in classes.items():
            runtime_module = class_to_runtime.get(class_name)
            if not runtime_module:
                continue
            for method in declaration.get("methods") or []:
                if method.get("visibility") != "public":
                    continue
                method_id = method.get("id")
                if not method_id:
                    continue
                self._methods[method_id] = MethodDescriptor(
                    method_id=method_id,
                    class_name=class_name,
                    runtime_module=runtime_module,
                    method_name=method.get("name", ""),
                    parameters=tuple(method.get("parameters") or []),
                    returns_promise=bool(method.get("returnsPromise")),
                    release_tag=method.get("releaseTag"),
                    deprecated=bool(method.get("deprecated")),
                    signature=method.get("signature", ""),
                )
        for enum_name, declaration in (declarations.get("enums") or {}).items():
            if declaration.get("deprecated"):
                continue
            self._enums[enum_name] = {
                member["name"]
                for member in declaration.get("members") or []
                if member.get("name") and not member.get("deprecated")
            }
        if not self._methods:
            raise ContractError("API manifest contains no executable runtime methods")

    def _validate_identity(self, identity: dict[str, Any], risk: Any, error: Any) -> None:
        expected_keys = (
            "projectUuid",
            "documentUuid",
            "documentType",
            "capturedAt",
            "bridgeService",
            "windowId",
            "gatewayVersion",
            "bridgeScriptSha256",
        )
        for key in expected_keys:
            if key not in identity:
                error("IDENTITY_FIELD", f"Missing identity field {key}", f"$.identity.{key}")
        if identity.get("bridgeService") != SERVICE_ID:
            error("BRIDGE_IDENTITY", f"bridgeService must be {SERVICE_ID}", "$.identity.bridgeService")
        if identity.get("gatewayVersion") != GATEWAY_VERSION:
            error(
                "GATEWAY_VERSION",
                f"gatewayVersion must be {GATEWAY_VERSION}",
                "$.identity.gatewayVersion",
            )
        captured_at = identity.get("capturedAt")
        if not isinstance(captured_at, str) or not _is_iso8601(captured_at):
            error("CAPTURED_AT", "capturedAt must be an ISO-8601 timestamp", "$.identity.capturedAt")
        if risk in {"EPHEMERAL_WRITE", "PERSISTENT_WRITE"}:
            for key in ("projectUuid", "documentUuid", "documentType", "windowId"):
                if identity.get(key) is None or identity.get(key) == "":
                    error("WRITE_IDENTITY", f"{key} is mandatory for write plans", f"$.identity.{key}")
            bridge_sha = identity.get("bridgeScriptSha256")
            if not isinstance(bridge_sha, str) or not re.fullmatch(r"[0-9a-f]{64}", bridge_sha):
                error(
                    "BRIDGE_FINGERPRINT",
                    "Write plans require a lowercase SHA-256 bridgeScriptSha256",
                    "$.identity.bridgeScriptSha256",
                )

    def _validate_argument_count(
        self,
        args: list[Any],
        descriptor: MethodDescriptor,
        path: str,
        error: Any,
    ) -> None:
        parameters = descriptor.parameters
        required = sum(1 for parameter in parameters if not parameter.get("optional") and not parameter.get("rest"))
        has_rest = any(parameter.get("rest") for parameter in parameters)
        if len(args) < required or (not has_rest and len(args) > len(parameters)):
            maximum = "unbounded" if has_rest else str(len(parameters))
            error(
                "ARG_COUNT",
                f"{descriptor.method_id} expects {required}..{maximum} arguments, got {len(args)}",
                f"{path}.args",
            )

    def _validate_argument_values(
        self,
        value: Any,
        path: str,
        error: Any,
        *,
        allow_undefined: bool = False,
    ) -> None:
        if isinstance(value, list):
            for index, item in enumerate(value):
                self._validate_argument_values(item, f"{path}[{index}]", error)
            return
        if not isinstance(value, dict):
            return
        if "$undefined" in value:
            if set(value) != {"$undefined"} or value["$undefined"] is not True:
                error("UNDEFINED_REFERENCE", "Undefined reference must be exactly {\"$undefined\": true}", path)
            elif not allow_undefined:
                error("UNDEFINED_REFERENCE", "Undefined may be used only for an optional top-level argument", path)
            return
        if "$enum" in value:
            if set(value) != {"$enum"} or not isinstance(value["$enum"], str):
                error("ENUM_REFERENCE", "Enum reference must be exactly {\"$enum\": \"Enum.MEMBER\"}", path)
            elif not self.validate_enum_reference(value["$enum"]):
                error("ENUM_REFERENCE", f"Unknown enum member {value['$enum']!r}", path)
            return
        for key, item in value.items():
            if isinstance(key, str) and key.startswith("$"):
                error("RESERVED_ARGUMENT_KEY", f"Unsupported reserved key {key}", f"{path}.{key}")
            self._validate_argument_values(item, f"{path}.{key}", error)

    def _validate_risk_rules(self, plan: dict[str, Any], calls: Iterable[Any], risk: Any, save: Any, error: Any) -> None:
        effects = [call.get("effect") for call in calls if isinstance(call, dict)]
        if risk == "READ":
            if any(effect != "READ" for effect in effects):
                error("READ_PLAN_WRITE", "READ plans may contain only READ calls", "$.calls")
            if save is not False:
                error("READ_PLAN_SAVE", "READ plans require save=false", "$.save")
        elif risk == "EPHEMERAL_WRITE":
            if "WRITE" not in effects:
                error("EPHEMERAL_NO_WRITE", "EPHEMERAL_WRITE requires at least one WRITE call", "$.calls")
            if save is not False:
                error("EPHEMERAL_SAVE", "EPHEMERAL_WRITE requires save=false", "$.save")
            rollback = plan.get("rollback")
            if not isinstance(rollback, dict):
                error("ROLLBACK", "EPHEMERAL_WRITE requires rollback", "$.rollback")
            else:
                for key in ("strategy", "verification"):
                    if not isinstance(rollback.get(key), str) or not rollback[key].strip():
                        error("ROLLBACK", f"rollback.{key} must be non-empty", f"$.rollback.{key}")
            self._validate_write_scope_and_calls(plan, calls, risk, error)
        elif risk == "PERSISTENT_WRITE":
            if "WRITE" not in effects:
                error("PERSISTENT_NO_WRITE", "PERSISTENT_WRITE requires at least one WRITE call", "$.calls")
            if save is not True:
                error("PERSISTENT_SAVE", "PERSISTENT_WRITE requires save=true", "$.save")
            self._validate_write_scope_and_calls(plan, calls, risk, error)

    def _validate_write_scope_and_calls(
        self,
        plan: dict[str, Any],
        calls: Iterable[Any],
        risk: str,
        error: Any,
    ) -> None:
        scope = plan.get("scope")
        fields = scope.get("allowedFields") if isinstance(scope, dict) else None
        if not isinstance(fields, list) or not fields:
            error("WRITE_SCOPE", "Write plans require scope.allowedFields", "$.scope.allowedFields")
            fields = []
        elif not set(fields).issubset(PERSISTENT_WRITE_FIELDS):
            error(
                "WRITE_SCOPE",
                f"Writes are limited to {sorted(PERSISTENT_WRITE_FIELDS)}",
                "$.scope.allowedFields",
            )
        identity = plan.get("identity") if isinstance(plan.get("identity"), dict) else {}
        page_uuid = scope.get("pageUuid") if isinstance(scope, dict) else None
        if not isinstance(page_uuid, str) or not page_uuid:
            error("WRITE_PAGE", "Write scope requires a pageUuid", "$.scope.pageUuid")
        elif page_uuid != identity.get("documentUuid"):
            error("WRITE_PAGE", "scope.pageUuid must equal identity.documentUuid", "$.scope.pageUuid")
        if identity.get("documentType") != SCHEMATIC_PAGE_DOCUMENT_TYPE:
            error(
                "WRITE_DOCUMENT_TYPE",
                f"Procurement writes require schematic-page documentType={SCHEMATIC_PAGE_DOCUMENT_TYPE}",
                "$.identity.documentType",
            )

        allowed_properties = {
            PROCUREMENT_FIELD_TO_API_PROPERTY[field]
            for field in fields
            if field in PROCUREMENT_FIELD_TO_API_PROPERTY
        }
        save_call_count = 0
        for index, call in enumerate(calls):
            if not isinstance(call, dict) or call.get("effect") != "WRITE":
                continue
            method_id = call.get("methodId")
            path = f"$.calls[{index}]"
            if method_id == SCHEMATIC_SAVE_METHOD_ID:
                save_call_count += 1
                if risk != "PERSISTENT_WRITE":
                    error("EPHEMERAL_SAVE_CALL", "EPHEMERAL_WRITE cannot call SCH_Document.save", f"{path}.methodId")
                continue
            if method_id != COMPONENT_MODIFY_METHOD_ID:
                error(
                    "UNSUPPORTED_WRITE_METHOD",
                    "Write calls are limited to SCH_PrimitiveComponent.modify and guarded schematic save",
                    f"{path}.methodId",
                )
                continue
            args = call.get("args")
            properties = args[1] if isinstance(args, list) and len(args) > 1 else None
            if not isinstance(properties, dict) or not properties:
                error("WRITE_PROPERTIES", "Component modify requires a non-empty property object", f"{path}.args[1]")
                continue
            disallowed = set(properties) - allowed_properties
            if disallowed:
                error(
                    "PROTECTED_FIELD_WRITE",
                    f"Properties are outside the authorized procurement scope: {sorted(disallowed)}",
                    f"{path}.args[1]",
                )
        if risk == "PERSISTENT_WRITE" and save_call_count != 1:
            error(
                "PERSISTENT_SAVE_CALL",
                "PERSISTENT_WRITE requires exactly one SCH_Document.save call",
                "$.calls",
            )


def classify_method_effect(method_name: str) -> str | None:
    """Conservatively classify a method by its operation verb."""
    lowered = method_name.lower()
    if lowered.startswith(READ_PREFIXES):
        return "READ"
    if lowered.startswith(WRITE_PREFIXES):
        return "WRITE"
    return None


def _is_iso8601(value: str) -> bool:
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return True
