"""Validation against the locked canonical EasyEDA API manifest."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from .constants import (
    API_PLAN_SCHEMA,
    API_RISKS,
    BOM_WRITE_FIELDS,
    CALL_EFFECTS,
    READ_PREFIXES,
    WRITE_PREFIXES,
)
from .io_utils import is_sha256, sha256_json


def registry_identity(manifest: dict[str, Any]) -> dict[str, Any]:
    canonical = manifest.get("canonicalSource") or {}
    return {
        "schemaVersion": manifest.get("schemaVersion"),
        "package": canonical.get("package"),
        "version": canonical.get("version"),
        "declarationSha256": canonical.get("declarationSha256"),
    }


def build_method_index(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    classes = ((manifest.get("declarations") or {}).get("classes") or {})
    index: dict[str, dict[str, Any]] = {}
    for class_name, class_record in classes.items():
        if not isinstance(class_record, dict):
            continue
        for method in class_record.get("methods") or []:
            if not isinstance(method, dict) or not method.get("id"):
                continue
            index[method["id"]] = {
                "className": class_name,
                "classReleaseTag": class_record.get("releaseTag"),
                "documentationPath": class_record.get("documentationPath"),
                **method,
            }
    return index


def lookup_method(manifest: dict[str, Any], method_id: str) -> dict[str, Any] | None:
    return build_method_index(manifest).get(method_id)


def plan_digest(plan: dict[str, Any]) -> str:
    digest_input = deepcopy(plan)
    digest_input.pop("planDigest", None)
    digest_input.pop("authorization", None)
    return sha256_json(digest_input)


def _non_empty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _method_name(method_id: str) -> str:
    qualified = method_id.split("#", 1)[0]
    return qualified.rsplit(".", 1)[-1]


def infer_effect(method_id: str) -> str | None:
    name = _method_name(method_id)
    lowered = name.lower()
    if any(lowered.startswith(prefix) for prefix in WRITE_PREFIXES):
        return "WRITE"
    if any(lowered.startswith(prefix) for prefix in READ_PREFIXES):
        return "READ"
    return None


def _registry_errors(plan_registry: Any, expected: dict[str, Any]) -> list[str]:
    if not isinstance(plan_registry, dict):
        return ["registry must be an object"]
    errors: list[str] = []
    for field in ("schemaVersion", "package", "version", "declarationSha256"):
        if plan_registry.get(field) != expected.get(field):
            errors.append(f"registry.{field} does not match locked manifest")
    return errors


def validate_api_plan(
    plan: dict[str, Any], manifest: dict[str, Any]
) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    if plan.get("schemaVersion") != API_PLAN_SCHEMA:
        errors.append(f"schemaVersion must be {API_PLAN_SCHEMA}")
    if not _non_empty_string(plan.get("planId")):
        errors.append("planId must be a non-empty string")

    risk = plan.get("risk")
    if risk not in API_RISKS:
        errors.append("risk must be READ, EPHEMERAL_WRITE, or PERSISTENT_WRITE")
    errors.extend(_registry_errors(plan.get("registry"), registry_identity(manifest)))

    identity = plan.get("identity")
    if not isinstance(identity, dict):
        errors.append("identity must be an object")
    else:
        for field in ("projectUuid", "documentUuid", "documentType", "capturedAt"):
            if not _non_empty_string(identity.get(field)):
                errors.append(f"identity.{field} must be a non-empty string")
        bridge = identity.get("bridge")
        if not isinstance(bridge, dict) or bridge.get("service") != "easyeda-bridge":
            errors.append("identity.bridge.service must be easyeda-bridge")

    method_index = build_method_index(manifest)
    calls = plan.get("calls")
    contains_write = False
    if not isinstance(calls, list) or not calls:
        errors.append("calls must be a non-empty array")
        calls = []
    for index, call in enumerate(calls):
        prefix = f"calls[{index}]"
        if not isinstance(call, dict):
            errors.append(f"{prefix} must be an object")
            continue
        method_id = call.get("methodId")
        if not _non_empty_string(method_id):
            errors.append(f"{prefix}.methodId must be a non-empty string")
            continue
        method = method_index.get(method_id)
        if method is None:
            errors.append(f"{prefix}.methodId is absent from the locked manifest: {method_id}")
            continue
        if method.get("deprecated") is True:
            errors.append(f"{prefix}.methodId is deprecated: {method_id}")
        effect = call.get("effect")
        if effect not in CALL_EFFECTS:
            errors.append(f"{prefix}.effect must be READ or WRITE")
        if effect == "WRITE":
            contains_write = True
        inferred = infer_effect(method_id)
        if inferred and effect in CALL_EFFECTS and inferred != effect:
            errors.append(
                f"{prefix}.effect {effect} conflicts with inferred {inferred} for {method_id}"
            )
        if inferred is None:
            review = call.get("classificationReview")
            if not isinstance(review, dict) or not _non_empty_string(review.get("reason")):
                errors.append(
                    f"{prefix} uses an unknown-effect method and requires classificationReview.reason"
                )
        if not _non_empty_string(call.get("purpose")):
            errors.append(f"{prefix}.purpose must be a non-empty string")

    save = plan.get("save")
    if not isinstance(save, bool):
        errors.append("save must be boolean")

    if risk == "READ":
        if contains_write:
            errors.append("READ plan cannot contain WRITE calls")
        if save is not False:
            errors.append("READ plan must set save=false")
    elif risk == "EPHEMERAL_WRITE":
        rollback = plan.get("rollback")
        if not contains_write:
            errors.append("EPHEMERAL_WRITE plan requires at least one WRITE call")
        if save is not False:
            errors.append("EPHEMERAL_WRITE plan must set save=false")
        if not isinstance(rollback, dict) or rollback.get("required") is not True:
            errors.append("EPHEMERAL_WRITE plan requires rollback.required=true")
        elif not _non_empty_string(rollback.get("strategy")):
            errors.append("EPHEMERAL_WRITE plan requires rollback.strategy")
    elif risk == "PERSISTENT_WRITE":
        if not contains_write:
            errors.append("PERSISTENT_WRITE plan requires at least one WRITE call")
        scope = plan.get("scope")
        if not isinstance(scope, dict):
            errors.append("PERSISTENT_WRITE plan requires scope")
        else:
            fields = scope.get("fields")
            if not isinstance(fields, list) or not fields:
                errors.append("PERSISTENT_WRITE scope.fields must be a non-empty array")
            else:
                unexpected = sorted(set(fields) - BOM_WRITE_FIELDS)
                if unexpected:
                    errors.append(
                        "PERSISTENT_WRITE scope includes forbidden fields: "
                        + ", ".join(unexpected)
                    )
            if not is_sha256(scope.get("protectedFieldsDigest")):
                errors.append("PERSISTENT_WRITE requires scope.protectedFieldsDigest")
        if not is_sha256(plan.get("finalBomDigest")):
            errors.append("PERSISTENT_WRITE requires finalBomDigest")

    computed_digest = plan_digest(plan)
    supplied_digest = plan.get("planDigest")
    if supplied_digest is not None and supplied_digest.lower() != computed_digest:
        errors.append("planDigest does not match canonical plan content")

    executable = not errors
    if risk == "PERSISTENT_WRITE" and not errors:
        authorization = plan.get("authorization")
        authorization_ready = (
            isinstance(authorization, dict)
            and authorization.get("explicit") is True
            and _non_empty_string(authorization.get("acceptedAt"))
            and authorization.get("acceptedPlanDigest") == computed_digest
            and is_sha256(authorization.get("acceptanceReportSha256"))
            and save is True
        )
        if not authorization_ready:
            executable = False
            warnings.append(
                "persistent plan is structurally valid but not executable until exact-plan authorization, acceptance evidence, and save=true are present"
            )

    return {
        "valid": not errors,
        "executable": executable,
        "risk": risk,
        "planDigest": computed_digest,
        "registry": registry_identity(manifest),
        "errors": errors,
        "warnings": warnings,
        "methodCount": len(calls),
    }
