"""Pure public-context validator for ``creator-workflow``.

The shared materializer owns filesystem, Git, link, and protected consumer-path
checks.  This module validates only portable public configuration and returns a
canonical JSON context plus read and write ceilings.  Configuration is never an
execution or side-effect authorization.
"""

from __future__ import annotations

import copy
import math
import re
from pathlib import PurePosixPath
from typing import Any


REPOSITORY_SCHEMA = "agent-skills.repository/v1"
SKILL_SCHEMA = "agent-skills.creator-workflow/v1"
CONTEXT_SCHEMA = "agent-skills.creator-workflow-context/v1"
SKILL_NAME = "creator-workflow"

_ID_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_SCRIPT_RE = re.compile(r"^[a-z0-9][a-z0-9:_-]{0,79}$")
_WINDOWS_RESERVED = frozenset(
    {"con", "prn", "aux", "nul"}
    | {f"com{index}" for index in range(1, 10)}
    | {f"lpt{index}" for index in range(1, 10)}
)

FACT_ROLES = frozenset(
    {
        "brand-profile",
        "channel-profile",
        "package-manifest",
        "project-template",
        "publication-contract",
        "publication-template",
        "repository-instructions",
        "validation-instructions",
    }
)
PROFILE_ADAPTERS = frozenset(
    {"generic-content-project-v1", "pathnote-publication-v1"}
)
ROUTE_ADAPTERS = frozenset(
    {"package-script-v1", "package-script-v2", "selected-skill-v1"}
)
EFFECT_FIELDS = ("billable", "remote", "destructive", "publish")
ARGUMENT_KINDS = frozenset({"value", "input-path", "output-base", "target-path"})
CARDINALITIES = frozenset({"one", "many"})
OUTPUT_KINDS = frozenset({"exact", "suffix", "indexed-by-count"})
CONDITION_KINDS = frozenset({"always", "argument-present", "argument-true"})
VALUE_TYPES = frozenset({"bool", "int", "string"})


class ContextConfigError(ValueError):
    """Raised when public creator-workflow configuration is invalid."""


def _object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ContextConfigError(f"{label} must be an object")
    return value


def _exact_keys(
    value: dict[str, Any],
    *,
    allowed: frozenset[str],
    required: frozenset[str],
    label: str,
) -> None:
    unknown = [key for key in value if not isinstance(key, str) or key not in allowed]
    missing = [key for key in sorted(required) if key not in value]
    if unknown:
        rendered = ", ".join(sorted(repr(key) for key in unknown))
        raise ContextConfigError(f"{label} contains unknown fields: {rendered}")
    if missing:
        raise ContextConfigError(f"{label} is missing fields: {', '.join(missing)}")


def _string(value: Any, label: str, *, maximum: int = 240) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(value) > maximum
        or any(character in value for character in "\r\n\x00")
    ):
        raise ContextConfigError(
            f"{label} must be a non-empty, trimmed single-line string"
        )
    return value


def _public_fact_text(value: Any, label: str, *, maximum: int = 500) -> str:
    text = _string(value, label, maximum=maximum)
    folded = text.casefold()
    if (
        "://" in text
        or "-----begin " in folded
        or re.search(r"\b(?:bearer|basic)\s+\S+", text, re.IGNORECASE)
        or re.search(
            r"\b(?:api[_-]?key|access[_-]?token|refresh[_-]?token|client[_-]?secret|authorization|credential(?:s)?|secret|cookie|password)\s*[:=]",
            text,
            re.IGNORECASE,
        )
    ):
        raise ContextConfigError(f"{label} must not contain a URL or credential-like value")
    return text


def _public_scalar(value: Any, label: str) -> bool | int | float | str:
    if isinstance(value, str):
        return _public_fact_text(value, label, maximum=500)
    if isinstance(value, bool):
        return value
    if type(value) is int:
        return value
    if isinstance(value, float) and math.isfinite(value):
        return value
    raise ContextConfigError(f"{label} must be a finite JSON scalar")


def _matches_value_type(value: Any, value_type: str) -> bool:
    if value_type == "bool":
        return isinstance(value, bool)
    if value_type == "int":
        return type(value) is int
    return isinstance(value, str)


def _identifier(value: Any, label: str) -> str:
    text = _string(value, label, maximum=64)
    if _ID_RE.fullmatch(text) is None:
        raise ContextConfigError(f"{label} must be a lowercase hyphen identifier")
    return text


def _relative_path(value: Any, label: str) -> str:
    raw = _string(value, label, maximum=500)
    if (
        raw.startswith("/")
        or raw.endswith("/")
        or "\\" in raw
        or "//" in raw
        or re.match(r"^[A-Za-z]:", raw)
        or any(character in raw for character in '<>:"|?*')
    ):
        raise ContextConfigError(f"{label} must be a portable repository-relative path")
    parts = raw.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise ContextConfigError(f"{label} must be a portable repository-relative path")
    for part in parts:
        if (
            part.endswith((" ", "."))
            or any(ord(character) < 32 for character in part)
            or part.split(".", 1)[0].casefold() in _WINDOWS_RESERVED
        ):
            raise ContextConfigError(f"{label} contains a Windows-unsafe component")
    return PurePosixPath(*parts).as_posix()


def _parts(path: str) -> tuple[str, ...]:
    return tuple(part.casefold() for part in PurePosixPath(path).parts)


def _overlap(left: str, right: str) -> bool:
    left_parts, right_parts = _parts(left), _parts(right)
    shorter = min(len(left_parts), len(right_parts))
    return left_parts[:shorter] == right_parts[:shorter]


def _strict_descendant(child: str, parent: str) -> bool:
    child_parts, parent_parts = _parts(child), _parts(parent)
    return len(child_parts) > len(parent_parts) and child_parts[: len(parent_parts)] == parent_parts


def _repository_config(value: Any) -> dict[str, Any]:
    repository = _object(value, "repository_config")
    _exact_keys(
        repository,
        allowed=frozenset({"schema", "repository_id", "language", "timezone", "facts"}),
        required=frozenset({"schema", "repository_id"}),
        label="repository_config",
    )
    if repository["schema"] != REPOSITORY_SCHEMA:
        raise ContextConfigError(
            f"repository_config.schema must equal {REPOSITORY_SCHEMA!r}"
        )
    result: dict[str, Any] = {
        "schema": REPOSITORY_SCHEMA,
        "repository_id": _identifier(
            repository["repository_id"], "repository_config.repository_id"
        ),
        "facts": {},
    }
    for key in ("language", "timezone"):
        if key in repository:
            result[key] = _public_fact_text(
                repository[key], f"repository_config.{key}", maximum=80
            )
    facts = _object(repository.get("facts", {}), "repository_config.facts")
    for raw_id, raw_fact in facts.items():
        fact_id = _identifier(raw_id, "repository_config fact id")
        fact = _object(raw_fact, f"repository_config.facts.{fact_id}")
        _exact_keys(
            fact,
            allowed=frozenset({"path", "section", "description"}),
            required=frozenset({"path"}),
            label=f"repository_config.facts.{fact_id}",
        )
        normalized = {"path": _relative_path(fact["path"], f"fact {fact_id}.path")}
        for key in ("section", "description"):
            if key in fact:
                normalized[key] = _public_fact_text(
                    fact[key], f"fact {fact_id}.{key}", maximum=500
                )
        result["facts"][fact_id] = normalized
    result["facts"] = {key: result["facts"][key] for key in sorted(result["facts"])}
    return result


def _root_records(value: Any, label: str) -> list[dict[str, str]]:
    if not isinstance(value, list):
        raise ContextConfigError(f"{label} must be an array")
    records: list[dict[str, str]] = []
    seen_ids: set[str] = set()
    for index, raw in enumerate(value):
        item_label = f"{label}[{index}]"
        item = _object(raw, item_label)
        _exact_keys(
            item,
            allowed=frozenset({"id", "path"}),
            required=frozenset({"id", "path"}),
            label=item_label,
        )
        root_id = _identifier(item["id"], f"{item_label}.id")
        if root_id in seen_ids:
            raise ContextConfigError(f"{label} contains duplicate id {root_id!r}")
        seen_ids.add(root_id)
        records.append({"id": root_id, "path": _relative_path(item["path"], f"{item_label}.path")})
    return sorted(records, key=lambda item: item["id"])


def _fact_refs(value: Any, repository: dict[str, Any]) -> list[dict[str, str]]:
    if not isinstance(value, list):
        raise ContextConfigError("skill_config.repository_fact_refs must be an array")
    result: list[dict[str, str]] = []
    seen: set[str] = set()
    for index, raw in enumerate(value):
        label = f"skill_config.repository_fact_refs[{index}]"
        item = _object(raw, label)
        _exact_keys(
            item,
            allowed=frozenset({"fact_id", "role", "kind"}),
            required=frozenset({"fact_id", "role", "kind"}),
            label=label,
        )
        fact_id = _identifier(item["fact_id"], f"{label}.fact_id")
        if fact_id in seen:
            raise ContextConfigError(f"duplicate repository fact reference {fact_id!r}")
        if fact_id not in repository["facts"]:
            raise ContextConfigError(f"{label} references unknown fact {fact_id!r}")
        seen.add(fact_id)
        role = _string(item["role"], f"{label}.role", maximum=80)
        if role not in FACT_ROLES:
            raise ContextConfigError(f"{label}.role is unsupported")
        kind = _string(item["kind"], f"{label}.kind", maximum=20)
        if kind not in {"file", "collection"}:
            raise ContextConfigError(f"{label}.kind must be 'file' or 'collection'")
        result.append({"fact_id": fact_id, "role": role, "kind": kind})
    return sorted(result, key=lambda item: item["fact_id"])


def _effects(value: Any, label: str) -> dict[str, bool]:
    effects = _object(value, label)
    fields = frozenset(EFFECT_FIELDS)
    _exact_keys(effects, allowed=fields, required=fields, label=label)
    normalized: dict[str, bool] = {}
    for field in EFFECT_FIELDS:
        selected = effects[field]
        if not isinstance(selected, bool):
            raise ContextConfigError(f"{label}.{field} must be boolean")
        normalized[field] = selected
    return normalized


def _argument_bindings(value: Any, label: str) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise ContextConfigError(f"{label} must be an array")
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, raw in enumerate(value):
        item_label = f"{label}[{index}]"
        item = _object(raw, item_label)
        kind = _string(item.get("kind"), f"{item_label}.kind", maximum=30)
        if kind not in ARGUMENT_KINDS:
            raise ContextConfigError(f"{item_label}.kind is unsupported")
        allowed = {"key", "kind", "required", "cardinality"}
        required_fields = set(allowed)
        if kind == "input-path":
            allowed.add("authority")
            required_fields.add("authority")
        elif kind == "value":
            allowed.update({"value_type", "const"})
            required_fields.add("value_type")
        _exact_keys(
            item,
            allowed=frozenset(allowed),
            required=frozenset(required_fields),
            label=item_label,
        )
        key = _identifier(item["key"], f"{item_label}.key")
        if key in seen:
            raise ContextConfigError(f"{label} contains duplicate key {key!r}")
        seen.add(key)
        required = item["required"]
        if not isinstance(required, bool):
            raise ContextConfigError(f"{item_label}.required must be boolean")
        cardinality = _string(
            item["cardinality"], f"{item_label}.cardinality", maximum=10
        )
        if cardinality not in CARDINALITIES:
            raise ContextConfigError(
                f"{item_label}.cardinality must be 'one' or 'many'"
            )
        if kind == "output-base" and cardinality != "one":
            raise ContextConfigError(
                f"{item_label} output-base bindings must have cardinality 'one'"
            )
        normalized: dict[str, Any] = {
            "key": key,
            "kind": kind,
            "required": required,
            "cardinality": cardinality,
        }
        if kind == "input-path":
            authority = _string(
                item["authority"], f"{item_label}.authority", maximum=30
            )
            if authority not in {"managed-fact", "user-provided"}:
                raise ContextConfigError(
                    f"{item_label}.authority must be 'managed-fact' or 'user-provided'"
                )
            normalized["authority"] = authority
        elif kind == "value":
            value_type = _string(
                item["value_type"], f"{item_label}.value_type", maximum=10
            )
            if value_type not in VALUE_TYPES:
                raise ContextConfigError(
                    f"{item_label}.value_type must be 'bool', 'int', or 'string'"
                )
            normalized["value_type"] = value_type
            if "const" in item:
                if cardinality != "one":
                    raise ContextConfigError(
                        f"{item_label}.const requires cardinality 'one'"
                    )
                const = _public_scalar(item["const"], f"{item_label}.const")
                if not _matches_value_type(const, value_type):
                    raise ContextConfigError(
                        f"{item_label}.const must exactly match value_type {value_type!r}"
                    )
                normalized["const"] = const
        result.append(normalized)
    return sorted(result, key=lambda item: item["key"])


def _output_condition(
    value: Any,
    label: str,
    arguments: dict[str, dict[str, Any]],
) -> dict[str, str]:
    condition = _object(value, label)
    kind = _string(condition.get("kind"), f"{label}.kind", maximum=30)
    if kind not in CONDITION_KINDS:
        raise ContextConfigError(f"{label}.kind is unsupported")
    required = {"kind"} if kind == "always" else {"kind", "argument"}
    _exact_keys(
        condition,
        allowed=frozenset(required),
        required=frozenset(required),
        label=label,
    )
    normalized = {"kind": kind}
    if kind != "always":
        argument = _identifier(condition["argument"], f"{label}.argument")
        binding = arguments.get(argument)
        if binding is None:
            raise ContextConfigError(f"{label} references an unknown argument")
        if kind == "argument-true" and not (
            binding["kind"] == "value"
            and binding["cardinality"] == "one"
            and binding["value_type"] == "bool"
        ):
            raise ContextConfigError(
                f"{label} argument-true requires a scalar value argument"
            )
        normalized["argument"] = argument
    return normalized


def _output_bindings(
    value: Any,
    label: str,
    arguments: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise ContextConfigError(f"{label} must be an array")
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    used_bases: set[str] = set()
    for index, raw in enumerate(value):
        item_label = f"{label}[{index}]"
        item = _object(raw, item_label)
        kind = _string(item.get("kind"), f"{item_label}.kind", maximum=30)
        if kind not in OUTPUT_KINDS:
            raise ContextConfigError(f"{item_label}.kind is unsupported")
        allowed = {"id", "kind", "source_argument", "condition"}
        if kind == "suffix":
            allowed.add("suffix")
        elif kind == "indexed-by-count":
            allowed.add("count_argument")
        _exact_keys(
            item,
            allowed=frozenset(allowed),
            required=frozenset(allowed),
            label=item_label,
        )
        binding_id = _identifier(item["id"], f"{item_label}.id")
        if binding_id in seen:
            raise ContextConfigError(f"{label} contains duplicate id {binding_id!r}")
        seen.add(binding_id)
        source = _identifier(
            item["source_argument"], f"{item_label}.source_argument"
        )
        source_binding = arguments.get(source)
        if source_binding is None or source_binding["kind"] != "output-base":
            raise ContextConfigError(
                f"{item_label}.source_argument must reference an output-base argument"
            )
        used_bases.add(source)
        normalized: dict[str, Any] = {
            "id": binding_id,
            "kind": kind,
            "source_argument": source,
            "condition": _output_condition(
                item["condition"], f"{item_label}.condition", arguments
            ),
        }
        if kind == "suffix":
            suffix = _string(item["suffix"], f"{item_label}.suffix", maximum=80)
            if (
                "/" in suffix
                or "\\" in suffix
                or suffix in {".", ".."}
                or any(character in suffix for character in '<>:"|?*')
            ):
                raise ContextConfigError(
                    f"{item_label}.suffix must be a portable filename suffix"
                )
            normalized["suffix"] = suffix
        elif kind == "indexed-by-count":
            count_argument = _identifier(
                item["count_argument"], f"{item_label}.count_argument"
            )
            count_binding = arguments.get(count_argument)
            if count_binding is None or not (
                count_binding["kind"] == "value"
                and count_binding["cardinality"] == "one"
                and count_binding["required"]
                and count_binding["value_type"] == "int"
            ):
                raise ContextConfigError(
                    f"{item_label}.count_argument must reference a required scalar value argument"
                )
            normalized["count_argument"] = count_argument
        result.append(normalized)
    declared_bases = {
        key for key, binding in arguments.items() if binding["kind"] == "output-base"
    }
    if used_bases != declared_bases:
        unused = sorted(declared_bases - used_bases)
        raise ContextConfigError(
            f"{label} does not derive every output-base argument: {unused}"
        )
    return sorted(result, key=lambda item: item["id"])


def _billing_source(
    value: Any,
    label: str,
    arguments: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    source = _object(value, label)
    kind = _string(source.get("kind"), f"{label}.kind", maximum=20)
    if kind == "argument":
        _exact_keys(
            source,
            allowed=frozenset({"kind", "argument"}),
            required=frozenset({"kind", "argument"}),
            label=label,
        )
        argument = _identifier(source["argument"], f"{label}.argument")
        binding = arguments.get(argument)
        if binding is None or not (
            binding["kind"] == "value"
            and binding["cardinality"] == "one"
            and binding["required"]
        ):
            raise ContextConfigError(
                f"{label}.argument must reference a required scalar value argument"
            )
        return {"kind": "argument", "argument": argument}
    if kind == "literal":
        _exact_keys(
            source,
            allowed=frozenset({"kind", "value"}),
            required=frozenset({"kind", "value"}),
            label=label,
        )
        return {"kind": "literal", "value": _public_scalar(source["value"], f"{label}.value")}
    raise ContextConfigError(f"{label}.kind must be 'argument' or 'literal'")


def _billing_bindings(
    value: Any,
    label: str,
    arguments: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    bindings = _object(value, label)
    required = frozenset({"provider", "model_or_tier", "count", "request_bounds"})
    _exact_keys(bindings, allowed=required, required=required, label=label)
    raw_bounds = _object(bindings["request_bounds"], f"{label}.request_bounds")
    if not raw_bounds or len(raw_bounds) > 16:
        raise ContextConfigError(
            f"{label}.request_bounds must be a non-empty object with at most 16 fields"
        )
    bounds: dict[str, Any] = {}
    for raw_key, raw_source in raw_bounds.items():
        key = _identifier(raw_key, f"{label}.request_bounds key")
        if key in bounds:
            raise ContextConfigError(f"{label}.request_bounds contains duplicate keys")
        bounds[key] = _billing_source(
            raw_source, f"{label}.request_bounds.{key}", arguments
        )
    normalized = {
        "provider": _billing_source(bindings["provider"], f"{label}.provider", arguments),
        "model_or_tier": _billing_source(
            bindings["model_or_tier"], f"{label}.model_or_tier", arguments
        ),
        "count": _billing_source(bindings["count"], f"{label}.count", arguments),
        "request_bounds": {key: bounds[key] for key in sorted(bounds)},
    }
    for field in ("provider", "model_or_tier"):
        source = normalized[field]
        if source["kind"] == "literal" and not isinstance(source["value"], str):
            raise ContextConfigError(f"{label}.{field} literal must be a string")
        if (
            source["kind"] == "argument"
            and arguments[source["argument"]]["value_type"] != "string"
        ):
            raise ContextConfigError(
                f"{label}.{field} argument must have value_type 'string'"
            )
    provider = normalized["provider"]
    if provider["kind"] == "literal":
        provider["value"] = _identifier(
            provider["value"], f"{label}.provider.value"
        )
    count = normalized["count"]
    if count["kind"] == "literal" and not (
        type(count["value"]) is int and 1 <= count["value"] <= 32
    ):
        raise ContextConfigError(f"{label}.count literal must be an integer from 1 to 32")
    if (
        count["kind"] == "argument"
        and arguments[count["argument"]]["value_type"] != "int"
    ):
        raise ContextConfigError(
            f"{label}.count argument must have value_type 'int'"
        )
    return normalized


def _routes(value: Any, selected_facts: set[str]) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not value:
        raise ContextConfigError("skill_config.routes must be a non-empty array")
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, raw in enumerate(value):
        label = f"skill_config.routes[{index}]"
        route = _object(raw, label)
        adapter = _string(route.get("adapter"), f"{label}.adapter", maximum=80)
        if adapter not in ROUTE_ADAPTERS:
            raise ContextConfigError(f"{label}.adapter is unsupported")
        if adapter == "selected-skill-v1":
            allowed = required = frozenset({"id", "adapter", "skill", "effects"})
            _exact_keys(route, allowed=allowed, required=required, label=label)
            normalized: dict[str, Any] = {
                "id": _identifier(route["id"], f"{label}.id"),
                "adapter": adapter,
                "skill": _identifier(route["skill"], f"{label}.skill"),
                "effects": _effects(route["effects"], f"{label}.effects"),
            }
            if normalized["skill"] == SKILL_NAME:
                raise ContextConfigError(f"{label}.skill must not recursively select creator-workflow")
        elif adapter == "package-script-v1":
            allowed = required = frozenset(
                {
                    "id",
                    "adapter",
                    "manifest_fact_ref",
                    "script",
                    "subcommands",
                    "argument_keys",
                    "effects",
                }
            )
            _exact_keys(route, allowed=allowed, required=required, label=label)
            manifest_ref = _identifier(
                route["manifest_fact_ref"], f"{label}.manifest_fact_ref"
            )
            if manifest_ref not in selected_facts:
                raise ContextConfigError(f"{label} references an undeclared manifest fact")
            script = _string(route["script"], f"{label}.script", maximum=80)
            if _SCRIPT_RE.fullmatch(script) is None:
                raise ContextConfigError(f"{label}.script must be a safe package script token")
            raw_subcommands = route["subcommands"]
            if not isinstance(raw_subcommands, list) or not raw_subcommands:
                raise ContextConfigError(f"{label}.subcommands must be a non-empty array")
            subcommands = [_identifier(item, f"{label}.subcommands") for item in raw_subcommands]
            if len(set(subcommands)) != len(subcommands):
                raise ContextConfigError(f"{label}.subcommands contains duplicates")
            raw_argument_keys = route["argument_keys"]
            if not isinstance(raw_argument_keys, list):
                raise ContextConfigError(f"{label}.argument_keys must be an array")
            argument_keys = [
                _identifier(item, f"{label}.argument_keys")
                for item in raw_argument_keys
            ]
            if len(set(argument_keys)) != len(argument_keys):
                raise ContextConfigError(f"{label}.argument_keys contains duplicates")
            normalized = {
                "id": _identifier(route["id"], f"{label}.id"),
                "adapter": adapter,
                "manifest_fact_ref": manifest_ref,
                "script": script,
                "subcommands": sorted(subcommands),
                "argument_keys": sorted(argument_keys),
                "effects": _effects(route["effects"], f"{label}.effects"),
            }
        else:
            if "effects" not in route:
                raise ContextConfigError(f"{label} is missing fields: effects")
            effects = _effects(route.get("effects"), f"{label}.effects")
            base_fields = {
                "id",
                "adapter",
                "manifest_fact_ref",
                "script",
                "subcommands",
                "argument_bindings",
                "output_bindings",
                "effects",
            }
            allowed = set(base_fields)
            required = set(base_fields)
            allowed.add("observation_receipt_argument")
            if effects["billable"]:
                allowed.add("billing_bindings")
                required.add("billing_bindings")
            _exact_keys(route, allowed=allowed, required=required, label=label)
            manifest_ref = _identifier(
                route["manifest_fact_ref"], f"{label}.manifest_fact_ref"
            )
            if manifest_ref not in selected_facts:
                raise ContextConfigError(f"{label} references an undeclared manifest fact")
            script = _string(route["script"], f"{label}.script", maximum=80)
            if _SCRIPT_RE.fullmatch(script) is None:
                raise ContextConfigError(f"{label}.script must be a safe package script token")
            raw_subcommands = route["subcommands"]
            if not isinstance(raw_subcommands, list) or not raw_subcommands:
                raise ContextConfigError(f"{label}.subcommands must be a non-empty array")
            subcommands = [_identifier(item, f"{label}.subcommands") for item in raw_subcommands]
            if len(set(subcommands)) != len(subcommands):
                raise ContextConfigError(f"{label}.subcommands contains duplicates")
            argument_bindings = _argument_bindings(
                route["argument_bindings"], f"{label}.argument_bindings"
            )
            arguments_by_key = {
                item["key"]: item for item in argument_bindings
            }
            output_bindings = _output_bindings(
                route["output_bindings"],
                f"{label}.output_bindings",
                arguments_by_key,
            )
            normalized = {
                "id": _identifier(route["id"], f"{label}.id"),
                "adapter": adapter,
                "manifest_fact_ref": manifest_ref,
                "script": script,
                "subcommands": sorted(subcommands),
                "argument_bindings": argument_bindings,
                "output_bindings": output_bindings,
                "effects": effects,
            }
            if "observation_receipt_argument" in route:
                receipt_argument = _identifier(
                    route["observation_receipt_argument"],
                    f"{label}.observation_receipt_argument",
                )
                receipt_binding = arguments_by_key.get(receipt_argument)
                if receipt_binding is None or not (
                    receipt_binding["kind"] == "value"
                    and receipt_binding["required"]
                    and receipt_binding["cardinality"] == "one"
                    and receipt_binding["value_type"] == "string"
                    and "const" not in receipt_binding
                ):
                    raise ContextConfigError(
                        f"{label}.observation_receipt_argument must reference a required, non-constant scalar string value argument"
                    )
                if not (
                    effects["remote"]
                    and not effects["billable"]
                    and not effects["destructive"]
                    and not effects["publish"]
                ):
                    raise ContextConfigError(
                        f"{label}.observation_receipt_argument requires a remote, non-billable, non-destructive, non-publish route"
                    )
                if output_bindings or any(
                    item["kind"] in {"output-base", "target-path"}
                    for item in argument_bindings
                ):
                    raise ContextConfigError(
                        f"{label}.observation_receipt_argument routes must not declare outputs"
                    )
                normalized["observation_receipt_argument"] = receipt_argument
            if effects["billable"]:
                normalized["billing_bindings"] = _billing_bindings(
                    route["billing_bindings"],
                    f"{label}.billing_bindings",
                    arguments_by_key,
                )
        if normalized["id"] in seen:
            raise ContextConfigError(f"skill_config.routes contains duplicate id {normalized['id']!r}")
        seen.add(normalized["id"])
        result.append(normalized)
    return sorted(result, key=lambda item: item["id"])


def _require_fact_use(
    fact_id: str,
    *,
    role: str,
    kind: str,
    refs: dict[str, dict[str, str]],
    label: str,
) -> None:
    reference = refs.get(fact_id)
    if reference is None or reference["role"] != role or reference["kind"] != kind:
        raise ContextConfigError(
            f"{label} must reference a {kind} fact with role {role!r}"
        )


def _profiles(
    value: Any,
    roots: dict[str, dict[str, str]],
    fact_refs: dict[str, dict[str, str]],
    route_ids: set[str],
) -> tuple[list[dict[str, Any]], set[str]]:
    if not isinstance(value, list) or not value:
        raise ContextConfigError("skill_config.profiles must be a non-empty array")
    result: list[dict[str, Any]] = []
    used_roots: set[str] = set()
    seen: set[str] = set()
    for index, raw in enumerate(value):
        label = f"skill_config.profiles[{index}]"
        profile = _object(raw, label)
        adapter = _string(profile.get("adapter"), f"{label}.adapter", maximum=80)
        if adapter not in PROFILE_ADAPTERS:
            raise ContextConfigError(f"{label}.adapter is unsupported")
        if adapter == "generic-content-project-v1":
            allowed = required = frozenset(
                {
                    "id", "adapter", "project_root", "work_root", "output_root",
                    "template_fact_ref", "routes",
                }
            )
            _exact_keys(profile, allowed=allowed, required=required, label=label)
            references = {
                "project_root": "project_roots",
                "work_root": "work_roots",
                "output_root": "output_roots",
            }
            normalized: dict[str, Any] = {
                "id": _identifier(profile["id"], f"{label}.id"),
                "adapter": adapter,
            }
            for field, group in references.items():
                root_id = _identifier(profile[field], f"{label}.{field}")
                if root_id not in roots[group]:
                    raise ContextConfigError(f"{label}.{field} references an unknown root")
                normalized[field] = root_id
                used_roots.add(f"{group}:{root_id}")
            template = _identifier(profile["template_fact_ref"], f"{label}.template_fact_ref")
            _require_fact_use(
                template,
                role="project-template",
                kind="collection",
                refs=fact_refs,
                label=f"{label}.template_fact_ref",
            )
            normalized["template_fact_ref"] = template
        else:
            allowed = required = frozenset(
                {
                    "id", "adapter", "publication_root", "template_fact_ref",
                    "contract_fact_ref", "routes",
                }
            )
            _exact_keys(profile, allowed=allowed, required=required, label=label)
            root_id = _identifier(profile["publication_root"], f"{label}.publication_root")
            if root_id not in roots["publication_roots"]:
                raise ContextConfigError(f"{label}.publication_root references an unknown root")
            used_roots.add(f"publication_roots:{root_id}")
            template = _identifier(profile["template_fact_ref"], f"{label}.template_fact_ref")
            contract = _identifier(profile["contract_fact_ref"], f"{label}.contract_fact_ref")
            _require_fact_use(
                template,
                role="publication-template",
                kind="collection",
                refs=fact_refs,
                label=f"{label}.template_fact_ref",
            )
            _require_fact_use(
                contract,
                role="publication-contract",
                kind="file",
                refs=fact_refs,
                label=f"{label}.contract_fact_ref",
            )
            normalized = {
                "id": _identifier(profile["id"], f"{label}.id"),
                "adapter": adapter,
                "publication_root": root_id,
                "template_fact_ref": template,
                "contract_fact_ref": contract,
            }
        raw_routes = profile["routes"]
        if not isinstance(raw_routes, list) or not raw_routes:
            raise ContextConfigError(f"{label}.routes must be a non-empty array")
        profile_routes = [_identifier(item, f"{label}.routes") for item in raw_routes]
        if len(set(profile_routes)) != len(profile_routes):
            raise ContextConfigError(f"{label}.routes contains duplicates")
        unknown = sorted(set(profile_routes) - route_ids)
        if unknown:
            raise ContextConfigError(f"{label}.routes references unknown routes: {unknown}")
        normalized["routes"] = sorted(profile_routes)
        if normalized["id"] in seen:
            raise ContextConfigError(f"skill_config.profiles contains duplicate id {normalized['id']!r}")
        seen.add(normalized["id"])
        result.append(normalized)
    return sorted(result, key=lambda item: item["id"]), used_roots


def validate_materialized_context(
    repository_config: Any, skill_config: Any
) -> dict[str, Any]:
    """Validate public config without filesystem, Git, environment, or I/O access."""

    repository = _repository_config(repository_config)
    skill = _object(skill_config, "skill_config")
    _exact_keys(
        skill,
        allowed=frozenset(
            {"schema", "skill", "repository_fact_refs", "storage", "profiles", "routes", "protected_roots"}
        ),
        required=frozenset(
            {"schema", "skill", "repository_fact_refs", "storage", "profiles", "routes", "protected_roots"}
        ),
        label="skill_config",
    )
    if skill["schema"] != SKILL_SCHEMA:
        raise ContextConfigError(f"skill_config.schema must equal {SKILL_SCHEMA!r}")
    if skill["skill"] != SKILL_NAME:
        raise ContextConfigError(f"skill_config.skill must equal {SKILL_NAME!r}")

    fact_refs = _fact_refs(skill["repository_fact_refs"], repository)
    selected_facts = {item["fact_id"] for item in fact_refs}
    refs_by_id = {item["fact_id"]: item for item in fact_refs}
    for reference in fact_refs:
        fact = repository["facts"][reference["fact_id"]]
        if reference["kind"] == "collection" and "section" in fact:
            raise ContextConfigError(
                f"collection fact {reference['fact_id']!r} must not declare a section"
            )
    storage = _object(skill["storage"], "skill_config.storage")
    _exact_keys(
        storage,
        allowed=frozenset({"state_root", "project_roots", "work_roots", "output_roots", "publication_roots"}),
        required=frozenset({"state_root", "project_roots", "work_roots", "output_roots", "publication_roots"}),
        label="skill_config.storage",
    )
    normalized_storage: dict[str, Any] = {
        "state_root": _relative_path(storage["state_root"], "skill_config.storage.state_root")
    }
    roots: dict[str, dict[str, str]] = {}
    for group in ("project_roots", "work_roots", "output_roots", "publication_roots"):
        records = _root_records(storage[group], f"skill_config.storage.{group}")
        normalized_storage[group] = records
        roots[group] = {item["id"]: item["path"] for item in records}

    routes = _routes(skill["routes"], selected_facts)
    for route in routes:
        if route["adapter"] in {"package-script-v1", "package-script-v2"}:
            _require_fact_use(
                route["manifest_fact_ref"],
                role="package-manifest",
                kind="file",
                refs=refs_by_id,
                label=f"route {route['id']!r}.manifest_fact_ref",
            )
    profiles, used_roots = _profiles(
        skill["profiles"], roots, refs_by_id, {item["id"] for item in routes}
    )
    declared_roots = {
        f"{group}:{root_id}" for group, values in roots.items() for root_id in values
    }
    if used_roots != declared_roots:
        unused = sorted(declared_roots - used_roots)
        raise ContextConfigError(f"skill_config.storage contains unused roots: {unused}")

    write_paths = [normalized_storage["state_root"]]
    for values in roots.values():
        write_paths.extend(values.values())
    for index, left in enumerate(write_paths):
        for right in write_paths[index + 1 :]:
            if _overlap(left, right):
                raise ContextConfigError(f"managed write roots must be disjoint: {left!r} and {right!r}")

    raw_protected = skill["protected_roots"]
    if not isinstance(raw_protected, list):
        raise ContextConfigError("skill_config.protected_roots must be an array")
    protected = sorted(
        {_relative_path(item, "skill_config.protected_roots") for item in raw_protected},
        key=str.casefold,
    )
    if len(protected) != len(raw_protected):
        raise ContextConfigError("skill_config.protected_roots contains duplicates")
    for index, left in enumerate(protected):
        for right in protected[index + 1 :]:
            if _overlap(left, right):
                raise ContextConfigError(f"protected roots must be disjoint: {left!r} and {right!r}")
        for managed in write_paths:
            if _overlap(left, managed) and not _strict_descendant(left, managed):
                raise ContextConfigError(
                    f"protected root {left!r} may only overlap a write root as its strict descendant"
                )

    selected_repository = {key: copy.deepcopy(value) for key, value in repository.items() if key != "facts"}
    selected_repository["facts"] = {
        fact_id: copy.deepcopy(repository["facts"][fact_id]) for fact_id in sorted(selected_facts)
    }
    configuration = {
        "schema": SKILL_SCHEMA,
        "skill": SKILL_NAME,
        "repository_fact_refs": fact_refs,
        "storage": normalized_storage,
        "profiles": profiles,
        "routes": routes,
        "protected_roots": protected,
    }
    tracked_files: set[str] = set()
    tracked_collections: set[str] = set()
    for item in fact_refs:
        path = repository["facts"][item["fact_id"]]["path"]
        (tracked_files if item["kind"] == "file" else tracked_collections).add(path)
    return {
        "context": {
            "schema": CONTEXT_SCHEMA,
            "repository": selected_repository,
            "configuration": configuration,
            "adapter_catalog": {
                "profiles": sorted(PROFILE_ADAPTERS),
                "routes": sorted(ROUTE_ADAPTERS),
            },
        },
        "tracked_files": sorted(tracked_files),
        "tracked_collections": sorted(tracked_collections),
        "write_paths": sorted(set(write_paths)),
        "required_skills": sorted(
            {route["skill"] for route in routes if route["adapter"] == "selected-skill-v1"}
        ),
    }
