#!/usr/bin/env python3
"""Deterministic local ledger for creator-workflow.

This standard-library module never invokes a provider, browser, shell, Git,
network client, or subprocess.  It prepares canonical plans, enforces exact
authorization and dependency digests, and maintains a recoverable hash-chained
event ledger for work performed by the calling agent or a delegated tool.
"""

from __future__ import annotations

import argparse
import base64
import contextlib
import ctypes
import datetime as dt
import decimal
import errno
import hashlib
import importlib.util
import json
import os
import re
import stat
import sys
import tempfile
from collections.abc import Iterator as AbstractIterator, Mapping
from pathlib import Path, PurePosixPath
from typing import Any, Iterator, NoReturn


WORKFLOW_SCHEMA = "agent-skills.creator-workflow-ledger/v1"
PROPOSAL_SCHEMA = "agent-skills.creator-operation-proposal/v1"
PLAN_SCHEMA = "agent-skills.creator-operation-plan/v1"
AUTH_SCHEMA = "agent-skills.creator-operation-authorization/v1"
EVENT_SCHEMA = "agent-skills.creator-event/v1"
SNAPSHOT_SCHEMA = "agent-skills.creator-snapshot/v1"
JOURNAL_SCHEMA = "agent-skills.creator-journal/v1"
LOCK_SCHEMA = "agent-skills.creator-lock/v1"
ABSENT = "absent"

ID_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
HEX64_RE = re.compile(r"^[0-9a-f]{64}$")
WINDOWS_RESERVED = frozenset(
    {"con", "prn", "aux", "nul"}
    | {f"com{index}" for index in range(1, 10)}
    | {f"lpt{index}" for index in range(1, 10)}
)
KINDS = frozenset(
    {"research", "design", "create", "transform", "compose", "verify", "package", "publish", "maintain"}
)
GRANTS = frozenset({"billable", "retry", "publish", "destructive"})
STATES = frozenset(
    {"prepared", "authorized", "running", "dispatching", "submitted", "waiting", "succeeded", "failed", "unknown", "cancelled"}
)
TERMINAL = frozenset({"succeeded", "failed", "unknown", "cancelled"})
TRANSITIONS: dict[str | None, frozenset[str]] = {
    None: frozenset({"prepared"}),
    "prepared": frozenset({"authorized", "running", "cancelled"}),
    "authorized": frozenset({"running", "dispatching", "cancelled"}),
    "running": frozenset({"dispatching", "succeeded", "failed", "unknown", "cancelled"}),
    "dispatching": frozenset({"submitted", "succeeded", "unknown", "failed"}),
    "submitted": frozenset({"waiting", "succeeded", "failed", "unknown"}),
    "waiting": frozenset({"waiting", "succeeded", "failed", "unknown", "cancelled"}),
    "succeeded": frozenset(),
    "failed": frozenset(),
    "unknown": frozenset(),
    "cancelled": frozenset(),
}
SENSITIVE_KEYS = frozenset(
    {
        "access_token", "api_key", "apikey", "authorization", "authorization_header",
        "bearer_token", "body", "browser_state", "client_secret", "content", "cookie",
        "cookies", "credential", "credentials", "header", "headers", "password",
        "private_key", "prompt", "raw", "refresh_token", "request", "secret",
        "session_cookie", "signed_url", "token",
    }
)
BASE64_RE = re.compile(r"^[A-Za-z0-9+/]{256,}={0,2}$")
URLSAFE_BASE64_RE = re.compile(r"^[A-Za-z0-9_-]{256,}={0,2}$")
OPAQUE_RECEIPT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@/-]{0,199}$")
CURRENCY_RE = re.compile(r"^[A-Z]{3}$")
HIGH_CONFIDENCE_CREDENTIAL_RES = (
    re.compile(r"\bsk-(?:proj-|ant-)?[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\bsk_(?:live|test)_[A-Za-z0-9]{16,}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    re.compile(r"\bglpat-[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\b(?:hf_|gsk_)[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bxox[baprsc]-[A-Za-z0-9-]{20,}\b"),
    re.compile(r"\bAIza[A-Za-z0-9_-]{30,}\b"),
    re.compile(r"\bya29\.[A-Za-z0-9._-]{20,}\b"),
    re.compile(
        r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{10,}\b"
    ),
)
MANAGED_IGNORED_DIRECTORIES = frozenset(
    {".git", ".pytest_cache", ".venv", "__pycache__"}
)
MANAGED_IGNORED_SUFFIXES = frozenset({".pyc", ".pyo"})
MANAGED_MARKER_FILE = ".agent-skills-managed.json"

_CONTEXT_SPEC = importlib.util.spec_from_file_location(
    "creator_workflow_context_config", Path(__file__).with_name("context_config.py")
)
if _CONTEXT_SPEC is None or _CONTEXT_SPEC.loader is None:  # pragma: no cover
    raise RuntimeError("creator-workflow context validator is unavailable")
_CONTEXT_MODULE = importlib.util.module_from_spec(_CONTEXT_SPEC)
_CONTEXT_SPEC.loader.exec_module(_CONTEXT_MODULE)


class WorkflowError(RuntimeError):
    def __init__(self, code: str, message: str, **details: Any) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details


_MANAGED_CONTEXT_TOKEN = object()


class ManagedContext(Mapping[str, Any]):
    """Immutable handle to a materialized context that is reverified on use."""

    __slots__ = (
        "_creator_workflow_token",
        "_repository",
        "_context_path",
        "_raw_digest",
        "_wrapper_bytes",
    )

    def __init__(self, *_args: Any, **_kwargs: Any) -> None:
        raise TypeError("ManagedContext can only be created by load_managed_context")

    def _snapshot(self) -> dict[str, Any]:
        return json.loads(self._wrapper_bytes.decode("ascii"))

    def __getitem__(self, key: str) -> Any:
        return self._snapshot()[key]

    def __iter__(self) -> AbstractIterator[str]:
        return iter(self._snapshot())

    def __len__(self) -> int:
        return len(self._snapshot())

    def __eq__(self, other: object) -> bool:
        if isinstance(other, ManagedContext):
            return self._wrapper_bytes == other._wrapper_bytes
        return self._snapshot() == other

    def __setitem__(self, _key: str, _value: Any) -> NoReturn:
        raise TypeError("ManagedContext is immutable")

    def __setattr__(self, _name: str, _value: Any) -> NoReturn:
        raise TypeError("ManagedContext is immutable")


def _new_managed_context(
    repository: Path,
    context_path: Path,
    raw_digest: str,
    wrapper: dict[str, Any],
) -> ManagedContext:
    value = object.__new__(ManagedContext)
    object.__setattr__(value, "_creator_workflow_token", _MANAGED_CONTEXT_TOKEN)
    object.__setattr__(value, "_repository", Path(os.path.abspath(repository)))
    object.__setattr__(value, "_context_path", Path(os.path.abspath(context_path)))
    object.__setattr__(value, "_raw_digest", raw_digest)
    object.__setattr__(value, "_wrapper_bytes", _canonical(wrapper))
    return value


def _require_managed_context(
    value: Any, repo: Path | None = None
) -> dict[str, Any]:
    if not isinstance(value, ManagedContext) or getattr(
        value, "_creator_workflow_token", None
    ) is not _MANAGED_CONTEXT_TOKEN:
        _fail(
            "safety",
            "managed operations require a context loaded from a materialized Skill target",
        )
    if repo is not None:
        root = Path(os.path.abspath(repo))
        if not _same_path(root, value._repository):
            _fail("safety", "managed context is bound to a different repository")
        refreshed = load_managed_context(root, value._context_path)
        if refreshed._raw_digest != value._raw_digest:
            _fail("conflict", "managed context bytes changed; re-load context")
        return refreshed._snapshot()
    return value._snapshot()


def _fail(code: str, message: str, **details: Any) -> NoReturn:
    raise WorkflowError(code, message, **details)


def _canonical(value: Any) -> bytes:
    try:
        return (
            json.dumps(
                value,
                ensure_ascii=True,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
            + "\n"
        ).encode("ascii")
    except (TypeError, ValueError) as exc:
        _fail("malformed", "value is not canonical JSON", reason=str(exc))


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _digest_value(value: Any) -> str:
    return _sha(_canonical(value))


def _object(value: Any, label: str, allowed: set[str], required: set[str]) -> dict[str, Any]:
    if not isinstance(value, dict):
        _fail("malformed", f"{label} must be an object")
    unknown = sorted(set(value) - allowed)
    missing = sorted(required - set(value))
    if unknown:
        _fail("malformed", f"{label} contains unknown fields", fields=unknown)
    if missing:
        _fail("malformed", f"{label} is missing required fields", fields=missing)
    return value


def _string(value: Any, label: str, *, maximum: int = 500, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or (not allow_empty and not value) or value != value.strip() or len(value) > maximum or "\x00" in value:
        _fail("malformed", f"{label} must be a trimmed string")
    return value


def _id(value: Any, label: str) -> str:
    text = _string(value, label, maximum=80)
    if ID_RE.fullmatch(text) is None:
        _fail("malformed", f"{label} must be lowercase hyphen-case")
    return text


def _digest(value: Any, label: str, *, absent: bool = False) -> str:
    text = _string(value, label, maximum=64)
    if absent and text == ABSENT:
        return text
    if HEX64_RE.fullmatch(text) is None:
        _fail("malformed", f"{label} must be a SHA-256 digest")
    return text


def _time(value: Any, label: str) -> str:
    text = _string(value, label, maximum=64)
    try:
        parsed = dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        _fail("malformed", f"{label} must be ISO-8601")
    if parsed.tzinfo is None:
        _fail("malformed", f"{label} must include a timezone")
    return text


def _safe_relative(value: Any, label: str) -> str:
    raw = _string(value, label, maximum=500)
    if (
        raw.startswith("/")
        or raw.endswith("/")
        or "\\" in raw
        or "//" in raw
        or re.match(r"^[A-Za-z]:", raw)
        or any(character in raw for character in '<>:"|?*')
    ):
        _fail("safety", f"{label} must be a portable repository-relative path")
    parts = raw.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        _fail("safety", f"{label} must be a portable repository-relative path")
    for part in parts:
        if (
            part.endswith((" ", "."))
            or any(ord(character) < 32 for character in part)
            or part.split(".", 1)[0].casefold() in WINDOWS_RESERVED
        ):
            _fail("safety", f"{label} contains a Windows-unsafe component")
    return PurePosixPath(*parts).as_posix()


def _reject_sensitive(
    value: Any,
    label: str = "value",
    *,
    _depth: int = 0,
    _counter: list[int] | None = None,
) -> None:
    if _counter is None:
        _counter = [0]
    _counter[0] += 1
    if _depth > 20 or _counter[0] > 2000:
        _fail("safety", f"{label} exceeds the durable JSON complexity limit")
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                _fail("malformed", f"{label} has a non-string key")
            normalized = re.sub(r"[^a-z0-9]+", "_", key.casefold()).strip("_")
            if normalized in SENSITIVE_KEYS or any(
                token in normalized
                for token in (
                    "access_token", "api_key", "auth_header", "authorization",
                    "credential", "private_key", "refresh_token", "secret_key",
                )
            ):
                _fail("safety", f"{label} contains prohibited sensitive field", field=key)
            _reject_sensitive(item, f"{label}.{key}", _depth=_depth + 1, _counter=_counter)
    elif isinstance(value, list):
        for item in value:
            if isinstance(item, str) and re.search(
                r"(?:^|\s)--(?:api[-_]?key|access[-_]?token|refresh[-_]?token|client[-_]?secret|authorization|credential(?:s)?|secret|cookie|password|header)(?:[=\s]|$)",
                item,
                re.IGNORECASE,
            ):
                _fail("safety", f"{label} contains a prohibited credential argument")
        for index, item in enumerate(value):
            _reject_sensitive(item, f"{label}[{index}]", _depth=_depth + 1, _counter=_counter)
    elif isinstance(value, str):
        if len(value) > 8192:
            _fail("safety", f"{label} exceeds the durable string limit")
        folded = value.casefold()
        if (
            BASE64_RE.fullmatch(value)
            or URLSAFE_BASE64_RE.fullmatch(value)
            or "-----begin " in folded
            or folded.startswith(("bearer ", "basic ", "data:"))
            or re.search(
                r"(?:^|\s)--(?:api[-_]?key|access[-_]?token|refresh[-_]?token|client[-_]?secret|authorization|credential(?:s)?|secret|cookie|password|header)(?:[=\s]|$)",
                value,
                re.IGNORECASE,
            )
            or re.search(
                r"\b(?:authorization|api[_-]?key|access[_-]?token|refresh[_-]?token|client[_-]?secret|credential(?:s)?|secret|cookie|password)\s*[:=]\s*\S+",
                value,
                re.IGNORECASE,
            )
            or re.search(r"https?://[^/\s:@]+:[^/\s@]+@", value, re.IGNORECASE)
            or re.search(r"https?://[^\s?#]+[?#]", value, re.IGNORECASE)
            or any(pattern.search(value) for pattern in HIGH_CONFIDENCE_CREDENTIAL_RES)
        ):
            _fail(
                "safety",
                f"{label} appears to contain sensitive, secret, or encoded payload data",
            )


def _reject_event_payload(payload: Any, state: str) -> None:
    if not isinstance(payload, dict):
        _fail("integrity", "event payload must be an object")
    if state == "authorized":
        # The only allowed authorization-shaped object is validated against the
        # exact plan by reduce_events.  Scan every sibling normally.
        for key, value in payload.items():
            if key != "authorization":
                _reject_sensitive(value, f"event.payload.{key}")
        return
    _reject_sensitive(payload, "event.payload")


def _opaque_receipt(value: Any, label: str) -> str:
    receipt = _string(value, label, maximum=200)
    _reject_sensitive(receipt, label)
    if (
        OPAQUE_RECEIPT_RE.fullmatch(receipt) is None
        or "://" in receipt
        or receipt.casefold().startswith(("bearer", "basic"))
    ):
        _fail("integrity", f"{label} must be a safe opaque receipt identifier")
    return receipt


def _package_arguments(
    value: Any, label: str, allowed_keys: set[str]
) -> dict[str, Any]:
    arguments = _object(value, label, allowed_keys, set())
    normalized: dict[str, Any] = {}
    for raw_key in sorted(arguments):
        key = _id(raw_key, f"{label} key")
        item = arguments[raw_key]
        values = item if isinstance(item, list) else [item]
        if len(values) > 32:
            _fail("safety", f"{label}.{key} has too many values")
        for entry in values:
            if entry is None or isinstance(entry, (bool, int)):
                continue
            if isinstance(entry, float):
                if not (float("-inf") < entry < float("inf")):
                    _fail("malformed", f"{label}.{key} must be finite")
                continue
            if isinstance(entry, str):
                _string(entry, f"{label}.{key}", maximum=500, allow_empty=False)
                continue
            _fail(
                "malformed",
                f"{label}.{key} must contain only JSON scalar values",
            )
        normalized[key] = item
    return normalized


def _package_scalar(value: Any, label: str) -> bool | int | float | str:
    if isinstance(value, bool) or type(value) is int:
        return value
    if isinstance(value, float):
        if not (float("-inf") < value < float("inf")):
            _fail("malformed", f"{label} must be finite")
        return value
    if isinstance(value, str):
        return _string(value, label, maximum=500, allow_empty=False)
    _fail("malformed", f"{label} must be a JSON scalar")


def _matches_package_value_type(value: Any, value_type: str) -> bool:
    if value_type == "bool":
        return isinstance(value, bool)
    if value_type == "int":
        return type(value) is int
    return isinstance(value, str)


def _bound_argument_values(
    arguments: dict[str, Any],
    binding: dict[str, Any],
    label: str,
) -> list[bool | int | float | str]:
    key = binding["key"]
    if key not in arguments:
        if binding["required"]:
            _fail("safety", f"{label}.{key} is required by the selected route")
        return []
    raw = arguments[key]
    if binding["cardinality"] == "one":
        if isinstance(raw, list):
            _fail("malformed", f"{label}.{key} must be a scalar")
        values = [_package_scalar(raw, f"{label}.{key}")]
    else:
        if not isinstance(raw, list) or not raw or len(raw) > 32:
            _fail(
                "malformed",
                f"{label}.{key} must be a non-empty array with at most 32 values",
            )
        values = [
            _package_scalar(item, f"{label}.{key}") for item in raw
        ]
    if binding["kind"] in {"input-path", "output-base", "target-path"}:
        normalized: list[str] = []
        for value in values:
            if not isinstance(value, str):
                _fail("malformed", f"{label}.{key} must contain only paths")
            normalized.append(_safe_relative(value, f"{label}.{key}"))
        return normalized
    for value in values:
        if not _matches_package_value_type(value, binding["value_type"]):
            _fail(
                "malformed",
                f"{label}.{key} must exactly match declared value_type {binding['value_type']!r}",
            )
    if "const" in binding and not _same_json_scalar(values[0], binding["const"]):
        _fail(
            "safety",
            f"{label}.{key} must equal its configured constant",
        )
    return values


def _condition_enabled(
    condition: dict[str, Any], arguments: dict[str, Any]
) -> bool:
    if condition["kind"] == "always":
        return True
    argument = condition["argument"]
    if condition["kind"] == "argument-present":
        return argument in arguments
    return arguments.get(argument) is True


def _indexed_target(path: str, index: int) -> str:
    source = PurePosixPath(path)
    suffix = source.suffix if source.name != source.suffix else ""
    stem = source.name[: -len(suffix)] if suffix else source.name
    name = f"{stem}-{index}{suffix}"
    return _safe_relative(
        (source.parent / name).as_posix(), "indexed output target"
    )


def _resolved_billing_source(
    source: dict[str, Any], arguments: dict[str, Any]
) -> bool | int | float | str:
    if source["kind"] == "literal":
        return source["value"]
    argument = source["argument"]
    if argument not in arguments:
        _fail("safety", "billing source argument is missing", argument=argument)
    return _package_scalar(arguments[argument], f"billing argument {argument}")


def _same_json_scalar(left: Any, right: Any) -> bool:
    return type(left) is type(right) and left == right


def _validate_package_route_bindings(
    plan: dict[str, Any],
    route: dict[str, Any],
    manifest_path: str,
) -> None:
    parameters = _object(
        plan["parameters"],
        "plan.parameters",
        {"subcommand", "arguments"},
        {"subcommand", "arguments"},
    )
    subcommand = _id(parameters["subcommand"], "plan.parameters.subcommand")
    if subcommand not in route["subcommands"]:
        _fail(
            "safety",
            "package subcommand is not enabled by the selected route",
            route_id=route["id"],
            subcommand=subcommand,
        )
    bindings = {item["key"]: item for item in route["argument_bindings"]}
    arguments = _object(
        parameters["arguments"],
        "plan.parameters.arguments",
        set(bindings),
        set(),
    )
    values = {
        key: _bound_argument_values(
            arguments, binding, "plan.parameters.arguments"
        )
        for key, binding in bindings.items()
    }

    receipt_argument = route.get("observation_receipt_argument")
    if receipt_argument is not None:
        if "observation_of" not in plan:
            _fail(
                "safety",
                "selected package route is observation-only",
                route_id=route["id"],
            )
        receipt_values = values[receipt_argument]
        if (
            len(receipt_values) != 1
            or not isinstance(receipt_values[0], str)
            or receipt_values[0] != plan.get("observed_receipt")
        ):
            _fail(
                "safety",
                "observation receipt argument must exactly match observed_receipt",
            )
    elif "observation_of" in plan:
        _fail(
            "safety",
            "package observation requires an observation-only receipt-bound route",
        )

    expected_inputs: list[tuple[str, str]] = [(manifest_path, "managed-fact")]
    for key, binding in bindings.items():
        if binding["kind"] == "input-path":
            expected_inputs.extend(
                (path, binding["authority"]) for path in values[key]
            )
    folded_inputs: set[str] = set()
    for path, _authority in expected_inputs:
        folded = path.casefold()
        if folded in folded_inputs:
            _fail(
                "safety",
                "package arguments bind the same input path more than once",
                path=path,
            )
        folded_inputs.add(folded)
    actual_inputs = [(item["path"], item["authority"]) for item in plan["inputs"]]
    if sorted(expected_inputs, key=lambda item: item[0].casefold()) != actual_inputs:
        _fail(
            "safety",
            "package plan inputs must exactly equal its manifest and input-path arguments",
        )

    expected_targets: list[str] = []
    for key, binding in bindings.items():
        if binding["kind"] == "target-path":
            expected_targets.extend(values[key])
    enabled_bases: set[str] = set()
    for output in route["output_bindings"]:
        if not _condition_enabled(output["condition"], arguments):
            continue
        source = output["source_argument"]
        if not values[source]:
            _fail(
                "safety",
                "enabled output binding requires its output-base argument",
                binding=output["id"],
                argument=source,
            )
        enabled_bases.add(source)
        base = values[source][0]
        assert isinstance(base, str)
        if output["kind"] == "exact":
            expected_targets.append(base)
        elif output["kind"] == "suffix":
            expected_targets.append(
                _safe_relative(base + output["suffix"], "suffixed output target")
            )
        else:
            count_values = values[output["count_argument"]]
            count = count_values[0] if count_values else None
            if type(count) is not int or not 1 <= count <= 32:
                _fail(
                    "malformed",
                    "indexed output count must be an integer from 1 to 32",
                    binding=output["id"],
                )
            if count == 1:
                expected_targets.append(base)
            else:
                expected_targets.extend(
                    _indexed_target(base, index) for index in range(1, count + 1)
                )
    for key, binding in bindings.items():
        if (
            binding["kind"] == "output-base"
            and values[key]
            and key not in enabled_bases
        ):
            _fail(
                "safety",
                "output-base argument has no enabled derivation",
                argument=key,
            )
    folded_targets: set[str] = set()
    for path in expected_targets:
        folded = path.casefold()
        if folded in folded_targets:
            _fail(
                "safety",
                "package output bindings derive duplicate target paths",
                path=path,
            )
        folded_targets.add(folded)
    actual_targets = [item["path"] for item in plan["targets"]]
    if sorted(expected_targets, key=str.casefold) != actual_targets:
        _fail(
            "safety",
            "package plan targets must exactly equal its target arguments and derived outputs",
        )

    if route["effects"]["billable"]:
        billing_bindings = route["billing_bindings"]
        expected_provider = _resolved_billing_source(
            billing_bindings["provider"], arguments
        )
        expected_model = _resolved_billing_source(
            billing_bindings["model_or_tier"], arguments
        )
        expected_count = _resolved_billing_source(
            billing_bindings["count"], arguments
        )
        expected_bounds = {
            key: _resolved_billing_source(source, arguments)
            for key, source in billing_bindings["request_bounds"].items()
        }
        billing = plan.get("billing")
        if not isinstance(billing, dict):
            _fail("authorization", "billable package route requires billing")
        if not (
            _same_json_scalar(billing.get("provider"), expected_provider)
            and _same_json_scalar(billing.get("model_or_tier"), expected_model)
            and _same_json_scalar(billing.get("count"), expected_count)
            and set(billing.get("request_bounds", {})) == set(expected_bounds)
            and all(
                _same_json_scalar(billing["request_bounds"][key], value)
                for key, value in expected_bounds.items()
            )
        ):
            _fail(
                "authorization",
                "package billing must exactly match its declarative argument bindings",
            )


def _billing(value: Any, label: str) -> dict[str, Any]:
    record = _object(
        value,
        label,
        {
            "provider",
            "model_or_tier",
            "count",
            "request_bounds",
            "cost_boundary",
            "one_attempt_max",
        },
        {
            "provider",
            "model_or_tier",
            "count",
            "request_bounds",
            "cost_boundary",
            "one_attempt_max",
        },
    )
    provider = _id(record["provider"], f"{label}.provider")
    model_or_tier = _string(
        record["model_or_tier"], f"{label}.model_or_tier", maximum=160
    )
    if type(record["count"]) is not int or not 1 <= record["count"] <= 32:
        _fail("malformed", f"{label}.count must be an integer from 1 to 32")
    if record["one_attempt_max"] is not True:
        _fail("authorization", f"{label}.one_attempt_max must be true")
    bounds = record["request_bounds"]
    if not isinstance(bounds, dict) or not bounds or len(bounds) > 16:
        _fail("malformed", f"{label}.request_bounds must be a non-empty bounded object")
    normalized_bounds = _package_arguments(
        bounds,
        f"{label}.request_bounds",
        {_id(key, f"{label}.request_bounds key") for key in bounds},
    )
    boundary = _object(
        record["cost_boundary"],
        f"{label}.cost_boundary",
        {"kind", "currency", "amount"},
        {"kind", "currency", "amount"},
    )
    kind = _string(boundary["kind"], f"{label}.cost_boundary.kind", maximum=20)
    if kind not in {"hard-cap", "estimate-only"}:
        _fail("malformed", f"{label}.cost_boundary.kind is unsupported")
    currency = _string(
        boundary["currency"], f"{label}.cost_boundary.currency", maximum=3
    )
    if CURRENCY_RE.fullmatch(currency) is None:
        _fail("malformed", f"{label}.cost_boundary.currency must be ISO-4217 style")
    amount = _string(boundary["amount"], f"{label}.cost_boundary.amount", maximum=32)
    try:
        parsed_amount = decimal.Decimal(amount)
    except decimal.InvalidOperation:
        _fail("malformed", f"{label}.cost_boundary.amount must be a decimal string")
    if not parsed_amount.is_finite() or parsed_amount <= 0:
        _fail("malformed", f"{label}.cost_boundary.amount must be positive")
    return {
        "provider": provider,
        "model_or_tier": model_or_tier,
        "count": record["count"],
        "request_bounds": normalized_bounds,
        "cost_boundary": {"kind": kind, "currency": currency, "amount": amount},
        "one_attempt_max": True,
    }


def _normalize_refs(value: Any, label: str, *, before: bool = False) -> list[dict[str, str]]:
    if not isinstance(value, list):
        _fail("malformed", f"{label} must be an array")
    result: list[dict[str, str]] = []
    paths: set[str] = set()
    key = "before_sha256" if before else "sha256"
    for index, raw in enumerate(value):
        allowed = {"path", key} if before else {"path", key, "authority"}
        item = _object(raw, f"{label}[{index}]", allowed, allowed)
        path = _safe_relative(item["path"], f"{label}[{index}].path")
        path_key = path.casefold()
        if path_key in paths:
            _fail("malformed", f"{label} contains duplicate path", path=path)
        paths.add(path_key)
        normalized = {"path": path, key: _digest(item[key], f"{label}[{index}].{key}", absent=before)}
        if not before:
            authority = _string(item["authority"], f"{label}[{index}].authority", maximum=30)
            if authority not in {"managed-fact", "user-provided"}:
                _fail("malformed", f"{label}[{index}].authority is unsupported")
            normalized["authority"] = authority
        result.append(normalized)
    result = sorted(result, key=lambda item: item["path"].casefold())
    if before:
        for index, left in enumerate(result):
            for right in result[index + 1 :]:
                if _paths_overlap(left["path"], right["path"]):
                    _fail(
                        "safety",
                        f"{label} contains overlapping targets",
                        paths=[left["path"], right["path"]],
                    )
    return result


def _success_artifacts(value: Any, label: str) -> list[dict[str, str]]:
    if not isinstance(value, list):
        _fail("integrity", f"{label} must be an array")
    artifacts: list[dict[str, str]] = []
    paths: set[str] = set()
    for index, raw in enumerate(value):
        item_label = f"{label}[{index}]"
        item = _object(raw, item_label, {"path", "sha256"}, {"path", "sha256"})
        path = _safe_relative(item["path"], f"{item_label}.path")
        folded = path.casefold()
        if folded in paths:
            _fail("integrity", f"{label} contains duplicate paths", path=path)
        paths.add(folded)
        artifacts.append(
            {
                "path": path,
                "sha256": _digest(item["sha256"], f"{item_label}.sha256"),
            }
        )
    return sorted(artifacts, key=lambda item: item["path"].casefold())


def prepare_operation(proposal: Any, context_digest: str) -> dict[str, Any]:
    """Return a canonical plan.  This function performs no filesystem writes."""

    _digest(context_digest, "context_digest")
    obj = _object(
        proposal,
        "proposal",
        {
            "schema", "workflow_id", "operation_id", "kind", "profile_id", "route_id",
            "summary", "inputs", "targets", "dependencies", "parameters", "billable",
            "destructive", "remote", "retry_of", "observation_of",
            "observed_receipt", "billing",
        },
        {
            "schema", "workflow_id", "operation_id", "kind", "profile_id", "route_id",
            "summary", "inputs", "targets", "dependencies", "parameters", "billable",
            "destructive", "remote",
        },
    )
    if obj["schema"] != PROPOSAL_SCHEMA:
        _fail("malformed", "proposal schema is unsupported")
    _reject_sensitive(obj, "proposal")
    kind = _string(obj["kind"], "proposal.kind", maximum=20)
    if kind not in KINDS:
        _fail("malformed", "proposal.kind is unsupported")
    for key in ("billable", "destructive", "remote"):
        if not isinstance(obj[key], bool):
            _fail("malformed", f"proposal.{key} must be boolean")
    if not isinstance(obj["parameters"], dict):
        _fail("malformed", "proposal.parameters must be an object")
    if kind == "publish" and not obj["remote"]:
        _fail("malformed", "publish operations must declare remote work")
    billing: dict[str, Any] | None = None
    if obj["billable"]:
        if "billing" not in obj:
            _fail(
                "authorization",
                "billable work requires provider, tier, count, request bounds, cost boundary, and one-attempt maximum",
            )
        billing = _billing(obj["billing"], "proposal.billing")
    elif "billing" in obj:
        _fail("malformed", "non-billable work must not declare proposal.billing")
    operation_id = _id(obj["operation_id"], "proposal.operation_id")
    dependencies = obj["dependencies"]
    if not isinstance(dependencies, list):
        _fail("malformed", "proposal.dependencies must be an array")
    normalized_dependencies = [_id(item, "proposal.dependencies") for item in dependencies]
    if len(set(normalized_dependencies)) != len(normalized_dependencies):
        _fail("malformed", "proposal.dependencies contains duplicates")
    if operation_id in normalized_dependencies:
        _fail("malformed", "an operation cannot depend on itself")
    retry_of = None
    if "retry_of" in obj:
        retry_of = _id(obj["retry_of"], "proposal.retry_of")
        if retry_of == operation_id:
            _fail("malformed", "an operation cannot retry itself")
    observation_of = None
    observed_receipt = None
    if ("observation_of" in obj) != ("observed_receipt" in obj):
        _fail(
            "malformed",
            "observation_of and observed_receipt must be declared together",
        )
    if "observation_of" in obj:
        observation_of = _id(obj["observation_of"], "proposal.observation_of")
        observed_receipt = _opaque_receipt(
            obj["observed_receipt"], "proposal.observed_receipt"
        )
        if observation_of == operation_id:
            _fail("malformed", "an operation cannot observe itself")
        if retry_of is not None:
            _fail("malformed", "an operation cannot be both an observation and a retry")
        if (
            kind != "verify"
            or not obj["remote"]
            or obj["billable"]
            or obj["destructive"]
            or normalized_dependencies
        ):
            _fail(
                "malformed",
                "an observation must be a non-billable, non-destructive remote verify operation without dependencies",
            )
    required_grants: set[str] = set()
    if obj["billable"]:
        required_grants.add("billable")
    if obj["destructive"]:
        required_grants.add("destructive")
    if kind == "publish":
        required_grants.add("publish")
    if retry_of is not None:
        required_grants.add("retry")
    targets = _normalize_refs(obj["targets"], "proposal.targets", before=True)
    if observation_of is not None and targets:
        _fail("malformed", "an observation operation must not declare targets")
    if any(item["before_sha256"] != ABSENT for item in targets) and not obj["destructive"]:
        _fail(
            "authorization",
            "an operation that replaces an existing target must declare destructive work",
        )
    plan: dict[str, Any] = {
        "schema": PLAN_SCHEMA,
        "workflow_id": _id(obj["workflow_id"], "proposal.workflow_id"),
        "operation_id": operation_id,
        "kind": kind,
        "profile_id": _id(obj["profile_id"], "proposal.profile_id"),
        "route_id": _id(obj["route_id"], "proposal.route_id"),
        "summary": _string(obj["summary"], "proposal.summary", maximum=500),
        "inputs": _normalize_refs(obj["inputs"], "proposal.inputs"),
        "targets": targets,
        "dependencies": sorted(normalized_dependencies),
        "parameters": obj["parameters"],
        "billable": obj["billable"],
        "destructive": obj["destructive"],
        "remote": obj["remote"],
        "required_grants": sorted(required_grants),
        "context_digest": context_digest,
    }
    if retry_of is not None:
        plan["retry_of"] = retry_of
    if observation_of is not None:
        plan["observation_of"] = observation_of
        plan["observed_receipt"] = observed_receipt
    if billing is not None:
        plan["billing"] = billing
    plan["preview_digest"] = _digest_value(plan)
    return plan


def validate_plan(plan: Any) -> dict[str, Any]:
    if not isinstance(plan, dict) or plan.get("schema") != PLAN_SCHEMA:
        _fail("malformed", "plan schema is unsupported")
    supplied = plan.get("preview_digest")
    _digest(supplied, "plan.preview_digest")
    unsigned = {key: value for key, value in plan.items() if key != "preview_digest"}
    if _digest_value(unsigned) != supplied:
        _fail("integrity", "plan preview digest does not match its payload")
    # Reconstruct through the public normalizer so unknown fields and bounds stay strict.
    proposal = {
        "schema": PROPOSAL_SCHEMA,
        **{key: unsigned[key] for key in (
            "workflow_id", "operation_id", "kind", "profile_id", "route_id", "summary",
            "inputs", "targets", "dependencies", "parameters", "billable", "destructive", "remote"
        )},
    }
    proposal["targets"] = [
        {"path": item["path"], "before_sha256": item["before_sha256"]} for item in unsigned["targets"]
    ]
    if "retry_of" in unsigned:
        proposal["retry_of"] = unsigned["retry_of"]
    if "observation_of" in unsigned or "observed_receipt" in unsigned:
        proposal["observation_of"] = unsigned.get("observation_of")
        proposal["observed_receipt"] = unsigned.get("observed_receipt")
    if "billing" in unsigned:
        proposal["billing"] = unsigned["billing"]
    rebuilt = prepare_operation(proposal, unsigned["context_digest"])
    if rebuilt != plan:
        _fail("integrity", "plan is not canonical")
    return rebuilt


def validate_authorization(value: Any, plan: dict[str, Any]) -> dict[str, Any]:
    obj = _object(
        value,
        "authorization",
        {"schema", "workflow_id", "operation_id", "preview_digest", "grants", "confirmed", "authorized_at"},
        {"schema", "workflow_id", "operation_id", "preview_digest", "grants", "confirmed", "authorized_at"},
    )
    if obj["schema"] != AUTH_SCHEMA:
        _fail("malformed", "authorization schema is unsupported")
    if obj["workflow_id"] != plan["workflow_id"] or obj["operation_id"] != plan["operation_id"] or obj["preview_digest"] != plan["preview_digest"]:
        _fail("conflict", "authorization does not bind the exact plan")
    if obj["confirmed"] is not True:
        _fail("authorization", "authorization must be explicitly confirmed")
    grants = obj["grants"]
    if not isinstance(grants, list) or any(item not in GRANTS for item in grants) or len(set(grants)) != len(grants):
        _fail("malformed", "authorization grants are invalid")
    expected_grants = set(plan["required_grants"])
    actual_grants = set(grants)
    missing = sorted(expected_grants - actual_grants)
    extra = sorted(actual_grants - expected_grants)
    if missing or extra:
        _fail(
            "authorization",
            "authorization grants must exactly match the plan",
            missing=missing,
            extra=extra,
        )
    return {
        "schema": AUTH_SCHEMA,
        "workflow_id": plan["workflow_id"],
        "operation_id": plan["operation_id"],
        "preview_digest": plan["preview_digest"],
        "grants": sorted(grants),
        "confirmed": True,
        "authorized_at": _time(obj["authorized_at"], "authorization.authorized_at"),
    }


def _path_present(path: Path) -> bool:
    return os.path.lexists(os.fspath(path))


def _is_link(path: Path) -> bool:
    if not _path_present(path):
        return False
    if path.is_symlink():
        return True
    junction = getattr(path, "is_junction", None)
    if junction is not None:
        try:
            if junction():
                return True
        except OSError:
            return True
    return bool(getattr(path.lstat(), "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))


def _repo_path(repo: Path, relative: str) -> Path:
    root = Path(os.path.abspath(repo))
    if not root.is_dir() or _is_link(root):
        _fail("safety", "repository root must be a real directory")
    current = root
    parts = PurePosixPath(_safe_relative(relative, "path")).parts
    for index, part in enumerate(parts):
        current /= part
        if _path_present(current):
            if _is_link(current):
                _fail("safety", "path crosses a link or junction", path=relative)
            if index < len(parts) - 1 and not current.is_dir():
                _fail("safety", "path crosses a non-directory", path=relative)
    return current


def _managed_skill_digest(root: Path) -> str:
    """Reproduce the materializer digest for an installed Skill tree."""

    target = Path(os.path.abspath(root))
    if not _path_present(target) or _is_link(target) or not target.is_dir():
        _fail("integrity", "materialized Skill target must be a real directory")
    entries: list[tuple[str, bytes]] = []

    def walk_error(error: OSError) -> None:
        raise error

    try:
        for directory, directory_names, file_names in os.walk(
            target, topdown=True, followlinks=False, onerror=walk_error
        ):
            current = Path(directory)
            kept: list[str] = []
            for name in sorted(directory_names):
                path = current / name
                if name in MANAGED_IGNORED_DIRECTORIES:
                    continue
                if _is_link(path) or not stat.S_ISDIR(path.lstat().st_mode):
                    _fail("integrity", "materialized Skill tree contains an unsafe directory")
                kept.append(name)
            directory_names[:] = kept
            for name in sorted(file_names):
                path = current / name
                if Path(name).suffix in MANAGED_IGNORED_SUFFIXES:
                    continue
                if name == MANAGED_MARKER_FILE:
                    continue
                if _is_link(path) or not stat.S_ISREG(path.lstat().st_mode):
                    _fail("integrity", "materialized Skill tree contains an unsafe file")
                entries.append((path.relative_to(target).as_posix(), path.read_bytes()))
    except OSError as exc:
        _fail("integrity", "cannot inspect materialized Skill target", reason=str(exc))

    digest = hashlib.sha256()
    for relative, content in sorted(entries, key=lambda item: item[0]):
        relative_bytes = relative.encode("utf-8")
        digest.update(len(relative_bytes).to_bytes(8, "big"))
        digest.update(relative_bytes)
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return digest.hexdigest()


def _path_parts(path: str) -> tuple[str, ...]:
    return tuple(part.casefold() for part in PurePosixPath(path).parts)


def _is_under(path: str, root: str, *, strict: bool = False) -> bool:
    path_parts, root_parts = _path_parts(path), _path_parts(root)
    return len(path_parts) >= len(root_parts) + (1 if strict else 0) and path_parts[: len(root_parts)] == root_parts


def _paths_overlap(left: str, right: str) -> bool:
    return _is_under(left, right) or _is_under(right, left)


def validate_runtime_wrapper(value: Any) -> dict[str, Any]:
    """Validate a materializer wrapper without reading the filesystem."""

    obj = _object(
        value,
        "managed context wrapper",
        {"version", "manager", "skill", "repository_id", "sources", "context", "allowlist"},
        {"version", "manager", "skill", "repository_id", "sources", "context", "allowlist"},
    )
    if obj["version"] != 1 or obj["manager"] != "agent-skills" or obj["skill"] != "creator-workflow":
        _fail("malformed", "managed context wrapper identity is invalid")
    repository_id = _id(obj["repository_id"], "wrapper.repository_id")
    sources_obj = _object(obj["sources"], "wrapper.sources", {"repository", "skill"}, {"repository", "skill"})
    sources: dict[str, dict[str, str]] = {}
    for name in ("repository", "skill"):
        record = _object(sources_obj[name], f"wrapper.sources.{name}", {"path", "digest"}, {"path", "digest"})
        sources[name] = {
            "path": _safe_relative(record["path"], f"wrapper.sources.{name}.path"),
            "digest": _digest(record["digest"], f"wrapper.sources.{name}.digest"),
        }
    context = obj["context"]
    if not isinstance(context, dict) or context.get("schema") != "agent-skills.creator-workflow-context/v1":
        _fail("malformed", "managed creator context schema is unsupported")
    try:
        expected = _CONTEXT_MODULE.validate_materialized_context(
            context["repository"], context["configuration"]
        )
    except (KeyError, ValueError) as exc:
        _fail("integrity", "managed creator context cannot be reproduced", reason=str(exc))
    if expected["context"] != context:
        _fail("integrity", "managed creator context is not canonical")
    if context["repository"]["repository_id"] != repository_id:
        _fail("integrity", "wrapper repository identity does not match context")
    allow = _object(obj["allowlist"], "wrapper.allowlist", {"tracked_files", "tracked_collections", "write_paths"}, {"tracked_files", "tracked_collections", "write_paths"})
    normalized_allow: dict[str, list[str]] = {}
    for key in ("tracked_files", "tracked_collections", "write_paths"):
        raw = allow[key]
        if not isinstance(raw, list) or any(not isinstance(item, str) for item in raw):
            _fail("malformed", f"wrapper.allowlist.{key} must be a string array")
        normalized = sorted(_safe_relative(item, f"wrapper.allowlist.{key}") for item in raw)
        if len(set(normalized)) != len(normalized):
            _fail("malformed", f"wrapper.allowlist.{key} contains duplicates")
        normalized_allow[key] = normalized
    if normalized_allow["tracked_collections"] != expected["tracked_collections"] or normalized_allow["write_paths"] != expected["write_paths"]:
        _fail("integrity", "wrapper collection or write roots drifted from validator output")
    explicit = set(expected["tracked_files"])
    actual = set(normalized_allow["tracked_files"])
    if not explicit <= actual:
        _fail("integrity", "wrapper omits an explicit fact file")
    invalid = sorted(path for path in actual - explicit if not any(_is_under(path, root, strict=True) for root in expected["tracked_collections"]))
    if invalid:
        _fail("integrity", "wrapper includes files outside declared fact collections", paths=invalid)
    return {
        "version": 1,
        "manager": "agent-skills",
        "skill": "creator-workflow",
        "repository_id": repository_id,
        "sources": sources,
        "context": context,
        "allowlist": normalized_allow,
    }


def _validate_source_binding(repo: Path, wrapper: dict[str, Any]) -> None:
    loaded: dict[str, Any] = {}
    for name in ("repository", "skill"):
        source = wrapper["sources"][name]
        path = _repo_path(repo, source["path"])
        if not path.is_file():
            _fail("conflict", "managed config source is missing", source=name)
        data = path.read_bytes()
        if _sha(data) != source["digest"]:
            _fail("conflict", "managed config source digest changed; re-materialize", source=name)
        try:
            loaded[name] = json.loads(data.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            _fail("integrity", "managed config source is invalid UTF-8 JSON", source=name, reason=str(exc))
    try:
        expected = _CONTEXT_MODULE.validate_materialized_context(loaded["repository"], loaded["skill"])
    except ValueError as exc:
        _fail("integrity", "bound managed configuration is invalid", reason=str(exc))
    if expected["context"] != wrapper["context"]:
        _fail("integrity", "managed context does not match bound config source bytes")


def managed_context_digest(wrapper: dict[str, Any]) -> str:
    return _digest_value(
        {
            "repository_id": wrapper["repository_id"],
            "sources": wrapper["sources"],
            "context": wrapper["context"],
            "allowlist": wrapper["allowlist"],
        }
    )


def load_managed_context(repo: Path, context_path: Path) -> dict[str, Any]:
    root = Path(os.path.abspath(repo))
    if not root.is_dir() or _is_link(root):
        _fail("safety", "repository root must be a real directory")
    try:
        relative = Path(os.path.abspath(context_path)).relative_to(root).as_posix()
    except ValueError:
        _fail("safety", "managed context must be inside the repository")
    expected = {
        ".agents/skills/creator-workflow/.agent-skills-context.json": "codex",
        ".claude/skills/creator-workflow/.agent-skills-context.json": "claude",
    }
    if relative not in expected:
        _fail("safety", "managed context path is not a creator-workflow materialized target")
    resolved_context = _repo_path(root, relative)
    if not resolved_context.is_file() or _is_link(resolved_context):
        _fail("safety", "managed context must be a regular materialized file")
    raw_bytes = resolved_context.read_bytes()
    try:
        raw = json.loads(raw_bytes.decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        _fail("integrity", "cannot load managed context", reason=str(exc))
    wrapper = validate_runtime_wrapper(raw)
    target_relative = str(PurePosixPath(relative).parent)
    marker_path = _repo_path(root, f"{target_relative}/.agent-skills-managed.json")
    state_path = _repo_path(root, ".agent-skills.state.json")
    if (
        not marker_path.is_file()
        or _is_link(marker_path)
        or not state_path.is_file()
        or _is_link(state_path)
    ):
        _fail("integrity", "materializer ownership marker or state is missing")
    marker = _read_json(marker_path, "materializer ownership marker")
    state = _read_json(state_path, "materializer state")
    marker_obj = _object(
        marker,
        "materializer ownership marker",
        {
            "version", "manager", "skill", "host", "source", "digest",
            "source_digest", "context_digest",
        },
        {
            "version", "manager", "skill", "host", "source", "digest",
            "source_digest", "context_digest",
        },
    )
    if (
        marker_obj["version"] != 1
        or marker_obj["manager"] != "agent-skills"
        or marker_obj["skill"] != "creator-workflow"
        or marker_obj["host"] != expected[relative]
        or marker_obj["context_digest"] != _sha(raw_bytes)
    ):
        _fail("integrity", "materializer ownership marker does not bind this context")
    if (
        not isinstance(state, dict)
        or state.get("version") != 1
        or state.get("manager") != "agent-skills"
        or not isinstance(state.get("managed"), dict)
    ):
        _fail("integrity", "materializer state is invalid")
    expected_state_record = {
        key: marker_obj[key]
        for key in (
            "skill", "host", "source", "digest", "source_digest", "context_digest"
        )
    }
    if state["managed"].get(target_relative) != expected_state_record:
        _fail("integrity", "materializer state and ownership marker disagree")
    _digest(marker_obj["digest"], "materializer ownership marker.digest")
    if _managed_skill_digest(Path(os.path.abspath(marker_path.parent))) != marker_obj["digest"]:
        _fail("integrity", "materialized creator-workflow Skill content drifted")
    validated_configuration = _CONTEXT_MODULE.validate_materialized_context(
        wrapper["context"]["repository"], wrapper["context"]["configuration"]
    )
    host_root = ".agents/skills" if marker_obj["host"] == "codex" else ".claude/skills"
    for required_skill in validated_configuration.get("required_skills", []):
        required_target = f"{host_root}/{required_skill}"
        required_marker_path = _repo_path(
            root, f"{required_target}/.agent-skills-managed.json"
        )
        if not required_marker_path.is_file() or _is_link(required_marker_path):
            _fail(
                "integrity",
                "required materialized Skill target is missing",
                skill=required_skill,
                host=marker_obj["host"],
            )
        required_marker = _read_json(
            required_marker_path, "required Skill ownership marker"
        )
        if (
            not isinstance(required_marker, dict)
            or required_marker.get("version") != 1
            or required_marker.get("manager") != "agent-skills"
            or required_marker.get("skill") != required_skill
            or required_marker.get("host") != marker_obj["host"]
        ):
            _fail("integrity", "required Skill ownership marker is invalid")
        required_record = {
            key: required_marker.get(key)
            for key in (
                "skill",
                "host",
                "source",
                "digest",
                "source_digest",
                "context_digest",
            )
        }
        if state["managed"].get(required_target) != required_record:
            _fail(
                "integrity",
                "required Skill marker and materializer state disagree",
                skill=required_skill,
                host=marker_obj["host"],
            )
        _digest(
            required_record["digest"],
            "required Skill ownership marker.digest",
        )
        if _managed_skill_digest(required_marker_path.parent) != required_record["digest"]:
            _fail(
                "integrity",
                "required materialized Skill content drifted",
                skill=required_skill,
                host=marker_obj["host"],
            )
    _validate_source_binding(root, wrapper)
    return _new_managed_context(root, resolved_context, _sha(raw_bytes), wrapper)


def _profile_roots(wrapper: dict[str, Any], profile_id: str) -> tuple[dict[str, Any], list[str]]:
    configuration = wrapper["context"]["configuration"]
    profiles = {item["id"]: item for item in configuration["profiles"]}
    if profile_id not in profiles:
        _fail("safety", "proposal references a profile outside managed context", profile_id=profile_id)
    profile = profiles[profile_id]
    storage = configuration["storage"]
    root_maps = {
        group: {item["id"]: item["path"] for item in storage[group]}
        for group in ("project_roots", "work_roots", "output_roots", "publication_roots")
    }
    if profile["adapter"] == "generic-content-project-v1":
        roots = [
            root_maps["project_roots"][profile["project_root"]],
            root_maps["work_roots"][profile["work_root"]],
            root_maps["output_roots"][profile["output_root"]],
        ]
    else:
        roots = [root_maps["publication_roots"][profile["publication_root"]]]
    return profile, roots


def _configured_route(
    wrapper: dict[str, Any], plan: dict[str, Any]
) -> dict[str, Any]:
    routes = {
        item["id"]: item
        for item in wrapper["context"]["configuration"]["routes"]
    }
    route = routes.get(plan["route_id"])
    if route is None:
        _fail("safety", "plan route is not present in managed context")
    return route


def _validate_managed_v2_success(
    repo: Path,
    plan: dict[str, Any],
    route: dict[str, Any],
    payload: dict[str, Any],
) -> None:
    if route["adapter"] != "package-script-v2":
        return
    if "artifacts" not in payload:
        _fail(
            "integrity",
            "managed package-script-v2 success requires exact artifact evidence",
        )
    artifacts = _success_artifacts(
        payload["artifacts"], "event.payload.artifacts"
    )
    if artifacts != payload["artifacts"]:
        _fail("integrity", "success artifacts must use canonical path order")
    expected_paths = [item["path"] for item in plan["targets"]]
    actual_paths = [item["path"] for item in artifacts]
    if actual_paths != expected_paths:
        _fail(
            "integrity",
            "success artifacts must exactly cover the package plan targets",
        )
    for artifact in artifacts:
        path = _repo_path(repo, artifact["path"])
        try:
            regular = (
                path.is_file()
                and not _is_link(path)
                and stat.S_ISREG(path.lstat().st_mode)
            )
            digest = _sha(path.read_bytes()) if regular else None
        except OSError as exc:
            _fail(
                "integrity",
                "cannot inspect a succeeded package artifact",
                path=artifact["path"],
                reason=str(exc),
            )
        if not regular:
            _fail(
                "integrity",
                "succeeded package artifact must be a regular file",
                path=artifact["path"],
            )
        if digest != artifact["sha256"]:
            _fail(
                "conflict",
                "succeeded package artifact digest does not match current bytes",
                path=artifact["path"],
            )


def validate_plan_against_wrapper(plan: dict[str, Any], wrapper: dict[str, Any]) -> None:
    validate_plan(plan)
    if plan["context_digest"] != managed_context_digest(wrapper):
        _fail("conflict", "plan does not bind the current managed context")
    profile, roots = _profile_roots(wrapper, plan["profile_id"])
    if plan["route_id"] not in profile["routes"]:
        _fail("safety", "plan route is not enabled by its profile")
    route = _configured_route(wrapper, plan)
    effects = route["effects"]
    for field in ("billable", "remote", "destructive"):
        if plan[field] is not effects[field]:
            _fail(
                "safety",
                "plan effects do not match the selected route",
                route_id=route["id"],
                effect=field,
            )
    if (plan["kind"] == "publish") is not effects["publish"]:
        _fail(
            "safety",
            "plan publish kind does not match the selected route",
            route_id=route["id"],
        )
    if route["adapter"] in {"package-script-v1", "package-script-v2"}:
        manifest_fact = wrapper["context"]["repository"]["facts"].get(
            route["manifest_fact_ref"]
        )
        if not isinstance(manifest_fact, dict) or not isinstance(
            manifest_fact.get("path"), str
        ):
            _fail("integrity", "package route manifest fact is unavailable")
        if route["adapter"] == "package-script-v2":
            _validate_package_route_bindings(plan, route, manifest_fact["path"])
        else:
            parameters = _object(
                plan["parameters"],
                "plan.parameters",
                {"subcommand", "arguments"},
                {"subcommand", "arguments"},
            )
            subcommand = _id(
                parameters["subcommand"], "plan.parameters.subcommand"
            )
            if subcommand not in route["subcommands"]:
                _fail(
                    "safety",
                    "package subcommand is not enabled by the selected route",
                    route_id=route["id"],
                    subcommand=subcommand,
                )
            _package_arguments(
                parameters["arguments"],
                "plan.parameters.arguments",
                set(route["argument_keys"]),
            )
            manifest_inputs = [
                item
                for item in plan["inputs"]
                if item["path"] == manifest_fact["path"]
                and item["authority"] == "managed-fact"
            ]
            if len(manifest_inputs) != 1:
                _fail(
                    "safety",
                    "package route requires its exact manifest as a managed-fact input",
                    path=manifest_fact["path"],
                )
    protected = wrapper["context"]["configuration"]["protected_roots"]
    writes = wrapper["allowlist"]["write_paths"]
    for target in plan["targets"]:
        path = target["path"]
        if not any(_is_under(path, root, strict=True) for root in roots):
            _fail("safety", "target is outside its profile roots", path=path)
        if not any(_is_under(path, root, strict=True) for root in writes):
            _fail("safety", "target is outside managed write ceilings", path=path)
        if any(_paths_overlap(path, root) for root in protected):
            _fail("safety", "target overlaps a protected root", path=path)
    tracked = set(wrapper["allowlist"]["tracked_files"])
    for source in plan["inputs"]:
        if source["authority"] == "managed-fact" and source["path"] not in tracked:
            _fail("safety", "managed-fact input is outside tracked-file allowlist", path=source["path"])


def prepare_managed_operation(repo: Path, wrapper: dict[str, Any], proposal: Any) -> dict[str, Any]:
    wrapper = _require_managed_context(wrapper, repo)
    validate_runtime_wrapper(wrapper)
    _validate_source_binding(repo, wrapper)
    plan = prepare_operation(proposal, managed_context_digest(wrapper))
    validate_plan_against_wrapper(plan, wrapper)
    verify_dependencies(repo, plan)
    return plan


def prepare_one_off_operation(proposal: Any, context_digest: str) -> dict[str, Any]:
    """Prepare a recoverable operation that has no repository write targets."""

    plan = prepare_operation(proposal, context_digest)
    _validate_one_off_plan(plan)
    return plan


def _validate_one_off_plan(plan: dict[str, Any]) -> None:
    if plan["targets"]:
        _fail("safety", "one-off operations must not declare repository targets")
    if any(item["authority"] != "user-provided" for item in plan["inputs"]):
        _fail("safety", "one-off operations may only bind user-provided inputs")


def _verify_inputs(repo: Path, plan: dict[str, Any]) -> None:
    for item in plan["inputs"]:
        path = _repo_path(repo, item["path"])
        if not _path_present(path) or not path.is_file() or _sha(path.read_bytes()) != item["sha256"]:
            _fail("conflict", "input digest changed", path=item["path"])


def verify_dependencies(repo: Path, plan: dict[str, Any]) -> None:
    validate_plan(plan)
    _verify_inputs(repo, plan)
    for item in plan["targets"]:
        path = _repo_path(repo, item["path"])
        if _path_present(path) and not path.is_file():
            _fail(
                "conflict",
                "existing target must be a regular file",
                path=item["path"],
            )
        actual = _sha(path.read_bytes()) if path.is_file() else ABSENT
        if actual != item["before_sha256"]:
            _fail("conflict", "target digest changed", path=item["path"], expected=item["before_sha256"], actual=actual)


def _read_json(path: Path, label: str) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        _fail("integrity", f"cannot read {label}", reason=str(exc))


def _events_bytes(events: list[dict[str, Any]]) -> bytes:
    return b"".join(_canonical(event) for event in events)


def _parse_events(data: bytes) -> list[dict[str, Any]]:
    if not data:
        return []
    result = []
    try:
        for line in data.decode("ascii").splitlines():
            result.append(json.loads(line))
    except (UnicodeError, json.JSONDecodeError) as exc:
        _fail("integrity", "event ledger is not canonical ASCII JSONL", reason=str(exc))
    if _events_bytes(result) != data:
        _fail("integrity", "event ledger bytes are not canonical")
    return result


def reduce_events(events: list[dict[str, Any]]) -> dict[str, Any]:
    operations: dict[str, dict[str, Any]] = {}
    previous = "0" * 64
    event_ids: set[str] = set()
    for index, event in enumerate(events):
        obj = _object(event, f"events[{index}]", {"schema", "sequence", "event_id", "occurred_at", "operation_id", "event_type", "state", "payload", "previous_hash", "event_hash"}, {"schema", "sequence", "event_id", "occurred_at", "operation_id", "event_type", "state", "payload", "previous_hash", "event_hash"})
        if (
            obj["schema"] != EVENT_SCHEMA
            or type(obj["sequence"]) is not int
            or obj["sequence"] != index + 1
        ):
            _fail("integrity", "event sequence is invalid", index=index)
        if obj["previous_hash"] != previous:
            _fail("integrity", "event hash chain is broken", index=index)
        supplied = _digest(obj["event_hash"], "event.event_hash")
        unsigned = {key: value for key, value in obj.items() if key != "event_hash"}
        if _digest_value(unsigned) != supplied:
            _fail("integrity", "event hash is invalid", index=index)
        previous = supplied
        event_id = _id(obj["event_id"], "event.event_id")
        _time(obj["occurred_at"], "event.occurred_at")
        _id(obj["event_type"], "event.event_type")
        if event_id in event_ids:
            _fail("integrity", "event_id must be unique", event_id=event_id)
        event_ids.add(event_id)
        operation_id = _id(obj["operation_id"], "event.operation_id")
        state = _string(obj["state"], "event.state", maximum=20)
        if state not in STATES:
            _fail("integrity", "event state is invalid")
        current = operations.get(operation_id)
        prior_state = current["state"] if current else None
        if state not in TRANSITIONS[prior_state]:
            _fail("integrity", "invalid operation transition", operation_id=operation_id, before=prior_state, after=state)
        payload = obj["payload"]
        if not isinstance(payload, dict):
            _fail("integrity", "event payload must be an object")
        _reject_event_payload(payload, state)
        if state == "prepared":
            if obj["event_type"] != "operation-prepared" or not isinstance(payload, dict) or "plan" not in payload:
                _fail("integrity", "prepared event must contain a plan")
            plan = validate_plan(payload["plan"])
            if plan["operation_id"] != operation_id:
                _fail("integrity", "prepared plan operation mismatch")
            if "retry_of" in plan:
                retried = operations.get(plan["retry_of"])
                if retried is None or retried["state"] not in TERMINAL:
                    _fail("integrity", "retry_of must reference a terminal prior operation")
            if "observation_of" in plan:
                observed = operations.get(plan["observation_of"])
                if (
                    observed is None
                    or observed["state"] != "unknown"
                    or observed["remote_receipt"] is None
                    or observed["remote_receipt"] != plan["observed_receipt"]
                ):
                    _fail(
                        "integrity",
                        "observation_of must bind the immutable receipt of a prior unknown operation",
                    )
            missing_dependencies = [
                dependency
                for dependency in plan["dependencies"]
                if dependency not in operations
            ]
            if missing_dependencies:
                _fail(
                    "integrity",
                    "operation dependencies must be declared earlier in the ledger",
                    operation_id=operation_id,
                    dependencies=missing_dependencies,
                )
            current = {"state": state, "plan": plan, "authorization": None, "remote_receipt": None}
        else:
            assert current is not None
            plan = current["plan"]
            if state in {"running", "dispatching"}:
                unmet = [
                    dependency
                    for dependency in plan["dependencies"]
                    if dependency not in operations
                    or operations[dependency]["state"] != "succeeded"
                ]
                if unmet:
                    _fail(
                        "integrity",
                        "operation dependencies must succeed before execution",
                        operation_id=operation_id,
                        dependencies=unmet,
                    )
                if plan["required_grants"] and current["authorization"] is None:
                    _fail(
                        "integrity",
                        "authorized grants are required before execution",
                        operation_id=operation_id,
                    )
            if state == "dispatching" and not (plan["remote"] or plan["billable"]):
                _fail("integrity", "dispatching is only valid for remote or billable work")
            if (
                (plan["remote"] or plan["billable"])
                and prior_state == "running"
                and state in {"submitted", "succeeded", "failed", "unknown"}
            ):
                _fail(
                    "integrity",
                    "remote or billable work must persist dispatching before its outcome",
                    operation_id=operation_id,
                )
            if state == "authorized":
                authorization = validate_authorization(payload.get("authorization"), plan)
                current["authorization"] = authorization
            if "remote_receipt" in payload:
                if state not in {"submitted", "waiting", "succeeded", "failed", "unknown"}:
                    _fail(
                        "integrity",
                        "remote receipt may only be recorded after dispatch",
                        operation_id=operation_id,
                    )
                if not (plan["remote"] or plan["billable"] or plan["kind"] == "publish"):
                    _fail(
                        "integrity",
                        "local work must not record a remote receipt",
                        operation_id=operation_id,
                    )
                receipt = _opaque_receipt(
                    payload["remote_receipt"], "event.payload.remote_receipt"
                )
                if current["remote_receipt"] is not None and current["remote_receipt"] != receipt:
                    _fail(
                        "integrity",
                        "remote receipt is immutable once recorded",
                        operation_id=operation_id,
                    )
                current["remote_receipt"] = receipt
            if "artifacts" in payload:
                if state != "succeeded":
                    _fail(
                        "integrity",
                        "success artifacts may only be recorded on a succeeded event",
                        operation_id=operation_id,
                    )
                artifacts = _success_artifacts(
                    payload["artifacts"], "event.payload.artifacts"
                )
                if artifacts != payload["artifacts"]:
                    _fail(
                        "integrity",
                        "success artifacts must use canonical path order",
                        operation_id=operation_id,
                    )
                current["artifacts"] = artifacts
            if state == "submitted" and current["remote_receipt"] is None:
                _fail(
                    "integrity",
                    "submitted remote work must record an opaque receipt",
                    operation_id=operation_id,
                )
            if (
                state == "succeeded"
                and (plan["remote"] or plan["billable"] or plan["kind"] == "publish")
                and current["remote_receipt"] is None
            ):
                _fail(
                    "integrity",
                    "successful remote, billable, or publish work must retain a receipt",
                    operation_id=operation_id,
                )
            current["state"] = state
        operations[operation_id] = current
    return {
        "schema": SNAPSHOT_SCHEMA,
        "event_count": len(events),
        "head_hash": previous,
        "operations": {key: operations[key] for key in sorted(operations)},
    }


def _new_event(events: list[dict[str, Any]], operation_id: str, event_type: str, state: str, payload: dict[str, Any], event_id: str, occurred_at: str) -> dict[str, Any]:
    _reject_event_payload(payload, state)
    previous = events[-1]["event_hash"] if events else "0" * 64
    event = {
        "schema": EVENT_SCHEMA,
        "sequence": len(events) + 1,
        "event_id": _id(event_id, "event_id"),
        "occurred_at": _time(occurred_at, "occurred_at"),
        "operation_id": _id(operation_id, "operation_id"),
        "event_type": _id(event_type, "event_type"),
        "state": state,
        "payload": payload,
        "previous_hash": previous,
    }
    event["event_hash"] = _digest_value(event)
    return event


@contextlib.contextmanager
def _lock(workflow_dir: Path) -> Iterator[None]:
    root = Path(os.path.abspath(workflow_dir))
    if not root.is_dir() or _is_link(root):
        _fail("safety", "workflow root must be a real directory")
    lock = _repo_path(root, ".creator-workflow.lock")
    token_value = os.urandom(24).hex()
    token = _canonical(
        {
            "schema": LOCK_SCHEMA,
            "pid": os.getpid(),
            "token": token_value,
            "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        }
    )
    try:
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(token)
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError:
        _fail("conflict", "workflow is locked")
    try:
        yield
    finally:
        try:
            if lock.is_file() and not _is_link(lock) and lock.read_bytes() == token:
                lock.unlink()
        except OSError:
            pass


def _pid_is_alive(pid: int) -> bool:
    if type(pid) is not int or pid <= 0 or pid > 0xFFFFFFFF:
        _fail("integrity", "workflow lock pid is invalid")
    if os.name == "nt":
        process_query_limited_information = 0x1000
        still_active = 259
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
        kernel32.OpenProcess.restype = ctypes.c_void_p
        kernel32.GetExitCodeProcess.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_ulong),
        ]
        kernel32.GetExitCodeProcess.restype = ctypes.c_int
        kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
        kernel32.CloseHandle.restype = ctypes.c_int
        handle = kernel32.OpenProcess(
            process_query_limited_information, False, pid
        )
        if not handle:
            error = ctypes.get_last_error()
            if error == 5:  # Access denied still proves that the PID exists.
                return True
            if error in {87, 1168}:
                return False
            return True
        try:
            exit_code = ctypes.c_ulong()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                return True
            return exit_code.value == still_active
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError as exc:
        if exc.errno == errno.ESRCH or getattr(exc, "winerror", None) in {87, 1168}:
            return False
        return True
    return True


def _break_stale_lock(
    workflow_dir: Path, expected_sha256: str, confirmed: bool
) -> str:
    root = Path(os.path.abspath(workflow_dir))
    _workflow_identity(root)
    lock = _repo_path(root, ".creator-workflow.lock")
    if not lock.is_file() or _is_link(lock):
        _fail("conflict", "workflow lock is absent or unsafe")
    raw = lock.read_bytes()
    expected = _digest(expected_sha256, "expected lock sha256")
    if _sha(raw) != expected:
        _fail("conflict", "workflow lock digest changed")
    record = _read_json(lock, "workflow lock")
    if _canonical(record) != raw:
        _fail("integrity", "workflow lock bytes are not canonical")
    lock_record = _object(
        record,
        "workflow lock",
        {"schema", "pid", "token", "created_at"},
        {"schema", "pid", "token", "created_at"},
    )
    if lock_record["schema"] != LOCK_SCHEMA:
        _fail("integrity", "workflow lock schema is invalid")
    token = _string(lock_record["token"], "workflow lock token", maximum=48)
    if re.fullmatch(r"[0-9a-f]{48}", token) is None:
        _fail("integrity", "workflow lock token is invalid")
    created_at = _time(lock_record["created_at"], "workflow lock created_at")
    created = dt.datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    if created > dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=5):
        _fail("integrity", "workflow lock creation time is in the future")
    if _pid_is_alive(lock_record["pid"]):
        _fail("conflict", "workflow lock owner is still active")
    if confirmed is not True:
        _fail("authorization", "breaking a stale workflow lock requires confirmation")
    if not lock.is_file() or _is_link(lock) or lock.read_bytes() != raw:
        _fail("conflict", "workflow lock changed before removal")
    lock.unlink()
    return expected


def break_managed_lock(
    repo: Path,
    wrapper: dict[str, Any],
    workflow_dir: Path,
    expected_sha256: str,
    confirmed: bool,
) -> str:
    _validate_managed_workflow_location(repo, wrapper, workflow_dir)
    return _break_stale_lock(workflow_dir, expected_sha256, confirmed)


def break_one_off_lock(
    repo: Path,
    state_root: Path,
    workflow_dir: Path,
    expected_sha256: str,
    confirmed: bool,
) -> str:
    _validate_one_off_workflow_location(repo, state_root, workflow_dir)
    return _break_stale_lock(workflow_dir, expected_sha256, confirmed)


def _replace(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        with contextlib.suppress(OSError):
            os.unlink(temporary)


def _create_exclusive(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        _fail("conflict", "workflow transaction journal already exists")
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        with contextlib.suppress(OSError):
            path.unlink()
        raise


def _encode(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _decode(value: str) -> bytes:
    try:
        return base64.b64decode(value.encode("ascii"), validate=True)
    except (UnicodeError, ValueError) as exc:
        _fail("integrity", "journal contains invalid bytes", reason=str(exc))


def _commit(workflow_dir: Path, events: list[dict[str, Any]]) -> None:
    events_path = _repo_path(workflow_dir, "events.jsonl")
    snapshot_path = _repo_path(workflow_dir, "snapshot.json")
    for path, label in ((events_path, "events"), (snapshot_path, "snapshot")):
        if not path.is_file() or _is_link(path):
            _fail("integrity", f"workflow {label} target must be a regular file")
    before_events = events_path.read_bytes() if events_path.exists() else b""
    before_snapshot = snapshot_path.read_bytes() if snapshot_path.exists() else b""
    after_events = _events_bytes(events)
    after_snapshot = _canonical(reduce_events(events))
    journal_path = _repo_path(workflow_dir, "transaction/journal.json")
    journal = {
        "schema": JOURNAL_SCHEMA,
        "targets": [
            {"path": "events.jsonl", "before": _encode(before_events), "after": _encode(after_events), "before_sha256": _sha(before_events), "after_sha256": _sha(after_events)},
            {"path": "snapshot.json", "before": _encode(before_snapshot), "after": _encode(after_snapshot), "before_sha256": _sha(before_snapshot), "after_sha256": _sha(after_snapshot)},
        ],
    }
    if events_path.read_bytes() != before_events or snapshot_path.read_bytes() != before_snapshot:
        _fail("conflict", "workflow changed before transaction journal creation")
    _create_exclusive(journal_path, _canonical(journal))
    if events_path.read_bytes() != before_events:
        _fail("conflict", "workflow events changed before replacement")
    _replace(events_path, after_events)
    if snapshot_path.read_bytes() != before_snapshot:
        _fail("conflict", "workflow snapshot changed before replacement")
    _replace(snapshot_path, after_snapshot)
    if events_path.read_bytes() != after_events or snapshot_path.read_bytes() != after_snapshot:
        _fail("integrity", "workflow transaction postcondition failed")
    journal_path.unlink()


def _validate_ledger_pair(events_data: bytes, snapshot_data: bytes) -> None:
    events = _parse_events(events_data)
    expected = _canonical(reduce_events(events))
    if snapshot_data != expected:
        _fail("integrity", "journal ledger pair has an invalid snapshot projection")


def _recover_locked(workflow_dir: Path) -> str:
    journal_path = _repo_path(workflow_dir, "transaction/journal.json")
    if not journal_path.exists():
        verify_workflow(workflow_dir)
        return "clean"
    if not journal_path.is_file() or _is_link(journal_path):
        _fail("safety", "workflow journal must be a regular file")
    journal_bytes = journal_path.read_bytes()
    journal = _read_json(journal_path, "journal")
    if _canonical(journal) != journal_bytes:
        _fail("integrity", "workflow journal is not canonical")
    _object(journal, "journal", {"schema", "targets"}, {"schema", "targets"})
    if journal["schema"] != JOURNAL_SCHEMA or not isinstance(journal["targets"], list):
        _fail("integrity", "journal schema is invalid")
    expected_paths = ["events.jsonl", "snapshot.json"]
    actual_paths = [item.get("path") if isinstance(item, dict) else None for item in journal["targets"]]
    if actual_paths != expected_paths:
        _fail("integrity", "journal targets must be the exact ordered ledger pair")
    observations: list[str] = []
    records: list[tuple[Path, bytes, bytes]] = []
    for raw in journal["targets"]:
        item = _object(raw, "journal target", {"path", "before", "after", "before_sha256", "after_sha256"}, {"path", "before", "after", "before_sha256", "after_sha256"})
        path = _repo_path(workflow_dir, _safe_relative(item["path"], "journal target path"))
        if not path.is_file() or _is_link(path):
            _fail("safety", "journal target must be a regular file", path=item["path"])
        before, after = _decode(item["before"]), _decode(item["after"])
        if _sha(before) != item["before_sha256"] or _sha(after) != item["after_sha256"]:
            _fail("integrity", "journal byte digest is invalid")
        current = path.read_bytes() if path.exists() else b""
        observations.append("before" if current == before else "after" if current == after else "third")
        records.append((path, before, after))
    _validate_ledger_pair(records[0][1], records[1][1])
    _validate_ledger_pair(records[0][2], records[1][2])
    if "third" in observations:
        _fail("conflict", "workflow target has a third state; manual resolution required")
    if all(item == "after" for item in observations):
        _validate_ledger_pair(records[0][0].read_bytes(), records[1][0].read_bytes())
        journal_path.unlink()
        verify_workflow(workflow_dir)
        return "completed"
    for path, before, _after in reversed(records):
        current = path.read_bytes()
        if current not in {before, _after}:
            _fail("conflict", "workflow target changed during recovery")
        _replace(path, before)
    _validate_ledger_pair(records[0][0].read_bytes(), records[1][0].read_bytes())
    journal_path.unlink()
    verify_workflow(workflow_dir)
    return "rolled-back"


def recover(workflow_dir: Path) -> str:
    """Recover one workflow while honoring the same exclusive lock as append."""

    root = Path(os.path.abspath(workflow_dir))
    if not root.is_dir() or _is_link(root):
        _fail("safety", "workflow root must be a real directory")
    with _lock(root):
        return _recover_locked(root)


def _same_path(left: Path, right: Path) -> bool:
    try:
        return os.path.samefile(left, right)
    except OSError:
        return os.path.normcase(os.path.abspath(left)) == os.path.normcase(
            os.path.abspath(right)
        )


def _workflow_identity(workflow_dir: Path) -> dict[str, Any]:
    root = Path(os.path.abspath(workflow_dir))
    if not root.is_dir() or _is_link(root):
        _fail("safety", "workflow root must be a real directory")
    path = _repo_path(root, "workflow.json")
    if not path.is_file() or _is_link(path):
        _fail("integrity", "workflow identity must be a regular file")
    identity = _read_json(path, "workflow identity")
    _object(
        identity,
        "workflow identity",
        {"schema", "workflow_id", "profile_id", "context_digest"},
        {"schema", "workflow_id", "profile_id", "context_digest"},
    )
    if identity["schema"] != WORKFLOW_SCHEMA:
        _fail("integrity", "workflow identity schema is invalid")
    _id(identity["workflow_id"], "workflow_id")
    _id(identity["profile_id"], "profile_id")
    _digest(identity["context_digest"], "context_digest")
    return identity


def _validate_managed_workflow_location(
    repo: Path,
    wrapper: dict[str, Any],
    workflow_dir: Path,
    identity: dict[str, Any] | None = None,
) -> dict[str, Any]:
    managed = _require_managed_context(wrapper, repo)
    validate_runtime_wrapper(managed)
    _validate_source_binding(repo, managed)
    identity = identity or _workflow_identity(workflow_dir)
    configuration = managed["context"]["configuration"]
    state_relative = configuration["storage"]["state_root"]
    expected = _repo_path(repo, f"{state_relative}/{identity['workflow_id']}")
    actual = Path(os.path.abspath(workflow_dir))
    if not _same_path(actual, expected):
        _fail(
            "safety",
            "managed workflow must live at the configured state root",
            expected=f"{state_relative}/{identity['workflow_id']}",
        )
    workflow_relative = f"{state_relative}/{identity['workflow_id']}"
    if any(
        _paths_overlap(workflow_relative, protected)
        for protected in configuration["protected_roots"]
    ):
        _fail("safety", "workflow state path overlaps a protected root")
    if identity["context_digest"] != managed_context_digest(managed):
        _fail("conflict", "workflow identity does not bind the current managed context")
    _profile_roots(managed, identity["profile_id"])
    return identity


def _external_state_root(repo: Path, state_root: Path) -> Path:
    repository = Path(os.path.abspath(repo))
    root = Path(os.path.abspath(state_root))
    if not state_root.is_absolute():
        _fail("safety", "one-off state root must be an absolute path")
    if not repository.is_dir() or _is_link(repository):
        _fail("safety", "repository root must be a real directory")
    if not root.is_dir() or _is_link(root):
        _fail("safety", "one-off state root must be a pre-created real directory")
    try:
        common = Path(os.path.commonpath((repository, root)))
    except ValueError:
        common = None
    if common is not None and (
        _same_path(common, repository) or _same_path(common, root)
    ):
        _fail("safety", "one-off state root must be outside the repository")
    current = root
    while True:
        if _path_present(current) and _is_link(current):
            _fail("safety", "one-off state root crosses a link or junction")
        if current.parent == current:
            break
        current = current.parent
    return root


def _validate_one_off_workflow_location(
    repo: Path, state_root: Path, workflow_dir: Path
) -> dict[str, Any]:
    root = _external_state_root(repo, state_root)
    identity = _workflow_identity(workflow_dir)
    expected = root / identity["workflow_id"]
    if not _same_path(Path(os.path.abspath(workflow_dir)), expected):
        _fail("safety", "one-off workflow must be a direct child of its declared state root")
    return identity


def recover_managed(
    repo: Path, wrapper: dict[str, Any], workflow_dir: Path
) -> str:
    root = Path(os.path.abspath(workflow_dir))
    _validate_managed_workflow_location(repo, wrapper, root)
    with _lock(root):
        _validate_managed_workflow_location(repo, wrapper, root)
        return _recover_locked(root)


def recover_one_off(repo: Path, state_root: Path, workflow_dir: Path) -> str:
    root = Path(os.path.abspath(workflow_dir))
    _validate_one_off_workflow_location(repo, state_root, root)
    with _lock(root):
        _validate_one_off_workflow_location(repo, state_root, root)
        return _recover_locked(root)


def record_prepared_one_off(
    repo: Path,
    state_root: Path,
    workflow_dir: Path,
    plan: dict[str, Any],
    event_id: str,
    occurred_at: str,
) -> dict[str, Any]:
    plan = validate_plan(plan)
    _validate_one_off_plan(plan)
    _validate_one_off_workflow_location(repo, state_root, workflow_dir)
    with _lock(workflow_dir):
        identity = _validate_one_off_workflow_location(
            repo, state_root, workflow_dir
        )
        if (
            plan["workflow_id"] != identity["workflow_id"]
            or plan["profile_id"] != identity["profile_id"]
            or plan["context_digest"] != identity["context_digest"]
        ):
            _fail("conflict", "one-off plan does not bind this workflow identity")
        verify_dependencies(repo, plan)
        return _append_state_locked(
            workflow_dir,
            operation_id=plan["operation_id"],
            state="prepared",
            event_type="operation-prepared",
            payload={"plan": plan},
            event_id=event_id,
            occurred_at=occurred_at,
        )


def append_one_off_state(
    repo: Path,
    state_root: Path,
    workflow_dir: Path,
    *,
    operation_id: str,
    state: str,
    event_type: str,
    payload: dict[str, Any],
    event_id: str,
    occurred_at: str,
) -> dict[str, Any]:
    _validate_one_off_workflow_location(repo, state_root, workflow_dir)
    if state == "prepared" or event_type == "operation-prepared":
        _fail("safety", "one-off prepared plans require record_prepared_one_off")
    with _lock(workflow_dir):
        _validate_one_off_workflow_location(repo, state_root, workflow_dir)
        existing = verify_workflow(workflow_dir)["snapshot"]
        for operation in existing["operations"].values():
            _validate_one_off_plan(operation["plan"])
        return _append_state_locked(
            workflow_dir,
            operation_id=operation_id,
            state=state,
            event_type=event_type,
            payload=payload,
            event_id=event_id,
            occurred_at=occurred_at,
            repo=repo,
        )


def initialize_workflow(state_root: Path, workflow_id: str, profile_id: str, context_digest: str) -> Path:
    workflow_id, profile_id = _id(workflow_id, "workflow_id"), _id(profile_id, "profile_id")
    _digest(context_digest, "context_digest")
    root = Path(os.path.abspath(state_root))
    root.mkdir(parents=True, exist_ok=True)
    if _is_link(root):
        _fail("safety", "state root must be a real directory")
    workflow_dir = root / workflow_id
    if _path_present(workflow_dir):
        _fail("conflict", "workflow already exists")
    workflow_dir.mkdir()
    identity = {"schema": WORKFLOW_SCHEMA, "workflow_id": workflow_id, "profile_id": profile_id, "context_digest": context_digest}
    _replace(workflow_dir / "workflow.json", _canonical(identity))
    _replace(workflow_dir / "events.jsonl", b"")
    _replace(workflow_dir / "snapshot.json", _canonical(reduce_events([])))
    return workflow_dir


def initialize_managed_workflow(
    repo: Path,
    wrapper: dict[str, Any],
    workflow_id: str,
    profile_id: str,
) -> Path:
    wrapper = _require_managed_context(wrapper, repo)
    validate_runtime_wrapper(wrapper)
    _validate_source_binding(repo, wrapper)
    _profile_roots(wrapper, _id(profile_id, "profile_id"))
    configuration = wrapper["context"]["configuration"]
    state_relative = configuration["storage"]["state_root"]
    if state_relative not in wrapper["allowlist"]["write_paths"]:
        _fail("integrity", "managed state root is outside write ceilings")
    normalized_workflow_id = _id(workflow_id, "workflow_id")
    workflow_relative = f"{state_relative}/{normalized_workflow_id}"
    if any(
        _paths_overlap(workflow_relative, protected)
        for protected in configuration["protected_roots"]
    ):
        _fail("safety", "workflow state path overlaps a protected root")
    return initialize_workflow(
        _repo_path(repo, state_relative),
        normalized_workflow_id,
        profile_id,
        managed_context_digest(wrapper),
    )


def verify_workflow(workflow_dir: Path) -> dict[str, Any]:
    root = Path(os.path.abspath(workflow_dir))
    if not root.is_dir() or _is_link(root):
        _fail("safety", "workflow root must be a real directory")
    identity_path = _repo_path(root, "workflow.json")
    events_path = _repo_path(root, "events.jsonl")
    snapshot_path = _repo_path(root, "snapshot.json")
    for path, label in (
        (identity_path, "identity"),
        (events_path, "events"),
        (snapshot_path, "snapshot"),
    ):
        if not path.is_file() or _is_link(path):
            _fail("integrity", f"workflow {label} must be a regular file")
    identity = _read_json(identity_path, "workflow identity")
    _object(identity, "workflow identity", {"schema", "workflow_id", "profile_id", "context_digest"}, {"schema", "workflow_id", "profile_id", "context_digest"})
    if identity["schema"] != WORKFLOW_SCHEMA:
        _fail("integrity", "workflow identity schema is invalid")
    _id(identity["workflow_id"], "workflow_id")
    _id(identity["profile_id"], "profile_id")
    _digest(identity["context_digest"], "context_digest")
    events = _parse_events(events_path.read_bytes())
    snapshot = reduce_events(events)
    for operation_id, operation in snapshot["operations"].items():
        plan = operation["plan"]
        if (
            plan["workflow_id"] != identity["workflow_id"]
            or plan["profile_id"] != identity["profile_id"]
            or plan["context_digest"] != identity["context_digest"]
        ):
            _fail(
                "integrity",
                "operation plan does not bind the workflow identity",
                operation_id=operation_id,
            )
    stored = _read_json(snapshot_path, "snapshot")
    if stored != snapshot or _canonical(stored) != snapshot_path.read_bytes():
        _fail("integrity", "snapshot is not the canonical event projection")
    if _repo_path(root, "transaction/journal.json").exists():
        _fail("conflict", "workflow has an unfinished transaction; recover first")
    return {"identity": identity, "snapshot": snapshot, "events": events}


def _append_state_locked(
    workflow_dir: Path,
    *,
    operation_id: str,
    state: str,
    event_type: str,
    payload: dict[str, Any],
    event_id: str,
    occurred_at: str,
    repo: Path | None = None,
    wrapper: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if state not in STATES:
        _fail("malformed", "state is unsupported")
    if wrapper is not None and repo is None:
        _fail("malformed", "managed append requires repo with wrapper")
    if wrapper is not None:
        assert repo is not None
        _validate_managed_workflow_location(repo, wrapper, workflow_dir)
    recovered = verify_workflow(workflow_dir)
    events = recovered["events"]
    existing = recovered["snapshot"]["operations"].get(operation_id)
    if state in {"running", "dispatching"} and existing is not None:
        if existing["plan"]["required_grants"] and existing["authorization"] is None:
            _fail("authorization", "operation requires authorization before execution")
    event = _new_event(events, operation_id, event_type, state, payload, event_id, occurred_at)
    candidate = [*events, event]
    snapshot = reduce_events(candidate)
    operation = snapshot["operations"][operation_id]
    managed_route: dict[str, Any] | None = None
    if wrapper is not None:
        assert repo is not None
        wrapper = _require_managed_context(wrapper, repo)
        validate_plan_against_wrapper(operation["plan"], wrapper)
        managed_route = _configured_route(wrapper, operation["plan"])
        if state == "succeeded" and managed_route["adapter"] == "package-script-v2":
            _verify_inputs(repo, operation["plan"])
            _validate_managed_v2_success(
                repo, operation["plan"], managed_route, payload
            )
    if state in {"prepared", "running", "dispatching"} and repo is not None:
        verify_dependencies(repo, operation["plan"])
    if state in {"running", "dispatching"}:
        if operation["plan"]["required_grants"] and operation["authorization"] is None:
            _fail("authorization", "operation requires authorization before execution")
    if state == "dispatching" and not (operation["plan"]["remote"] or operation["plan"]["billable"]):
        _fail("malformed", "dispatching is only valid for remote or billable work")
    _commit(workflow_dir, candidate)
    return event


def append_state(
    workflow_dir: Path,
    *,
    operation_id: str,
    state: str,
    event_type: str,
    payload: dict[str, Any],
    event_id: str,
    occurred_at: str,
    repo: Path | None = None,
    wrapper: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if wrapper is not None:
        if repo is None:
            _fail("malformed", "managed append requires repo with wrapper")
        _validate_managed_workflow_location(repo, wrapper, workflow_dir)
    with _lock(workflow_dir):
        return _append_state_locked(
            workflow_dir,
            operation_id=operation_id,
            state=state,
            event_type=event_type,
            payload=payload,
            event_id=event_id,
            occurred_at=occurred_at,
            repo=repo,
            wrapper=wrapper,
        )


def record_prepared(
    workflow_dir: Path,
    plan: dict[str, Any],
    event_id: str,
    occurred_at: str,
    *,
    repo: Path | None = None,
    wrapper: dict[str, Any] | None = None,
) -> dict[str, Any]:
    plan = validate_plan(plan)
    if wrapper is not None and repo is None:
        _fail("malformed", "managed prepare recording requires repo with wrapper")
    if wrapper is not None:
        assert repo is not None
        _validate_managed_workflow_location(repo, wrapper, workflow_dir)
        validate_plan_against_wrapper(plan, wrapper)
    with _lock(workflow_dir):
        identity = verify_workflow(workflow_dir)["identity"]
        if plan["workflow_id"] != identity["workflow_id"] or plan["profile_id"] != identity["profile_id"] or plan["context_digest"] != identity["context_digest"]:
            _fail("conflict", "plan does not bind this workflow identity")
        return _append_state_locked(
            workflow_dir,
            operation_id=plan["operation_id"],
            state="prepared",
            event_type="operation-prepared",
            payload={"plan": plan},
            event_id=event_id,
            occurred_at=occurred_at,
            repo=repo,
            wrapper=wrapper,
        )


def _load(path: Path) -> Any:
    return _read_json(path, os.fspath(path))


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prepare and maintain a creator-workflow ledger without executing tools.")
    sub = parser.add_subparsers(dest="command", required=True)
    prepare = sub.add_parser("prepare")
    prepare.add_argument("--proposal", required=True, type=Path)
    prepare.add_argument("--repo", required=True, type=Path)
    prepare.add_argument("--context", required=True, type=Path)
    prepare_one_off = sub.add_parser("prepare-one-off")
    prepare_one_off.add_argument("--proposal", required=True, type=Path)
    prepare_one_off.add_argument("--context-digest", required=True)
    verify = sub.add_parser("verify")
    verify.add_argument("--workflow-dir", required=True, type=Path)
    recover_parser = sub.add_parser("recover")
    recover_parser.add_argument("--workflow-dir", required=True, type=Path)
    recover_parser.add_argument("--repo", required=True, type=Path)
    recover_parser.add_argument("--context", required=True, type=Path)
    recover_one_off = sub.add_parser("recover-one-off")
    recover_one_off.add_argument("--repo", required=True, type=Path)
    recover_one_off.add_argument("--state-root", required=True, type=Path)
    recover_one_off.add_argument("--workflow-dir", required=True, type=Path)
    break_lock = sub.add_parser("break-stale-lock")
    break_lock.add_argument("--repo", required=True, type=Path)
    break_lock.add_argument("--context", required=True, type=Path)
    break_lock.add_argument("--workflow-dir", required=True, type=Path)
    break_lock.add_argument("--expected-sha256", required=True)
    break_lock.add_argument("--confirmed", action="store_true")
    break_one_off = sub.add_parser("break-stale-lock-one-off")
    break_one_off.add_argument("--repo", required=True, type=Path)
    break_one_off.add_argument("--state-root", required=True, type=Path)
    break_one_off.add_argument("--workflow-dir", required=True, type=Path)
    break_one_off.add_argument("--expected-sha256", required=True)
    break_one_off.add_argument("--confirmed", action="store_true")
    init = sub.add_parser("init")
    init.add_argument("--repo", required=True, type=Path)
    init.add_argument("--context", required=True, type=Path)
    init.add_argument("--workflow-id", required=True)
    init.add_argument("--profile-id", required=True)
    init_one_off = sub.add_parser("init-one-off")
    init_one_off.add_argument("--repo", required=True, type=Path)
    init_one_off.add_argument("--state-root", required=True, type=Path)
    init_one_off.add_argument("--workflow-id", required=True)
    init_one_off.add_argument("--profile-id", required=True)
    init_one_off.add_argument("--context-digest", required=True)
    record = sub.add_parser("record")
    record.add_argument("--workflow-dir", required=True, type=Path)
    record.add_argument("--operation-id", required=True)
    record.add_argument("--state", required=True)
    record.add_argument("--event-type", required=True)
    record.add_argument("--payload", required=True, type=Path)
    record.add_argument("--event-id", required=True)
    record.add_argument("--occurred-at", required=True)
    record.add_argument("--repo", required=True, type=Path)
    record.add_argument("--context", required=True, type=Path)
    prepared = sub.add_parser("record-prepared")
    prepared.add_argument("--workflow-dir", required=True, type=Path)
    prepared.add_argument("--plan", required=True, type=Path)
    prepared.add_argument("--event-id", required=True)
    prepared.add_argument("--occurred-at", required=True)
    prepared.add_argument("--repo", required=True, type=Path)
    prepared.add_argument("--context", required=True, type=Path)
    prepared_one_off = sub.add_parser("record-prepared-one-off")
    prepared_one_off.add_argument("--repo", required=True, type=Path)
    prepared_one_off.add_argument("--state-root", required=True, type=Path)
    prepared_one_off.add_argument("--workflow-dir", required=True, type=Path)
    prepared_one_off.add_argument("--plan", required=True, type=Path)
    prepared_one_off.add_argument("--event-id", required=True)
    prepared_one_off.add_argument("--occurred-at", required=True)
    record_one_off = sub.add_parser("record-one-off")
    record_one_off.add_argument("--repo", required=True, type=Path)
    record_one_off.add_argument("--state-root", required=True, type=Path)
    record_one_off.add_argument("--workflow-dir", required=True, type=Path)
    record_one_off.add_argument("--operation-id", required=True)
    record_one_off.add_argument("--state", required=True)
    record_one_off.add_argument("--event-type", required=True)
    record_one_off.add_argument("--payload", required=True, type=Path)
    record_one_off.add_argument("--event-id", required=True)
    record_one_off.add_argument("--occurred-at", required=True)
    return parser.parse_args()


def main() -> int:
    args = _arguments()
    try:
        if args.command == "prepare":
            wrapper = load_managed_context(args.repo, args.context)
            result = prepare_managed_operation(args.repo, wrapper, _load(args.proposal))
        elif args.command == "prepare-one-off":
            result = prepare_one_off_operation(
                _load(args.proposal), args.context_digest
            )
        elif args.command == "verify":
            result = verify_workflow(args.workflow_dir)
        elif args.command == "recover":
            wrapper = load_managed_context(args.repo, args.context)
            result = {
                "recovery": recover_managed(
                    args.repo, wrapper, args.workflow_dir
                )
            }
        elif args.command == "recover-one-off":
            result = {
                "recovery": recover_one_off(
                    args.repo, args.state_root, args.workflow_dir
                )
            }
        elif args.command == "break-stale-lock":
            wrapper = load_managed_context(args.repo, args.context)
            result = {
                "removed_lock_sha256": break_managed_lock(
                    args.repo,
                    wrapper,
                    args.workflow_dir,
                    args.expected_sha256,
                    args.confirmed,
                )
            }
        elif args.command == "break-stale-lock-one-off":
            result = {
                "removed_lock_sha256": break_one_off_lock(
                    args.repo,
                    args.state_root,
                    args.workflow_dir,
                    args.expected_sha256,
                    args.confirmed,
                )
            }
        elif args.command == "init":
            wrapper = load_managed_context(args.repo, args.context)
            result = {"workflow_dir": os.fspath(initialize_managed_workflow(args.repo, wrapper, args.workflow_id, args.profile_id))}
        elif args.command == "init-one-off":
            root = _external_state_root(args.repo, args.state_root)
            result = {
                "workflow_dir": os.fspath(
                    initialize_workflow(
                        root,
                        args.workflow_id,
                        args.profile_id,
                        args.context_digest,
                    )
                )
            }
        elif args.command == "record-prepared":
            wrapper = load_managed_context(args.repo, args.context)
            plan = _load(args.plan)
            validate_plan_against_wrapper(plan, wrapper)
            result = record_prepared(
                args.workflow_dir,
                plan,
                args.event_id,
                args.occurred_at,
                repo=args.repo,
                wrapper=wrapper,
            )
        elif args.command == "record-prepared-one-off":
            result = record_prepared_one_off(
                args.repo,
                args.state_root,
                args.workflow_dir,
                _load(args.plan),
                args.event_id,
                args.occurred_at,
            )
        elif args.command == "record-one-off":
            payload = _load(args.payload)
            if not isinstance(payload, dict):
                _fail("malformed", "event payload must be an object")
            result = append_one_off_state(
                args.repo,
                args.state_root,
                args.workflow_dir,
                operation_id=args.operation_id,
                state=args.state,
                event_type=args.event_type,
                payload=payload,
                event_id=args.event_id,
                occurred_at=args.occurred_at,
            )
        else:
            wrapper = load_managed_context(args.repo, args.context)
            payload = _load(args.payload)
            if not isinstance(payload, dict):
                _fail("malformed", "event payload must be an object")
            result = append_state(args.workflow_dir, operation_id=args.operation_id, state=args.state, event_type=args.event_type, payload=payload, event_id=args.event_id, occurred_at=args.occurred_at, repo=args.repo, wrapper=wrapper)
        sys.stdout.write(json.dumps({"ok": True, "result": result}, ensure_ascii=True, sort_keys=True) + "\n")
        return 0
    except WorkflowError as exc:
        sys.stdout.write(json.dumps({"ok": False, "error": {"code": exc.code, "message": exc.message, "details": exc.details}}, ensure_ascii=True, sort_keys=True) + "\n")
        return {"malformed": 3, "safety": 4, "conflict": 5, "integrity": 6, "authorization": 7}.get(exc.code, 2)


if __name__ == "__main__":
    raise SystemExit(main())
