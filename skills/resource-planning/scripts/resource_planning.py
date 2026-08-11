#!/usr/bin/env python3
"""Deterministic validation and publishing for the resource-planning Skill.

This module deliberately uses only the Python standard library.  It performs no
network access and never invokes Git, a shell, or a subprocess.  Semantic
research and ranking remain the calling agent's responsibility.
"""

from __future__ import annotations

import argparse
import base64
import copy
import datetime as dt
import difflib
import hashlib
import json
import os
import re
import stat
import sys
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping, NoReturn, Sequence
from urllib.parse import urlsplit, urlunsplit


CONFIG_SCHEMA = "agent-skills.resource-planning/v1"
REPOSITORY_SCHEMA = "agent-skills.repository/v1"
CONTEXT_SCHEMA = "agent-skills.resource-planning-context/v1"
REGISTRY_SCHEMA = "agent-skills.resource-registry/v1"
PROPOSAL_SCHEMA = "agent-skills.resource-proposal/v1"
PLAN_SCHEMA = "agent-skills.resource-plan/v1"
ENVELOPE_SCHEMA = "agent-skills.resource-execution/v1"
JOURNAL_SCHEMA = "agent-skills.resource-journal/v1"
WRAPPER_VERSION = 1
PREVIEW_SENTINEL = "__RESOURCE_PLANNING_PREVIEW_DIGEST__"
ABSENT = "absent"

EXIT_USAGE = 2
EXIT_MALFORMED = 3
EXIT_SAFETY = 4
EXIT_CONFLICT = 5
EXIT_INTEGRITY = 6

ID_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
HEX64_RE = re.compile(r"^[0-9a-f]{64}$")
REVISION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:+/@-]{0,255}$")
DOI_RE = re.compile(r"^10\.\d{4,9}/\S+$", re.IGNORECASE)
ARXIV_RE = re.compile(r"^(?:[a-z-]+(?:\.[A-Z]{2})?/\d{7}|\d{4}\.\d{4,5})(?:v\d+)?$", re.IGNORECASE)
SLOT_MARKER_RE = re.compile(
    r"^<!-- resource-slot:([a-z0-9]+(?:-[a-z0-9]+)*):(start|end) -->$"
)
STATE_MARKER_RE = re.compile(r"^<!-- resource-state:(\{.*\}) -->$")

SOURCE_KINDS = {"web", "feed", "repository", "paper-index", "manual", "private"}
SOURCE_ROLES = {
    "discovery-index",
    "normative-primary",
    "first-party-engineering",
    "independent-validation",
    "teaching-review",
}
RESOURCE_TYPES = {"paper", "code", "documentation", "course", "book", "article", "video", "dataset", "other"}
RELATIONS = {
    "version_of",
    "updates",
    "successor_to",
    "complements",
    "conflicts_with",
    "possible_duplicate",
}
CLAIM_STATES = {"verified", "qualified", "unverified", "conflict"}
COVERAGE_STATES = {"covered", "no-hit", "blocked", "skipped"}
ACTIONS = {"add", "annotate", "replace", "retire"}
PERSISTENT_STATES = {
    "draft",
    "blocked",
    "qualified",
    "approved",
    "deferred",
    "rejected",
    "superseded",
    "applied",
    "stale",
}
TRANSITIONS: dict[str | None, set[str]] = {
    None: {"draft"},
    "draft": {"blocked", "qualified"},
    "qualified": {"approved", "blocked", "deferred", "rejected", "superseded"},
    "blocked": {"draft", "qualified", "rejected", "superseded"},
    "deferred": {"qualified", "blocked", "rejected", "superseded"},
    "approved": {"applied"},
    "applied": {"stale", "superseded"},
    "rejected": set(),
    "superseded": set(),
    "stale": set(),
}

# This is the sole adapter allowlist.  Consumer configuration may narrow actions
# and vocabularies, but cannot add executable behavior.
ADAPTER_CATALOG: dict[str, dict[str, Any]] = {
    "markdown-curriculum": {
        "versions": [1],
        "actions": sorted(ACTIONS),
        "supports_progress_projection": True,
    },
    "problem-curriculum": {
        "versions": [1],
        "actions": sorted(ACTIONS),
        "supports_progress_projection": False,
    },
}


class ResourcePlanningError(RuntimeError):
    """Stable, classified failure raised by the deterministic core."""

    def __init__(self, code: str, message: str, **details: Any) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details


def _fail(code: str, message: str, **details: Any) -> NoReturn:
    raise ResourcePlanningError(code, message, **details)


def _strict_object(value: Any, label: str, allowed: set[str], required: set[str] = frozenset()) -> dict[str, Any]:
    if not isinstance(value, dict):
        _fail("malformed", f"{label} must be an object")
    unknown = sorted(set(value) - allowed)
    missing = sorted(required - set(value))
    if unknown:
        _fail("malformed", f"{label} has unknown fields", fields=unknown)
    if missing:
        _fail("malformed", f"{label} is missing required fields", fields=missing)
    return value


def _string(value: Any, label: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or (not allow_empty and not value.strip()):
        _fail("malformed", f"{label} must be a {'string' if allow_empty else 'non-empty string'}")
    if "\x00" in value:
        _fail("safety", f"{label} contains a NUL character")
    return value


def _identifier(value: Any, label: str) -> str:
    text = _string(value, label)
    if not ID_RE.fullmatch(text):
        _fail("malformed", f"{label} must be lowercase hyphen-case", value=text)
    return text


def _run_id(value: Any, label: str = "run_id") -> str:
    text = _string(value, label)
    if not RUN_ID_RE.fullmatch(text):
        _fail("malformed", f"{label} has an invalid format", value=text)
    return text


def _digest(value: Any, label: str) -> str:
    text = _string(value, label)
    if not HEX64_RE.fullmatch(text):
        _fail("malformed", f"{label} must be a lowercase SHA-256 digest")
    return text


def _iso_time(value: Any, label: str) -> str:
    text = _string(value, label)
    try:
        parsed = dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        _fail("malformed", f"{label} must be an ISO-8601 timestamp", value=text)
    if parsed.tzinfo is None:
        _fail("malformed", f"{label} must include a timezone", value=text)
    return text


def _date(value: Any, label: str) -> str:
    text = _string(value, label)
    try:
        dt.date.fromisoformat(text)
    except ValueError:
        _fail("malformed", f"{label} must be an ISO date", value=text)
    return text


def _string_list(value: Any, label: str, *, identifiers: bool = False, allow_empty: bool = True) -> list[str]:
    if not isinstance(value, list) or (not allow_empty and not value):
        _fail("malformed", f"{label} must be {'a non-empty' if not allow_empty else 'an'} array")
    result = [(_identifier(item, f"{label}[{index}]") if identifiers else _string(item, f"{label}[{index}]")) for index, item in enumerate(value)]
    if len(result) != len(set(result)):
        _fail("malformed", f"{label} contains duplicates")
    return result


def _positive_int(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        _fail("malformed", f"{label} must be a positive integer")
    return value


def _search_terms(value: Any, label: str) -> list[str]:
    terms = _string_list(value, label)
    for term in terms:
        if len(term) > 200 or any(character in term for character in "\r\n\t"):
            _fail("malformed", f"{label} contains a non-provider-neutral term")
    return terms


def _canonical_json(value: Any) -> bytes:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    except (TypeError, ValueError) as exc:
        _fail("malformed", "value is not JSON serializable", reason=str(exc))


def _render_json(value: Any) -> bytes:
    try:
        return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
    except (TypeError, ValueError) as exc:
        _fail("malformed", "value is not JSON serializable", reason=str(exc))


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _safe_relative(value: Any, label: str) -> str:
    raw = _string(value, label)
    if "\\" in raw:
        _fail("safety", f"{label} must use forward slashes", value=raw)
    path = PurePosixPath(raw)
    if path.is_absolute() or raw.startswith("/") or ".." in path.parts:
        _fail("safety", f"{label} must stay inside the repository", value=raw)
    normalized = path.as_posix()
    if normalized in {"", "."} or normalized.startswith("../") or normalized != raw:
        _fail("safety", f"{label} must be a non-empty repository-relative path", value=raw)
    reserved = {"con", "prn", "aux", "nul", *(f"com{number}" for number in range(1, 10)), *(f"lpt{number}" for number in range(1, 10))}
    for part in path.parts:
        if any(character in part for character in ':<>"|?*') or any(ord(character) < 32 for character in part):
            _fail("safety", f"{label} contains a platform-unsafe path component", value=raw)
        if part.endswith((".", " ")) or part.split(".", 1)[0].lower() in reserved:
            _fail("safety", f"{label} contains a Windows-reserved path component", value=raw)
    return normalized


def _is_under(path: str, directory: str) -> bool:
    candidate = PurePosixPath(path)
    parent = PurePosixPath(directory)
    try:
        candidate.relative_to(parent)
    except ValueError:
        return False
    return candidate != parent


def _paths_overlap(left: str, right: str) -> bool:
    left_folded = "/".join(part.casefold() for part in PurePosixPath(left).parts)
    right_folded = "/".join(part.casefold() for part in PurePosixPath(right).parts)
    return (
        left_folded == right_folded
        or _is_under(left_folded, right_folded)
        or _is_under(right_folded, left_folded)
    )


def _enum(value: Any, label: str, allowed: set[str]) -> str:
    text = _string(value, label)
    if text not in allowed:
        _fail("malformed", f"{label} has an unsupported value", value=text, allowed=sorted(allowed))
    return text


def _normalize_repository_config(data: Any) -> dict[str, Any]:
    obj = _strict_object(data, "repository config", {"schema", "repository_id", "language", "timezone", "facts"}, {"schema", "repository_id"})
    if obj["schema"] != REPOSITORY_SCHEMA:
        _fail("malformed", "unsupported repository config schema", value=obj["schema"])
    result: dict[str, Any] = {"schema": REPOSITORY_SCHEMA, "repository_id": _identifier(obj["repository_id"], "repository_id")}
    for key in ("language", "timezone"):
        if key in obj:
            result[key] = _string(obj[key], key)
    raw_facts = obj.get("facts", {})
    if not isinstance(raw_facts, dict):
        _fail("malformed", "repository facts must be an object")
    facts: dict[str, Any] = {}
    for raw_id in sorted(raw_facts):
        fact_id = _identifier(raw_id, "fact id")
        record = _strict_object(raw_facts[raw_id], f"fact {fact_id}", {"path", "section", "description"}, {"path"})
        normalized = {"path": _safe_relative(record["path"], f"fact {fact_id}.path")}
        for key in ("section", "description"):
            if key in record:
                normalized[key] = _string(record[key], f"fact {fact_id}.{key}")
        facts[fact_id] = normalized
    result["facts"] = facts
    return result


def _normalize_adapter(data: Any, label: str) -> dict[str, Any]:
    obj = _strict_object(data, label, {"adapter_id", "version", "heading", "anchor", "id_policy", "allowed_actions", "status_terms", "priority_terms"}, {"adapter_id", "version"})
    adapter_id = _identifier(obj["adapter_id"], f"{label}.adapter_id")
    if adapter_id not in ADAPTER_CATALOG:
        _fail("malformed", f"{label} uses an unknown adapter", adapter_id=adapter_id)
    version = _positive_int(obj["version"], f"{label}.version")
    if version not in ADAPTER_CATALOG[adapter_id]["versions"]:
        _fail("malformed", f"{label} uses an unsupported adapter version", adapter_id=adapter_id, version=version)
    result: dict[str, Any] = {"adapter_id": adapter_id, "version": version}
    for key in ("heading", "anchor"):
        if key in obj:
            result[key] = _string(obj[key], f"{label}.{key}")
    if "id_policy" in obj:
        result["id_policy"] = _enum(obj["id_policy"], f"{label}.id_policy", {"opaque", "section-local-suffix", "stable-id"})
    if "allowed_actions" in obj:
        actions = _string_list(obj["allowed_actions"], f"{label}.allowed_actions", allow_empty=False)
        unsupported = sorted(set(actions) - set(ADAPTER_CATALOG[adapter_id]["actions"]))
        if unsupported:
            _fail("malformed", f"{label}.allowed_actions exceeds the adapter allowlist", actions=unsupported)
        result["allowed_actions"] = sorted(actions)
    else:
        result["allowed_actions"] = list(ADAPTER_CATALOG[adapter_id]["actions"])
    for key in ("status_terms", "priority_terms"):
        if key in obj:
            result[key] = _string_list(obj[key], f"{label}.{key}")
    return result


def _normalize_skill_config(data: Any, repository: Mapping[str, Any]) -> dict[str, Any]:
    allowed = {"schema", "skill", "storage", "preferences", "sources", "queries", "fact_refs", "overlays", "modules"}
    obj = _strict_object(data, "resource-planning config", allowed, {"schema", "skill", "storage", "sources", "queries", "modules"})
    if obj["schema"] != CONFIG_SCHEMA or obj["skill"] != "resource-planning":
        _fail("malformed", "resource-planning config identity or schema is invalid")

    storage_obj = _strict_object(obj["storage"], "storage", {"registry_path", "report_directory", "research_brief_directory", "journal_path"}, {"registry_path", "report_directory", "research_brief_directory", "journal_path"})
    storage = {key: _safe_relative(storage_obj[key], f"storage.{key}") for key in sorted(storage_obj)}
    if storage["journal_path"] in {storage["registry_path"]} or _is_under(storage["journal_path"], storage["report_directory"]) or _is_under(storage["journal_path"], storage["research_brief_directory"]):
        _fail("safety", "journal_path must be separate from managed content targets")

    preferences_obj = _strict_object(obj.get("preferences", {}), "preferences", {"bootstrap_days", "decision_unit_soft_target", "timezone", "report_naming"})
    preferences: dict[str, Any] = {}
    for key in ("bootstrap_days", "decision_unit_soft_target"):
        if key in preferences_obj:
            preferences[key] = _positive_int(preferences_obj[key], f"preferences.{key}")
    if "timezone" in preferences_obj:
        preferences["timezone"] = _string(preferences_obj["timezone"], "preferences.timezone")
    if "report_naming" in preferences_obj:
        preferences["report_naming"] = _enum(preferences_obj["report_naming"], "preferences.report_naming", {"run-id", "date", "iso-week"})

    modules: list[dict[str, Any]] = []
    module_ids: set[str] = set()
    module_paths: set[str] = set()
    if not isinstance(obj["modules"], list):
        _fail("malformed", "modules must be an array")
    for index, raw in enumerate(obj["modules"]):
        label = f"modules[{index}]"
        record = _strict_object(raw, label, {"module_id", "display_name", "aliases", "portfolio_path", "progress_projection", "report_group", "adapter"}, {"module_id", "display_name", "portfolio_path", "adapter"})
        module_id = _identifier(record["module_id"], f"{label}.module_id")
        if module_id in module_ids:
            _fail("malformed", "duplicate module_id", module_id=module_id)
        module_ids.add(module_id)
        portfolio = _safe_relative(record["portfolio_path"], f"{label}.portfolio_path")
        adapter = _normalize_adapter(record["adapter"], f"{label}.adapter")
        normalized: dict[str, Any] = {
            "module_id": module_id,
            "display_name": _string(record["display_name"], f"{label}.display_name"),
            "aliases": _string_list(record.get("aliases", []), f"{label}.aliases"),
            "portfolio_path": portfolio,
            "adapter": adapter,
        }
        if portfolio in module_paths:
            _fail("malformed", "module portfolio paths must be unique", path=portfolio)
        module_paths.add(portfolio)
        if "progress_projection" in record:
            if not ADAPTER_CATALOG[adapter["adapter_id"]]["supports_progress_projection"]:
                _fail("malformed", "adapter does not support a generic progress projection", module_id=module_id, adapter_id=adapter["adapter_id"])
            progress = _safe_relative(record["progress_projection"], f"{label}.progress_projection")
            if progress in module_paths:
                _fail("malformed", "module managed paths must be unique", path=progress)
            module_paths.add(progress)
            normalized["progress_projection"] = progress
        if "report_group" in record:
            normalized["report_group"] = _identifier(record["report_group"], f"{label}.report_group")
        modules.append(normalized)

    sources: list[dict[str, Any]] = []
    source_ids: set[str] = set()
    if not isinstance(obj["sources"], list):
        _fail("malformed", "sources must be an array")
    for index, raw in enumerate(obj["sources"]):
        label = f"sources[{index}]"
        record = _strict_object(raw, label, {"source_id", "kind", "locator", "modules", "role_hint", "enabled", "cadence", "resource_types"}, {"source_id", "kind", "locator", "modules", "role_hint", "enabled"})
        source_id = _identifier(record["source_id"], f"{label}.source_id")
        if source_id in source_ids:
            _fail("malformed", "duplicate source_id", source_id=source_id)
        source_ids.add(source_id)
        mapped = _string_list(record["modules"], f"{label}.modules", identifiers=True, allow_empty=False)
        unknown = sorted(set(mapped) - module_ids)
        if unknown:
            _fail("malformed", f"{label} references unknown modules", modules=unknown)
        if not isinstance(record["enabled"], bool):
            _fail("malformed", f"{label}.enabled must be boolean")
        kind = _enum(record["kind"], f"{label}.kind", SOURCE_KINDS)
        locator = _string(record["locator"], f"{label}.locator")
        if kind in {"web", "feed", "repository", "paper-index"}:
            locator = _canonical_url(locator, f"{label}.locator")
            if urlsplit(locator).query:
                _fail("safety", f"{label}.locator must not store query parameters or access tokens")
        else:
            expected_prefix = f"{kind}:"
            if not locator.startswith(expected_prefix) or not re.fullmatch(r"[a-z]+:[A-Za-z0-9][A-Za-z0-9._:/+-]{0,255}", locator):
                _fail("malformed", f"{label}.locator must be a stable opaque {expected_prefix} identifier")
        role_hint = _enum(record["role_hint"], f"{label}.role_hint", SOURCE_ROLES)
        if kind in {"manual", "private"} and role_hint != "discovery-index":
            _fail("malformed", f"{label} manual/private sources may only be discovery signals")
        normalized = {
            "source_id": source_id,
            "kind": kind,
            "locator": locator,
            "modules": sorted(mapped),
            "role_hint": role_hint,
            "enabled": record["enabled"],
        }
        if "cadence" in record:
            normalized["cadence"] = _enum(record["cadence"], f"{label}.cadence", {"manual", "daily", "weekly", "monthly", "quarterly"})
        if "resource_types" in record:
            types = _string_list(record["resource_types"], f"{label}.resource_types", allow_empty=False)
            unknown_types = sorted(set(types) - RESOURCE_TYPES)
            if unknown_types:
                _fail("malformed", f"{label}.resource_types has unsupported values", values=unknown_types)
            normalized["resource_types"] = sorted(types)
        sources.append(normalized)

    queries: list[dict[str, Any]] = []
    query_ids: set[str] = set()
    if not isinstance(obj["queries"], list):
        _fail("malformed", "queries must be an array")
    for index, raw in enumerate(obj["queries"]):
        label = f"queries[{index}]"
        record = _strict_object(raw, label, {"query_id", "all_terms", "any_terms", "exclude_terms", "domains", "resource_types", "modules", "enabled"}, {"query_id", "all_terms", "any_terms", "exclude_terms", "domains", "resource_types", "modules", "enabled"})
        query_id = _identifier(record["query_id"], f"{label}.query_id")
        if query_id in query_ids:
            _fail("malformed", "duplicate query_id", query_id=query_id)
        query_ids.add(query_id)
        all_terms = _search_terms(record["all_terms"], f"{label}.all_terms")
        any_terms = _search_terms(record["any_terms"], f"{label}.any_terms")
        if not all_terms and not any_terms:
            _fail("malformed", f"{label} needs at least one all/any term")
        mapped = _string_list(record["modules"], f"{label}.modules", identifiers=True, allow_empty=False)
        unknown = sorted(set(mapped) - module_ids)
        if unknown:
            _fail("malformed", f"{label} references unknown modules", modules=unknown)
        if not isinstance(record["enabled"], bool):
            _fail("malformed", f"{label}.enabled must be boolean")
        types = _string_list(record["resource_types"], f"{label}.resource_types", allow_empty=False)
        unknown_types = sorted(set(types) - RESOURCE_TYPES)
        if unknown_types:
            _fail("malformed", f"{label}.resource_types has unsupported values", values=unknown_types)
        domains = [domain.lower() for domain in _string_list(record["domains"], f"{label}.domains")]
        if any(not re.fullmatch(r"(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)*[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", domain) for domain in domains):
            _fail("malformed", f"{label}.domains must contain host names only")
        queries.append({
            "query_id": query_id,
            "all_terms": all_terms,
            "any_terms": any_terms,
            "exclude_terms": _search_terms(record["exclude_terms"], f"{label}.exclude_terms"),
            "domains": domains,
            "resource_types": sorted(types),
            "modules": sorted(mapped),
            "enabled": record["enabled"],
        })

    fact_refs: list[dict[str, Any]] = []
    seen_facts: set[str] = set()
    raw_fact_refs = obj.get("fact_refs", [])
    if not isinstance(raw_fact_refs, list):
        _fail("malformed", "fact_refs must be an array")
    for index, raw in enumerate(raw_fact_refs):
        label = f"fact_refs[{index}]"
        record = _strict_object(raw, label, {"fact_id", "kind", "required", "modules"}, {"fact_id", "kind", "required", "modules"})
        fact_id = _identifier(record["fact_id"], f"{label}.fact_id")
        if fact_id in seen_facts:
            _fail("malformed", "duplicate fact_ref", fact_id=fact_id)
        if fact_id not in repository["facts"]:
            _fail("malformed", f"{label} references an unknown repository fact", fact_id=fact_id)
        seen_facts.add(fact_id)
        if not isinstance(record["required"], bool):
            _fail("malformed", f"{label}.required must be boolean")
        mapped = _string_list(record["modules"], f"{label}.modules", identifiers=True)
        unknown = sorted(set(mapped) - module_ids)
        if unknown:
            _fail("malformed", f"{label} references unknown modules", modules=unknown)
        fact_refs.append({"fact_id": fact_id, "kind": _enum(record["kind"], f"{label}.kind", {"file", "collection"}), "required": record["required"], "modules": sorted(mapped)})

    overlays: list[dict[str, Any]] = []
    overlay_ids: set[str] = set()
    raw_overlays = obj.get("overlays", [])
    if not isinstance(raw_overlays, list):
        _fail("malformed", "overlays must be an array")
    for index, raw in enumerate(raw_overlays):
        label = f"overlays[{index}]"
        record = _strict_object(raw, label, {"overlay_id", "fact_refs", "modules", "source_ids", "query_ids", "priority", "valid_from", "valid_until"}, {"overlay_id", "fact_refs", "modules", "source_ids", "query_ids", "priority", "valid_from", "valid_until"})
        overlay_id = _identifier(record["overlay_id"], f"{label}.overlay_id")
        if overlay_id in overlay_ids:
            _fail("malformed", "duplicate overlay_id", overlay_id=overlay_id)
        overlay_ids.add(overlay_id)
        refs = _string_list(record["fact_refs"], f"{label}.fact_refs", identifiers=True, allow_empty=False)
        if unknown := sorted(set(refs) - seen_facts):
            _fail("malformed", f"{label} references facts not declared in fact_refs", facts=unknown)
        mapped = _string_list(record["modules"], f"{label}.modules", identifiers=True)
        if unknown := sorted(set(mapped) - module_ids):
            _fail("malformed", f"{label} references unknown modules", modules=unknown)
        sids = _string_list(record["source_ids"], f"{label}.source_ids", identifiers=True)
        if unknown := sorted(set(sids) - source_ids):
            _fail("malformed", f"{label} references unknown sources", sources=unknown)
        qids = _string_list(record["query_ids"], f"{label}.query_ids", identifiers=True)
        if unknown := sorted(set(qids) - query_ids):
            _fail("malformed", f"{label} references unknown queries", queries=unknown)
        priority = record["priority"]
        if isinstance(priority, bool) or not isinstance(priority, int) or not -100 <= priority <= 100:
            _fail("malformed", f"{label}.priority must be an integer from -100 to 100")
        valid_from = _date(record["valid_from"], f"{label}.valid_from")
        valid_until = _date(record["valid_until"], f"{label}.valid_until")
        if valid_until < valid_from:
            _fail("malformed", f"{label} validity range is reversed")
        overlays.append({"overlay_id": overlay_id, "fact_refs": sorted(refs), "modules": sorted(mapped), "source_ids": sorted(sids), "query_ids": sorted(qids), "priority": priority, "valid_from": valid_from, "valid_until": valid_until})

    managed_paths: list[tuple[str, str]] = [
        ("storage.registry_path", storage["registry_path"]),
        ("storage.report_directory", storage["report_directory"]),
        ("storage.research_brief_directory", storage["research_brief_directory"]),
        ("storage.journal_path", storage["journal_path"]),
    ]
    for module in modules:
        managed_paths.append(
            (f"module {module['module_id']} portfolio_path", module["portfolio_path"])
        )
        if "progress_projection" in module:
            managed_paths.append(
                (
                    f"module {module['module_id']} progress_projection",
                    module["progress_projection"],
                )
            )
    for index, (left_label, left_path) in enumerate(managed_paths):
        for right_label, right_path in managed_paths[index + 1 :]:
            if _paths_overlap(left_path, right_path):
                _fail(
                    "safety",
                    "managed resource-planning paths must be disjoint",
                    left=left_label,
                    left_path=left_path,
                    right=right_label,
                    right_path=right_path,
                )
    referenced_fact_ids = {ref["fact_id"] for ref in fact_refs}
    for managed_label, managed_path in managed_paths:
        for fact_id in sorted(referenced_fact_ids):
            fact = repository["facts"][fact_id]
            if _paths_overlap(managed_path, fact["path"]):
                _fail(
                    "safety",
                    "managed resource-planning path overlaps a repository fact",
                    managed=managed_label,
                    managed_path=managed_path,
                    fact_id=fact_id,
                    fact_path=fact["path"],
                )

    return {
        "schema": CONFIG_SCHEMA,
        "skill": "resource-planning",
        "storage": storage,
        "preferences": preferences,
        "sources": sorted(sources, key=lambda item: item["source_id"]),
        "queries": sorted(queries, key=lambda item: item["query_id"]),
        "fact_refs": sorted(fact_refs, key=lambda item: item["fact_id"]),
        "overlays": sorted(overlays, key=lambda item: item["overlay_id"]),
        "modules": sorted(modules, key=lambda item: item["module_id"]),
    }


def validate_materialized_context(repository_config: Any, skill_config: Any) -> dict[str, Any]:
    """Validate public config without filesystem, Git, network, or subprocess use.

    The central materializer owns filesystem trust checks.  It calls this pure
    function and wraps the returned context/allowlists with source digests.
    """

    repository = _normalize_repository_config(repository_config)
    configuration = _normalize_skill_config(skill_config, repository)
    referenced_fact_ids = {ref["fact_id"] for ref in configuration["fact_refs"]}
    runtime_repository = {key: copy.deepcopy(value) for key, value in repository.items() if key != "facts"}
    runtime_repository["facts"] = {fact_id: copy.deepcopy(repository["facts"][fact_id]) for fact_id in sorted(referenced_fact_ids)}
    tracked_files: set[str] = set()
    tracked_collections: set[str] = set()
    for ref in configuration["fact_refs"]:
        path = repository["facts"][ref["fact_id"]]["path"]
        (tracked_files if ref["kind"] == "file" else tracked_collections).add(path)
    storage = configuration["storage"]
    write_paths = {
        storage["registry_path"],
        storage["report_directory"],
        storage["research_brief_directory"],
        storage["journal_path"],
    }
    for module in configuration["modules"]:
        write_paths.add(module["portfolio_path"])
        if "progress_projection" in module:
            write_paths.add(module["progress_projection"])
    context = {
        "schema": CONTEXT_SCHEMA,
        "repository": runtime_repository,
        "configuration": configuration,
        "adapter_catalog": copy.deepcopy(ADAPTER_CATALOG),
    }
    return {
        "context": context,
        "tracked_files": sorted(tracked_files),
        "tracked_collections": sorted(tracked_collections),
        "write_paths": sorted(write_paths),
    }


def validate_runtime_wrapper(data: Any) -> dict[str, Any]:
    """Validate the materializer-owned wrapper and its delegated allowlists."""

    obj = _strict_object(data, "managed context wrapper", {"version", "manager", "skill", "repository_id", "sources", "context", "allowlist"}, {"version", "manager", "skill", "repository_id", "sources", "context", "allowlist"})
    if obj["version"] != WRAPPER_VERSION or obj["manager"] != "agent-skills" or obj["skill"] != "resource-planning":
        _fail("malformed", "managed context wrapper identity is invalid")
    repository_id = _identifier(obj["repository_id"], "wrapper.repository_id")
    sources_obj = _strict_object(obj["sources"], "wrapper.sources", {"repository", "skill"}, {"repository", "skill"})
    sources: dict[str, Any] = {}
    for name in ("repository", "skill"):
        record = _strict_object(sources_obj[name], f"wrapper.sources.{name}", {"path", "digest"}, {"path", "digest"})
        sources[name] = {"path": _safe_relative(record["path"], f"wrapper.sources.{name}.path"), "digest": _digest(record["digest"], f"wrapper.sources.{name}.digest")}

    context_obj = _strict_object(obj["context"], "wrapper.context", {"schema", "repository", "configuration", "adapter_catalog"}, {"schema", "repository", "configuration", "adapter_catalog"})
    if context_obj["schema"] != CONTEXT_SCHEMA:
        _fail("malformed", "managed context has an unsupported schema")
    expected = validate_materialized_context(context_obj["repository"], context_obj["configuration"])
    if expected["context"] != context_obj:
        _fail("integrity", "managed context is not the canonical validator output")
    if context_obj["repository"]["repository_id"] != repository_id:
        _fail("integrity", "wrapper repository_id does not match managed context")

    allowlist_obj = _strict_object(obj["allowlist"], "wrapper.allowlist", {"tracked_files", "tracked_collections", "write_paths"}, {"tracked_files", "tracked_collections", "write_paths"})
    allowlist = {key: sorted(_string_list(allowlist_obj[key], f"wrapper.allowlist.{key}")) for key in ("tracked_files", "tracked_collections", "write_paths")}
    for key in allowlist:
        allowlist[key] = [_safe_relative(path, f"wrapper.allowlist.{key}") for path in allowlist[key]]
    if allowlist["tracked_collections"] != expected["tracked_collections"] or allowlist["write_paths"] != expected["write_paths"]:
        _fail("integrity", "wrapper collection/write roots do not match validator output")
    explicit_files = set(expected["tracked_files"])
    actual_files = set(allowlist["tracked_files"])
    if not explicit_files <= actual_files:
        _fail("integrity", "wrapper omits an explicitly tracked fact file", missing=sorted(explicit_files - actual_files))
    collection_roots = expected["tracked_collections"]
    invalid_expansions = sorted(path for path in actual_files - explicit_files if not any(_is_under(path, root) for root in collection_roots))
    if invalid_expansions:
        _fail("integrity", "wrapper tracked_files contains members outside declared collection roots", paths=invalid_expansions)
    return {
        "version": WRAPPER_VERSION,
        "manager": "agent-skills",
        "skill": "resource-planning",
        "repository_id": repository_id,
        "sources": sources,
        "context": expected["context"],
        "allowlist": allowlist,
    }


def _path_present(path: Path) -> bool:
    return os.path.lexists(os.fspath(path))


def _is_link_or_junction(path: Path) -> bool:
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
    try:
        attributes = getattr(path.lstat(), "st_file_attributes", 0)
    except OSError:
        return True
    return bool(attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))


def _absolute(path: Path) -> Path:
    return Path(os.path.abspath(os.fspath(path)))


def _repo_path(repo: Path, relative: str, *, label: str, leaf_kind: str = "file", allow_missing_leaf: bool = True) -> Path:
    safe = _safe_relative(relative, label)
    root = _absolute(repo)
    if not _path_present(root) or _is_link_or_junction(root) or not root.is_dir():
        _fail("safety", "repository root must be an existing real directory", path=os.fspath(root))
    candidate = _absolute(root.joinpath(*PurePosixPath(safe).parts))
    try:
        common = os.path.commonpath([os.fspath(root), os.fspath(candidate)])
    except ValueError:
        _fail("safety", f"{label} escapes the repository", path=safe)
    if os.path.normcase(common) != os.path.normcase(os.fspath(root)):
        _fail("safety", f"{label} escapes the repository", path=safe)
    current = root
    parts = PurePosixPath(safe).parts
    for index, part in enumerate(parts):
        current /= part
        if not _path_present(current):
            if index < len(parts) - 1 or not allow_missing_leaf:
                _fail("safety", f"{label} has a missing parent or required path", path=safe)
            continue
        if _is_link_or_junction(current):
            _fail("safety", f"{label} crosses a symlink, junction, or reparse point", path=safe)
        try:
            mode = current.lstat().st_mode
        except OSError as exc:
            _fail("safety", f"cannot inspect {label}", path=safe, reason=str(exc))
        if index < len(parts) - 1 and not stat.S_ISDIR(mode):
            _fail("safety", f"{label} crosses a non-directory component", path=safe)
        if index == len(parts) - 1:
            if leaf_kind == "file" and not stat.S_ISREG(mode):
                _fail("safety", f"{label} must be a regular file", path=safe)
            if leaf_kind == "directory" and not stat.S_ISDIR(mode):
                _fail("safety", f"{label} must be a real directory", path=safe)
    return candidate


def _argument_relative(repo: Path, raw: str, label: str) -> str:
    path = Path(raw)
    absolute = _absolute(path if path.is_absolute() else _absolute(repo) / path)
    try:
        common = os.path.commonpath([os.fspath(_absolute(repo)), os.fspath(absolute)])
    except ValueError:
        _fail("safety", f"{label} must be inside the repository")
    if os.path.normcase(common) != os.path.normcase(os.fspath(_absolute(repo))):
        _fail("safety", f"{label} must be inside the repository")
    return absolute.relative_to(_absolute(repo)).as_posix()


def _read_bytes(path: Path, label: str) -> bytes:
    try:
        return path.read_bytes()
    except OSError as exc:
        _fail("integrity", f"cannot read {label}", path=os.fspath(path), reason=str(exc))


def _read_json_path(path: Path, label: str) -> Any:
    data = _read_bytes(path, label)
    try:
        return json.loads(data.decode("utf-8"))
    except UnicodeDecodeError:
        _fail("malformed", f"{label} must be UTF-8", path=os.fspath(path))
    except json.JSONDecodeError as exc:
        _fail("malformed", f"{label} contains invalid JSON", path=os.fspath(path), reason=str(exc))


def _validate_source_binding(repo: Path, wrapper: Mapping[str, Any]) -> None:
    """Bind wrapper context to the exact repository/Skill config source bytes."""

    loaded: dict[str, Any] = {}
    seen_paths: set[str] = set()
    for name in ("repository", "skill"):
        source = wrapper["sources"][name]
        if source["path"] in seen_paths:
            _fail("integrity", "managed repository and Skill config sources must be distinct")
        seen_paths.add(source["path"])
        path = _repo_path(repo, source["path"], label=f"managed {name} config source", leaf_kind="file", allow_missing_leaf=False)
        data = _read_bytes(path, f"managed {name} config source")
        if _sha256(data) != source["digest"]:
            _fail("conflict", "managed config source digest changed; re-materialize", source=name)
        try:
            loaded[name] = json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            _fail("malformed", "managed config source is not valid UTF-8 JSON", source=name, reason=str(exc))
    expected = validate_materialized_context(loaded["repository"], loaded["skill"])
    if expected["context"] != wrapper["context"]:
        _fail("integrity", "managed wrapper context does not match its bound config source bytes")


def _snapshot_path(repo: Path, relative: str, kind: str, label: str) -> dict[str, str]:
    if kind != "file":
        _fail("integrity", "runtime dependencies must be expanded tracked files, never collection scans", kind=kind, path=relative)
    path = _repo_path(repo, relative, label=label, leaf_kind="file", allow_missing_leaf=True)
    sha = _sha256(_read_bytes(path, label)) if _path_present(path) else ABSENT
    return {"path": relative, "kind": kind, "sha256": sha}


def _canonical_url(value: str, label: str) -> str:
    if any(character in value for character in "\r\n\t"):
        _fail("malformed", f"{label} contains URL control characters")
    try:
        parts = urlsplit(value)
    except ValueError:
        _fail("malformed", f"{label} is not a valid URL", value=value)
    scheme = parts.scheme.lower()
    if scheme not in {"http", "https"} or not parts.netloc:
        _fail("malformed", f"{label} must be an HTTP(S) URL", value=value)
    if parts.username or parts.password:
        _fail("safety", f"{label} must not contain credentials")
    host = (parts.hostname or "").lower()
    try:
        port = parts.port
    except ValueError:
        _fail("malformed", f"{label} has an invalid port", value=value)
    netloc = host
    if port and not ((scheme == "http" and port == 80) or (scheme == "https" and port == 443)):
        netloc = f"{host}:{port}"
    path = re.sub(r"/{2,}", "/", parts.path or "/")
    if path != "/":
        path = path.rstrip("/")
    return urlunsplit((scheme, netloc, path, parts.query, ""))


def normalize_work_id(identity: Any) -> tuple[str, str]:
    """Normalize an exact native identity into a stable work_id and locator."""

    obj = _strict_object(identity, "identity", {"kind", "value"}, {"kind", "value"})
    kind = _enum(obj["kind"], "identity.kind", {"doi", "arxiv", "github", "native", "url"})
    value = _string(obj["value"], "identity.value").strip()
    if kind == "doi":
        lowered = value.lower()
        for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
            if lowered.startswith(prefix):
                lowered = lowered[len(prefix):]
                break
        if not DOI_RE.fullmatch(lowered) or any(character.isspace() for character in lowered):
            _fail("malformed", "identity.value is not a valid DOI")
        return f"doi:{lowered}", f"https://doi.org/{lowered}"
    if kind == "arxiv":
        lowered = value.lower()
        for prefix in ("https://arxiv.org/abs/", "http://arxiv.org/abs/", "arxiv:"):
            if lowered.startswith(prefix):
                lowered = lowered[len(prefix):]
                break
        if not ARXIV_RE.fullmatch(lowered):
            _fail("malformed", "identity.value is not a valid arXiv identifier")
        work = re.sub(r"v\d+$", "", lowered)
        return f"arxiv:{work}", f"https://arxiv.org/abs/{work}"
    if kind == "github":
        lowered = value.strip().lower()
        if lowered.startswith("https://github.com/"):
            lowered = lowered[len("https://github.com/"):]
        lowered = lowered.removesuffix(".git").strip("/")
        if not re.fullmatch(r"[a-z0-9_.-]+/[a-z0-9_.-]+", lowered):
            _fail("malformed", "identity.value must be a GitHub owner/repo")
        return f"github:{lowered}", f"https://github.com/{lowered}"
    if kind == "native":
        if ":" not in value:
            _fail("malformed", "native identity must be namespace:value")
        namespace, native = value.split(":", 1)
        namespace = _identifier(namespace, "native identity namespace")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/+-]{0,255}", native):
            _fail("malformed", "native identity value is invalid")
        return f"native:{namespace}:{native}", f"{namespace}:{native}"
    url = _canonical_url(value, "identity.value")
    return f"url:{url}", url


def _normalize_revision(value: Any) -> str:
    revision = _string(value, "revision_key")
    if revision != "unspecified" and not REVISION_RE.fullmatch(revision):
        _fail("malformed", "revision_key has an invalid format", value=revision)
    return revision


def _stable_id(prefix: str, *parts: Any, length: int = 24) -> str:
    return f"{prefix}_{_sha256(_canonical_json(parts))[:length]}"


def _empty_registry() -> dict[str, Any]:
    return {"schema": REGISTRY_SCHEMA, "generation": 0, "resources": [], "candidates": [], "coverage": [], "runs": []}


def reduce_events(events: Any, label: str = "events", *, allow_preview_sentinel: bool = False) -> str:
    if not isinstance(events, list) or not events:
        _fail("integrity", f"{label} must be a non-empty event array")
    state: str | None = None
    seen_ids: set[str] = set()
    for index, raw in enumerate(events):
        event_label = f"{label}[{index}]"
        event = _strict_object(raw, event_label, {"event_id", "sequence", "from_state", "to_state", "at", "run_id", "operation_kind", "reason", "preview_digest"}, {"event_id", "sequence", "from_state", "to_state", "at", "run_id", "operation_kind", "reason"})
        event_id = _string(event["event_id"], f"{event_label}.event_id")
        if event_id in seen_ids:
            _fail("integrity", f"{label} contains duplicate event IDs")
        seen_ids.add(event_id)
        if event["sequence"] != index + 1:
            _fail("integrity", f"{event_label}.sequence is not contiguous")
        if event["from_state"] != state:
            _fail("integrity", f"{event_label}.from_state disagrees with reducer", expected=state, actual=event["from_state"])
        target = _enum(event["to_state"], f"{event_label}.to_state", PERSISTENT_STATES)
        if target not in TRANSITIONS[state]:
            _fail("integrity", f"illegal candidate state transition", from_state=state, to_state=target)
        _iso_time(event["at"], f"{event_label}.at")
        _run_id(event["run_id"], f"{event_label}.run_id")
        operation = _enum(event["operation_kind"], f"{event_label}.operation_kind", {"refresh", "review"})
        _string(event["reason"], f"{event_label}.reason")
        if operation == "refresh" and target not in {"draft", "blocked", "qualified"}:
            _fail("integrity", "refresh event may only register draft, blocked, or qualified state", to_state=target)
        has_preview = "preview_digest" in event
        if target == "approved":
            if not has_preview:
                _fail("integrity", "approved event must bind preview_digest")
            preview = event["preview_digest"]
            if preview == PREVIEW_SENTINEL and not allow_preview_sentinel:
                _fail("integrity", "prepared preview sentinel must never persist in registry")
            if preview != PREVIEW_SENTINEL:
                _digest(preview, f"{event_label}.preview_digest")
            if operation != "review":
                _fail("integrity", "only review may create approved events")
        elif has_preview:
            _fail("integrity", "only approved events may contain preview_digest")
        state = target
    assert state is not None
    return state


def _validate_claim(raw: Any, label: str) -> dict[str, Any]:
    obj = _strict_object(raw, label, {"claim_id", "text", "status", "scope", "evidence"}, {"claim_id", "text", "status", "scope", "evidence"})
    claim_id = _string(obj["claim_id"], f"{label}.claim_id")
    text = _string(obj["text"], f"{label}.text")
    status = _enum(obj["status"], f"{label}.status", CLAIM_STATES)
    scope = _string(obj["scope"], f"{label}.scope")
    if not isinstance(obj["evidence"], list) or not obj["evidence"]:
        _fail("malformed", f"{label}.evidence must be a non-empty array")
    evidence: list[dict[str, Any]] = []
    for index, item in enumerate(obj["evidence"]):
        ev_label = f"{label}.evidence[{index}]"
        ev = _strict_object(item, ev_label, {"locator", "role", "checked_at", "direction", "note"}, {"locator", "role", "checked_at", "direction"})
        normalized = {
            "locator": _string(ev["locator"], f"{ev_label}.locator"),
            "role": _enum(ev["role"], f"{ev_label}.role", SOURCE_ROLES),
            "checked_at": _iso_time(ev["checked_at"], f"{ev_label}.checked_at"),
            "direction": _enum(ev["direction"], f"{ev_label}.direction", {"supports", "refutes", "context"}),
        }
        if "note" in ev:
            normalized["note"] = _string(ev["note"], f"{ev_label}.note")
        evidence.append(normalized)
    expected_id = _stable_id("claim", text, scope)
    if claim_id != expected_id:
        _fail("integrity", f"{label}.claim_id is not deterministic", expected=expected_id)
    return {"claim_id": claim_id, "text": text, "status": status, "scope": scope, "evidence": evidence}


def validate_registry(data: Any, *, allow_preview_sentinel: bool = False) -> dict[str, Any]:
    obj = _strict_object(data, "registry", {"schema", "generation", "resources", "candidates", "coverage", "runs"}, {"schema", "generation", "resources", "candidates", "coverage", "runs"})
    if obj["schema"] != REGISTRY_SCHEMA:
        _fail("malformed", "unsupported registry schema", value=obj["schema"])
    generation = obj["generation"]
    if isinstance(generation, bool) or not isinstance(generation, int) or generation < 0:
        _fail("malformed", "registry.generation must be a non-negative integer")
    if not all(isinstance(obj[key], list) for key in ("resources", "candidates", "coverage", "runs")):
        _fail("malformed", "registry collections must be arrays")

    resources: list[dict[str, Any]] = []
    resource_keys: set[tuple[str, str]] = set()
    aliases: dict[str, str] = {}
    for index, raw in enumerate(obj["resources"]):
        label = f"registry.resources[{index}]"
        record = _strict_object(raw, label, {"work_id", "revision_key", "title", "canonical_locator", "aliases", "module_ids", "relations", "claims", "first_seen_run", "last_seen_runs"}, {"work_id", "revision_key", "title", "canonical_locator", "aliases", "module_ids", "relations", "claims", "first_seen_run", "last_seen_runs"})
        work_id = _string(record["work_id"], f"{label}.work_id")
        revision = _normalize_revision(record["revision_key"])
        key = (work_id, revision)
        if key in resource_keys:
            _fail("integrity", "registry contains duplicate resource revisions", work_id=work_id, revision_key=revision)
        resource_keys.add(key)
        normalized_aliases = sorted(_string_list(record["aliases"], f"{label}.aliases"))
        canonical = _string(record["canonical_locator"], f"{label}.canonical_locator")
        for alias in [canonical, *normalized_aliases]:
            owner = aliases.get(alias)
            if owner is not None and owner != work_id:
                _fail("integrity", "alias maps to multiple work IDs", alias=alias)
            aliases[alias] = work_id
        relations: list[dict[str, Any]] = []
        if not isinstance(record["relations"], list):
            _fail("malformed", f"{label}.relations must be an array")
        for rel_index, item in enumerate(record["relations"]):
            rel_label = f"{label}.relations[{rel_index}]"
            rel = _strict_object(item, rel_label, {"kind", "target_work_id", "target_revision_key"}, {"kind", "target_work_id"})
            normalized_rel = {"kind": _enum(rel["kind"], f"{rel_label}.kind", RELATIONS), "target_work_id": _string(rel["target_work_id"], f"{rel_label}.target_work_id")}
            if "target_revision_key" in rel:
                normalized_rel["target_revision_key"] = _normalize_revision(rel["target_revision_key"])
            relations.append(normalized_rel)
        claims = [_validate_claim(item, f"{label}.claims[{claim_index}]") for claim_index, item in enumerate(record["claims"])] if isinstance(record["claims"], list) else _fail("malformed", f"{label}.claims must be an array")
        if len({claim["claim_id"] for claim in claims}) != len(claims):
            _fail("integrity", f"{label}.claims contains duplicate IDs")
        resources.append({
            "work_id": work_id,
            "revision_key": revision,
            "title": _string(record["title"], f"{label}.title"),
            "canonical_locator": canonical,
            "aliases": normalized_aliases,
            "module_ids": sorted(_string_list(record["module_ids"], f"{label}.module_ids", identifiers=True, allow_empty=False)),
            "relations": sorted(relations, key=lambda item: (item["kind"], item["target_work_id"], item.get("target_revision_key", ""))),
            "claims": sorted(claims, key=lambda item: item["claim_id"]),
            "first_seen_run": _run_id(record["first_seen_run"], f"{label}.first_seen_run"),
            "last_seen_runs": sorted(_string_list(record["last_seen_runs"], f"{label}.last_seen_runs", allow_empty=False)),
        })

    candidates: list[dict[str, Any]] = []
    candidate_ids: set[str] = set()
    decision_ids: set[str] = set()
    event_ids: set[str] = set()
    for index, raw in enumerate(obj["candidates"]):
        label = f"registry.candidates[{index}]"
        record = _strict_object(raw, label, {"candidate_id", "decision_unit_id", "work_id", "revision_key", "module_id", "action", "target_slot", "claim_ids", "preserve_learning_state", "review_after", "run_ids", "events", "current_state"}, {"candidate_id", "decision_unit_id", "work_id", "revision_key", "module_id", "action", "target_slot", "claim_ids", "preserve_learning_state", "review_after", "run_ids", "events", "current_state"})
        candidate_id = _string(record["candidate_id"], f"{label}.candidate_id")
        decision_id = _string(record["decision_unit_id"], f"{label}.decision_unit_id")
        if candidate_id in candidate_ids or decision_id in decision_ids:
            _fail("integrity", "registry contains duplicate candidate or decision unit IDs")
        candidate_ids.add(candidate_id)
        decision_ids.add(decision_id)
        work_id = _string(record["work_id"], f"{label}.work_id")
        revision = _normalize_revision(record["revision_key"])
        if (work_id, revision) not in resource_keys:
            _fail("integrity", f"{label} references a missing resource revision")
        resource_claim_ids = {claim["claim_id"] for resource in resources if resource["work_id"] == work_id and resource["revision_key"] == revision for claim in resource["claims"]}
        claim_ids = sorted(_string_list(record["claim_ids"], f"{label}.claim_ids"))
        if not set(claim_ids) <= resource_claim_ids:
            _fail("integrity", f"{label} references claims absent from its resource revision")
        events = record["events"]
        state = reduce_events(events, f"{label}.events", allow_preview_sentinel=allow_preview_sentinel)
        if record["current_state"] != state:
            _fail("integrity", f"{label}.current_state disagrees with event reducer", expected=state, actual=record["current_state"])
        for event in events:
            if event["event_id"] in event_ids:
                _fail("integrity", "registry contains a duplicate global event_id")
            event_ids.add(event["event_id"])
            expected_event = _stable_id(
                "evt",
                candidate_id,
                event["sequence"],
                event["from_state"],
                event["to_state"],
                event["at"],
                event["run_id"],
                event["operation_kind"],
                event["reason"],
            )
            if event["event_id"] != expected_event:
                _fail("integrity", f"{label} has a non-deterministic event_id", expected=expected_event)
        expected_candidate = _stable_id("cand", work_id, revision, record["module_id"], record["action"], record["target_slot"])
        expected_decision = _stable_id("du", work_id, revision, record["module_id"], record["action"], record["target_slot"])
        if candidate_id != expected_candidate or decision_id != expected_decision:
            _fail("integrity", f"{label} has non-deterministic IDs", expected_candidate=expected_candidate, expected_decision_unit=expected_decision)
        candidates.append({
            "candidate_id": candidate_id,
            "decision_unit_id": decision_id,
            "work_id": work_id,
            "revision_key": revision,
            "module_id": _identifier(record["module_id"], f"{label}.module_id"),
            "action": _enum(record["action"], f"{label}.action", ACTIONS),
            "target_slot": _identifier(record["target_slot"], f"{label}.target_slot"),
            "claim_ids": claim_ids,
            "preserve_learning_state": sorted(_string_list(record["preserve_learning_state"], f"{label}.preserve_learning_state")),
            "review_after": _iso_time(record["review_after"], f"{label}.review_after"),
            "run_ids": sorted(_string_list(record["run_ids"], f"{label}.run_ids", allow_empty=False)),
            "events": copy.deepcopy(events),
            "current_state": state,
        })

    coverage: list[dict[str, Any]] = []
    coverage_keys: set[tuple[str, str]] = set()
    for index, raw in enumerate(obj["coverage"]):
        label = f"registry.coverage[{index}]"
        record = _strict_object(raw, label, {"scope_kind", "scope_id", "cursor", "updated_at", "last_successful_run"}, {"scope_kind", "scope_id", "cursor", "updated_at", "last_successful_run"})
        scope_kind = _enum(record["scope_kind"], f"{label}.scope_kind", {"source", "query"})
        scope_id = _identifier(record["scope_id"], f"{label}.scope_id")
        key = (scope_kind, scope_id)
        if key in coverage_keys:
            _fail("integrity", "registry contains duplicate coverage cursor", scope_kind=scope_kind, scope_id=scope_id)
        coverage_keys.add(key)
        coverage.append({"scope_kind": scope_kind, "scope_id": scope_id, "cursor": _iso_time(record["cursor"], f"{label}.cursor"), "updated_at": _iso_time(record["updated_at"], f"{label}.updated_at"), "last_successful_run": _run_id(record["last_successful_run"], f"{label}.last_successful_run")})

    runs: list[dict[str, Any]] = []
    run_ids: set[str] = set()
    for index, raw in enumerate(obj["runs"]):
        label = f"registry.runs[{index}]"
        record = _strict_object(raw, label, {"run_id", "operation_kind", "prepared_at", "active_overlays", "coverage", "report", "decision_unit_ids"}, {"run_id", "operation_kind", "prepared_at", "active_overlays", "coverage", "report", "decision_unit_ids"})
        rid = _run_id(record["run_id"], f"{label}.run_id")
        if rid in run_ids:
            _fail("integrity", "registry contains duplicate run_id", run_id=rid)
        run_ids.add(rid)
        operation = _enum(record["operation_kind"], f"{label}.operation_kind", {"refresh", "review"})
        report = record["report"]
        if operation == "refresh":
            report_obj = _strict_object(report, f"{label}.report", {"path", "sha256"}, {"path", "sha256"})
            normalized_report: Any = {"path": _safe_relative(report_obj["path"], f"{label}.report.path"), "sha256": _digest(report_obj["sha256"], f"{label}.report.sha256")}
        else:
            if report is not None:
                _fail("integrity", "review run must not own a report")
            normalized_report = None
        if not isinstance(record["coverage"], list):
            _fail("malformed", f"{label}.coverage must be an array")
        normalized_run_coverage: list[dict[str, Any]] = []
        coverage_seen: set[tuple[str, str]] = set()
        for coverage_index, coverage_raw in enumerate(record["coverage"]):
            coverage_label = f"{label}.coverage[{coverage_index}]"
            coverage_record = _strict_object(coverage_raw, coverage_label, {"scope_kind", "scope_id", "status", "covered_from", "covered_to", "basis", "cursor_after", "detail"}, {"scope_kind", "scope_id", "status", "covered_from", "covered_to", "basis"})
            scope_kind = _enum(coverage_record["scope_kind"], f"{coverage_label}.scope_kind", {"source", "query"})
            scope_id = _identifier(coverage_record["scope_id"], f"{coverage_label}.scope_id")
            coverage_key = (scope_kind, scope_id)
            if coverage_key in coverage_seen:
                _fail("integrity", f"{label}.coverage contains duplicate scopes")
            coverage_seen.add(coverage_key)
            status = _enum(coverage_record["status"], f"{coverage_label}.status", COVERAGE_STATES)
            normalized_item: dict[str, Any] = {
                "scope_kind": scope_kind,
                "scope_id": scope_id,
                "status": status,
                "covered_from": _iso_time(coverage_record["covered_from"], f"{coverage_label}.covered_from"),
                "covered_to": _iso_time(coverage_record["covered_to"], f"{coverage_label}.covered_to"),
                "basis": _enum(coverage_record["basis"], f"{coverage_label}.basis", {"user", "cursor", "bootstrap"}),
            }
            if dt.datetime.fromisoformat(normalized_item["covered_to"].replace("Z", "+00:00")) < dt.datetime.fromisoformat(normalized_item["covered_from"].replace("Z", "+00:00")):
                _fail("integrity", f"{coverage_label} coverage range is reversed")
            if status in {"covered", "no-hit"}:
                if "cursor_after" not in coverage_record:
                    _fail("integrity", f"{coverage_label} successful status lacks cursor_after")
                normalized_item["cursor_after"] = _iso_time(coverage_record["cursor_after"], f"{coverage_label}.cursor_after")
                if normalized_item["cursor_after"] != normalized_item["covered_to"]:
                    _fail("integrity", f"{coverage_label}.cursor_after must equal covered_to")
            elif "cursor_after" in coverage_record:
                _fail("integrity", f"{coverage_label} blocked/skipped status advances cursor")
            if "detail" in coverage_record:
                normalized_item["detail"] = _string(coverage_record["detail"], f"{coverage_label}.detail")
            normalized_run_coverage.append(normalized_item)
        prepared_at = _iso_time(record["prepared_at"], f"{label}.prepared_at")
        if any(dt.datetime.fromisoformat(item["covered_to"].replace("Z", "+00:00")) > dt.datetime.fromisoformat(prepared_at.replace("Z", "+00:00")) for item in normalized_run_coverage):
            _fail("integrity", f"{label}.coverage extends beyond prepared_at")
        runs.append({
            "run_id": rid,
            "operation_kind": operation,
            "prepared_at": prepared_at,
            "active_overlays": sorted(_string_list(record["active_overlays"], f"{label}.active_overlays", identifiers=True)),
            "coverage": sorted(normalized_run_coverage, key=lambda item: (item["scope_kind"], item["scope_id"])),
            "report": normalized_report,
            "decision_unit_ids": sorted(_string_list(record["decision_unit_ids"], f"{label}.decision_unit_ids")),
        })
    all_run_ids = {item["run_id"] for item in runs}
    run_index = {item["run_id"]: item for item in runs}
    for resource in resources:
        referenced = {resource["first_seen_run"], *resource["last_seen_runs"]}
        if not referenced <= all_run_ids:
            _fail("integrity", "resource references a missing run", work_id=resource["work_id"], missing=sorted(referenced - all_run_ids))
        if any(run_index[run_id]["operation_kind"] != "refresh" for run_id in referenced):
            _fail("integrity", "resource first/last seen references must point to refresh runs", work_id=resource["work_id"])
    for candidate in candidates:
        referenced = set(candidate["run_ids"]) | {event["run_id"] for event in candidate["events"]}
        if not referenced <= all_run_ids:
            _fail("integrity", "candidate references a missing run", candidate_id=candidate["candidate_id"], missing=sorted(referenced - all_run_ids))
        for event in candidate["events"]:
            if run_index[event["run_id"]]["operation_kind"] != event["operation_kind"]:
                _fail("integrity", "candidate event operation disagrees with referenced run", event_id=event["event_id"])
    for cursor in coverage:
        if cursor["last_successful_run"] not in all_run_ids:
            _fail("integrity", "coverage cursor references a missing run", scope_id=cursor["scope_id"])
        matching = [
            item
            for item in run_index[cursor["last_successful_run"]]["coverage"]
            if item["scope_kind"] == cursor["scope_kind"]
            and item["scope_id"] == cursor["scope_id"]
            and item["status"] in {"covered", "no-hit"}
            and item.get("cursor_after") == cursor["cursor"]
        ]
        if len(matching) != 1:
            _fail("integrity", "coverage cursor is not derived from its successful run", scope_kind=cursor["scope_kind"], scope_id=cursor["scope_id"])
    return {
        "schema": REGISTRY_SCHEMA,
        "generation": generation,
        "resources": sorted(resources, key=lambda item: (item["work_id"], item["revision_key"])),
        "candidates": sorted(candidates, key=lambda item: item["candidate_id"]),
        "coverage": sorted(coverage, key=lambda item: (item["scope_kind"], item["scope_id"])),
        "runs": sorted(runs, key=lambda item: item["run_id"]),
    }


def _configuration_indexes(wrapper: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    configuration = wrapper["context"]["configuration"]
    return (
        {item["module_id"]: item for item in configuration["modules"]},
        {item["source_id"]: item for item in configuration["sources"]},
        {item["query_id"]: item for item in configuration["queries"]},
        {item["overlay_id"]: item for item in configuration["overlays"]},
    )


def _active_overlays(value: Any, wrapper: Mapping[str, Any], prepared_at: str) -> list[str]:
    selected = sorted(_string_list(value, "active_overlays", identifiers=True))
    overlays = _configuration_indexes(wrapper)[3]
    day = dt.datetime.fromisoformat(prepared_at.replace("Z", "+00:00")).date().isoformat()
    for overlay_id in selected:
        if overlay_id not in overlays:
            _fail("malformed", "proposal selects an unknown overlay", overlay_id=overlay_id)
        overlay = overlays[overlay_id]
        if not overlay["valid_from"] <= day <= overlay["valid_until"]:
            _fail("conflict", "proposal selects an inactive overlay", overlay_id=overlay_id, date=day)
    return selected


def _normalize_evidence_proposal(value: Any, label: str) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not value:
        _fail("malformed", f"{label} must be a non-empty array")
    result: list[dict[str, Any]] = []
    for index, raw in enumerate(value):
        item_label = f"{label}[{index}]"
        item = _strict_object(raw, item_label, {"locator", "role", "checked_at", "direction", "note"}, {"locator", "role", "checked_at", "direction"})
        normalized = {
            "locator": _string(item["locator"], f"{item_label}.locator"),
            "role": _enum(item["role"], f"{item_label}.role", SOURCE_ROLES),
            "checked_at": _iso_time(item["checked_at"], f"{item_label}.checked_at"),
            "direction": _enum(item["direction"], f"{item_label}.direction", {"supports", "refutes", "context"}),
        }
        if "note" in item:
            normalized["note"] = _string(item["note"], f"{item_label}.note")
        result.append(normalized)
    return result


def _normalize_resource_proposal(
    raw: Any,
    label: str,
    module_ids: set[str],
    run_id: str,
    prepared_at: str,
) -> dict[str, Any]:
    record = _strict_object(raw, label, {"identity", "revision_key", "title", "canonical_locator", "aliases", "modules", "relations", "claims"}, {"identity", "revision_key", "title", "canonical_locator", "aliases", "modules", "relations", "claims"})
    work_id, identity_locator = normalize_work_id(record["identity"])
    revision = _normalize_revision(record["revision_key"])
    modules = sorted(_string_list(record["modules"], f"{label}.modules", identifiers=True, allow_empty=False))
    if unknown := sorted(set(modules) - module_ids):
        _fail("malformed", f"{label} references unknown modules", modules=unknown)
    canonical = _string(record["canonical_locator"], f"{label}.canonical_locator")
    if canonical.startswith(("http://", "https://")):
        canonical = _canonical_url(canonical, f"{label}.canonical_locator")
    aliases: set[str] = {identity_locator}
    for index, alias in enumerate(_string_list(record["aliases"], f"{label}.aliases")):
        aliases.add(_canonical_url(alias, f"{label}.aliases[{index}]") if alias.startswith(("http://", "https://")) else alias)
    aliases.discard(canonical)

    relations: list[dict[str, Any]] = []
    if not isinstance(record["relations"], list):
        _fail("malformed", f"{label}.relations must be an array")
    for index, raw_relation in enumerate(record["relations"]):
        relation_label = f"{label}.relations[{index}]"
        relation = _strict_object(raw_relation, relation_label, {"kind", "target_identity", "target_revision_key"}, {"kind", "target_identity"})
        target_work_id, _locator = normalize_work_id(relation["target_identity"])
        normalized: dict[str, Any] = {"kind": _enum(relation["kind"], f"{relation_label}.kind", RELATIONS), "target_work_id": target_work_id}
        if "target_revision_key" in relation:
            normalized["target_revision_key"] = _normalize_revision(relation["target_revision_key"])
        relations.append(normalized)

    if not isinstance(record["claims"], list):
        _fail("malformed", f"{label}.claims must be an array")
    claims: list[dict[str, Any]] = []
    for index, raw_claim in enumerate(record["claims"]):
        claim_label = f"{label}.claims[{index}]"
        claim = _strict_object(raw_claim, claim_label, {"text", "status", "scope", "evidence"}, {"text", "status", "scope", "evidence"})
        text = _string(claim["text"], f"{claim_label}.text")
        scope = _string(claim["scope"], f"{claim_label}.scope")
        evidence = _normalize_evidence_proposal(
            claim["evidence"], f"{claim_label}.evidence"
        )
        prepared_value = dt.datetime.fromisoformat(prepared_at.replace("Z", "+00:00"))
        if any(
            dt.datetime.fromisoformat(item["checked_at"].replace("Z", "+00:00"))
            > prepared_value
            for item in evidence
        ):
            _fail(
                "malformed",
                f"{claim_label}.evidence cannot be checked after prepared_at",
            )
        claims.append({
            "claim_id": _stable_id("claim", text, scope),
            "text": text,
            "status": _enum(claim["status"], f"{claim_label}.status", CLAIM_STATES),
            "scope": scope,
            "evidence": evidence,
        })
    if len({item["claim_id"] for item in claims}) != len(claims):
        _fail("malformed", f"{label} contains duplicate claims")
    return {
        "work_id": work_id,
        "revision_key": revision,
        "title": _string(record["title"], f"{label}.title"),
        "canonical_locator": canonical,
        "aliases": sorted(aliases),
        "module_ids": modules,
        "relations": sorted(relations, key=lambda item: (item["kind"], item["target_work_id"], item.get("target_revision_key", ""))),
        "claims": sorted(claims, key=lambda item: item["claim_id"]),
        "first_seen_run": run_id,
        "last_seen_runs": [run_id],
    }


def _upsert_resource(registry: dict[str, Any], incoming: dict[str, Any], run_id: str) -> None:
    key = (incoming["work_id"], incoming["revision_key"])
    existing = next((item for item in registry["resources"] if (item["work_id"], item["revision_key"]) == key), None)
    if existing is None:
        registry["resources"].append(incoming)
        return
    if existing["title"] != incoming["title"]:
        _fail("conflict", "exact resource identity has a conflicting title", work_id=key[0], revision_key=key[1])
    if existing["canonical_locator"] != incoming["canonical_locator"]:
        locators = {existing["canonical_locator"], incoming["canonical_locator"], *existing["aliases"], *incoming["aliases"]}
        if existing["canonical_locator"] not in locators or incoming["canonical_locator"] not in locators:
            _fail("conflict", "exact resource identity has conflicting canonical locators", work_id=key[0])
        # Preserve the established canonical locator; record the new exact locator as an alias.
        incoming["aliases"].append(incoming["canonical_locator"])
    existing["aliases"] = sorted(set(existing["aliases"]) | set(incoming["aliases"]))
    existing["module_ids"] = sorted(set(existing["module_ids"]) | set(incoming["module_ids"]))
    existing_relations = {(item["kind"], item["target_work_id"], item.get("target_revision_key")): item for item in existing["relations"]}
    for relation in incoming["relations"]:
        existing_relations.setdefault((relation["kind"], relation["target_work_id"], relation.get("target_revision_key")), relation)
    existing["relations"] = sorted(existing_relations.values(), key=lambda item: (item["kind"], item["target_work_id"], item.get("target_revision_key", "")))
    existing_claims = {item["claim_id"]: item for item in existing["claims"]}
    for claim in incoming["claims"]:
        prior_claim = existing_claims.get(claim["claim_id"])
        if prior_claim is not None and prior_claim != claim:
            prior_evidence = {_canonical_json(item) for item in prior_claim["evidence"]}
            incoming_evidence = {_canonical_json(item) for item in claim["evidence"]}
            if not prior_evidence <= incoming_evidence:
                _fail("conflict", "claim refresh must preserve all previously registered evidence", claim_id=claim["claim_id"])
            existing_claims[claim["claim_id"]] = claim
        else:
            existing_claims.setdefault(claim["claim_id"], claim)
    existing["claims"] = sorted(existing_claims.values(), key=lambda item: item["claim_id"])
    existing["last_seen_runs"] = sorted(set(existing["last_seen_runs"]) | {run_id})


def _event(candidate_id: str, events: list[dict[str, Any]], to_state: str, *, at: str, run_id: str, operation_kind: str, reason: str, preview_digest: str | None = None) -> dict[str, Any]:
    from_state = events[-1]["to_state"] if events else None
    if to_state not in TRANSITIONS[from_state]:
        _fail("conflict", "proposal requests an illegal candidate transition", candidate_id=candidate_id, from_state=from_state, to_state=to_state)
    sequence = len(events) + 1
    result: dict[str, Any] = {
        "event_id": _stable_id("evt", candidate_id, sequence, from_state, to_state, at, run_id, operation_kind, reason),
        "sequence": sequence,
        "from_state": from_state,
        "to_state": to_state,
        "at": at,
        "run_id": run_id,
        "operation_kind": operation_kind,
        "reason": reason,
    }
    if to_state == "approved":
        if preview_digest is None:
            _fail("integrity", "approved transition lacks a preview binding")
        result["preview_digest"] = preview_digest
    events.append(result)
    return result


def _candidate_key(work_id: str, revision: str, module_id: str, action: str, target_slot: str) -> tuple[str, str]:
    return (
        _stable_id("cand", work_id, revision, module_id, action, target_slot),
        _stable_id("du", work_id, revision, module_id, action, target_slot),
    )


def _normalize_candidate_proposal(raw: Any, label: str, module_index: Mapping[str, Any], resources: Mapping[tuple[str, str], Any]) -> dict[str, Any]:
    record = _strict_object(raw, label, {"identity", "revision_key", "module_id", "action", "target_slot", "claim_refs", "preserve_learning_state", "review_after", "state", "reason"}, {"identity", "revision_key", "module_id", "action", "target_slot", "claim_refs", "preserve_learning_state", "review_after", "state", "reason"})
    work_id, _locator = normalize_work_id(record["identity"])
    revision = _normalize_revision(record["revision_key"])
    if (work_id, revision) not in resources:
        _fail("malformed", f"{label} references a resource revision not present in this refresh or registry")
    module_id = _identifier(record["module_id"], f"{label}.module_id")
    if module_id not in module_index:
        _fail("malformed", f"{label} references an unknown module", module_id=module_id)
    action = _enum(record["action"], f"{label}.action", ACTIONS)
    if action == "retire":
        _fail("malformed", f"{label} must express retirement as a review decision on the existing applied mapping")
    if action not in module_index[module_id]["adapter"]["allowed_actions"]:
        _fail("malformed", f"{label}.action is not allowed by the module adapter", action=action)
    state = _enum(record["state"], f"{label}.state", {"draft", "blocked", "qualified"})
    target_slot = _identifier(record["target_slot"], f"{label}.target_slot")
    if not isinstance(record["claim_refs"], list):
        _fail("malformed", f"{label}.claim_refs must be an array")
    claim_ids: list[str] = []
    for index, raw_ref in enumerate(record["claim_refs"]):
        ref_label = f"{label}.claim_refs[{index}]"
        ref = _strict_object(raw_ref, ref_label, {"text", "scope"}, {"text", "scope"})
        claim_ids.append(_stable_id("claim", _string(ref["text"], f"{ref_label}.text"), _string(ref["scope"], f"{ref_label}.scope")))
    if len(claim_ids) != len(set(claim_ids)):
        _fail("malformed", f"{label}.claim_refs contains duplicates")
    available_claims = {claim["claim_id"] for claim in resources[(work_id, revision)]["claims"]}
    if not set(claim_ids) <= available_claims:
        _fail("malformed", f"{label}.claim_refs references a claim absent from the resource revision")
    if state == "qualified" and not claim_ids:
        _fail("conflict", f"{label} qualified candidate must identify at least one key claim")
    candidate_id, decision_id = _candidate_key(work_id, revision, module_id, action, target_slot)
    return {
        "candidate_id": candidate_id,
        "decision_unit_id": decision_id,
        "work_id": work_id,
        "revision_key": revision,
        "module_id": module_id,
        "action": action,
        "target_slot": target_slot,
        "claim_ids": sorted(claim_ids),
        "preserve_learning_state": sorted(_string_list(record["preserve_learning_state"], f"{label}.preserve_learning_state")),
        "review_after": _iso_time(record["review_after"], f"{label}.review_after"),
        "desired_state": state,
        "reason": _string(record["reason"], f"{label}.reason"),
    }


def _apply_refresh_candidate(registry: dict[str, Any], proposal: dict[str, Any], *, at: str, run_id: str) -> dict[str, Any]:
    existing = next((item for item in registry["candidates"] if item["candidate_id"] == proposal["candidate_id"]), None)
    if existing is None:
        existing = {key: copy.deepcopy(proposal[key]) for key in ("candidate_id", "decision_unit_id", "work_id", "revision_key", "module_id", "action", "target_slot", "claim_ids", "preserve_learning_state", "review_after")}
        existing["run_ids"] = [run_id]
        existing["events"] = []
        _event(existing["candidate_id"], existing["events"], "draft", at=at, run_id=run_id, operation_kind="refresh", reason="registered by refresh")
        registry["candidates"].append(existing)
    else:
        stable_fields = ("decision_unit_id", "work_id", "revision_key", "module_id", "action", "target_slot", "claim_ids", "preserve_learning_state")
        for key in stable_fields:
            if existing[key] != proposal[key]:
                _fail("conflict", "candidate identity collides with different stable fields", candidate_id=existing["candidate_id"], field=key)
        existing["run_ids"] = sorted(set(existing["run_ids"]) | {run_id})
        if proposal["review_after"] < existing["review_after"]:
            existing["review_after"] = proposal["review_after"]
    current = existing["events"][-1]["to_state"]
    desired = proposal["desired_state"]
    if current != desired:
        _event(existing["candidate_id"], existing["events"], desired, at=at, run_id=run_id, operation_kind="refresh", reason=proposal["reason"])
    existing["current_state"] = reduce_events(existing["events"])
    if existing["current_state"] in {"approved", "applied"}:
        _fail("integrity", "refresh may not produce approved or applied")
    return existing


def _normalize_coverage(raw: Any, label: str, wrapper: Mapping[str, Any], current: Mapping[tuple[str, str], Any], prepared_at: str) -> dict[str, Any]:
    record = _strict_object(raw, label, {"scope_kind", "scope_id", "status", "covered_from", "covered_to", "basis", "cursor_after", "detail"}, {"scope_kind", "scope_id", "status", "covered_from", "covered_to", "basis"})
    scope_kind = _enum(record["scope_kind"], f"{label}.scope_kind", {"source", "query"})
    scope_id = _identifier(record["scope_id"], f"{label}.scope_id")
    source_index, query_index = _configuration_indexes(wrapper)[1:3]
    scope_index = source_index if scope_kind == "source" else query_index
    if scope_id not in scope_index:
        _fail("malformed", f"{label} references an unknown scope", scope_kind=scope_kind, scope_id=scope_id)
    status = _enum(record["status"], f"{label}.status", COVERAGE_STATES)
    if not scope_index[scope_id]["enabled"] and status != "skipped":
        _fail("conflict", f"{label} disabled scope must remain skipped")
    covered_from = _iso_time(record["covered_from"], f"{label}.covered_from")
    covered_to = _iso_time(record["covered_to"], f"{label}.covered_to")
    if dt.datetime.fromisoformat(covered_to.replace("Z", "+00:00")) > dt.datetime.fromisoformat(prepared_at.replace("Z", "+00:00")):
        _fail("malformed", f"{label}.covered_to cannot be after prepared_at")
    if dt.datetime.fromisoformat(covered_to.replace("Z", "+00:00")) < dt.datetime.fromisoformat(covered_from.replace("Z", "+00:00")):
        _fail("malformed", f"{label} coverage range is reversed")
    basis = _enum(record["basis"], f"{label}.basis", {"user", "cursor", "bootstrap"})
    prior = current.get((scope_kind, scope_id))
    if basis == "cursor":
        if prior is None or covered_from != prior["cursor"]:
            _fail("conflict", f"{label} cursor basis does not start at the current cursor")
    if basis == "bootstrap":
        if prior is not None:
            _fail("conflict", f"{label} cannot bootstrap a scope that already has a cursor")
        days = wrapper["context"]["configuration"]["preferences"].get("bootstrap_days")
        if days is None:
            _fail("malformed", f"{label} requests bootstrap without a configured bootstrap_days")
        actual = (dt.datetime.fromisoformat(covered_to.replace("Z", "+00:00")) - dt.datetime.fromisoformat(covered_from.replace("Z", "+00:00"))).total_seconds() / 86400
        if actual > days + 1e-9:
            _fail("malformed", f"{label} bootstrap exceeds the configured window", configured_days=days, actual_days=actual)
    if prior is None and basis == "cursor":
        _fail("conflict", f"{label} has no cursor")
    cursor_after = record.get("cursor_after")
    if status in {"covered", "no-hit"}:
        if cursor_after is None:
            _fail("malformed", f"{label} successful coverage requires cursor_after")
        cursor_after = _iso_time(cursor_after, f"{label}.cursor_after")
        if cursor_after != covered_to:
            _fail("malformed", f"{label}.cursor_after must equal covered_to")
        if prior and dt.datetime.fromisoformat(cursor_after.replace("Z", "+00:00")) < dt.datetime.fromisoformat(prior["cursor"].replace("Z", "+00:00")):
            _fail("conflict", f"{label} would move a cursor backwards")
    elif cursor_after is not None:
        _fail("integrity", f"{label} blocked/skipped coverage must not advance cursor")
    result: dict[str, Any] = {"scope_kind": scope_kind, "scope_id": scope_id, "status": status, "covered_from": covered_from, "covered_to": covered_to, "basis": basis}
    if cursor_after is not None:
        result["cursor_after"] = cursor_after
    if "detail" in record:
        result["detail"] = _string(record["detail"], f"{label}.detail")
    return result


def _append_review_transition(candidate: dict[str, Any], to_state: str, *, at: str, run_id: str, reason: str, preview: str | None = None) -> None:
    _event(candidate["candidate_id"], candidate["events"], to_state, at=at, run_id=run_id, operation_kind="review", reason=reason, preview_digest=preview)
    candidate["current_state"] = reduce_events(candidate["events"], allow_preview_sentinel=True)


def _normalize_review_decision(raw: Any, label: str, candidate_index: Mapping[str, Any]) -> dict[str, Any]:
    record = _strict_object(raw, label, {"candidate_id", "outcome", "reason", "count_change", "budget_change", "preserve_learning_state", "replaces_candidate_id"}, {"candidate_id", "outcome", "reason", "count_change", "budget_change", "preserve_learning_state"})
    candidate_id = _string(record["candidate_id"], f"{label}.candidate_id")
    if candidate_id not in candidate_index:
        _fail("malformed", f"{label} references an unknown candidate", candidate_id=candidate_id)
    outcome = _enum(record["outcome"], f"{label}.outcome", {"apply", "defer", "reject", "supersede", "block", "retire"})
    for key in ("count_change", "budget_change"):
        if isinstance(record[key], bool) or not isinstance(record[key], int):
            _fail("malformed", f"{label}.{key} must be an integer")
    normalized: dict[str, Any] = {
        "candidate_id": candidate_id,
        "decision_unit_id": candidate_index[candidate_id]["decision_unit_id"],
        "outcome": outcome,
        "reason": _string(record["reason"], f"{label}.reason"),
        "count_change": record["count_change"],
        "budget_change": record["budget_change"],
        "preserve_learning_state": sorted(_string_list(record["preserve_learning_state"], f"{label}.preserve_learning_state")),
    }
    if normalized["preserve_learning_state"] != candidate_index[candidate_id]["preserve_learning_state"]:
        _fail("conflict", f"{label} preserve list differs from the candidate contract")
    if "replaces_candidate_id" in record:
        replacement = _string(record["replaces_candidate_id"], f"{label}.replaces_candidate_id")
        if replacement not in candidate_index:
            _fail("malformed", f"{label} references an unknown replacement candidate")
        if replacement == candidate_id:
            _fail("malformed", f"{label} cannot replace itself")
        normalized["replaces_candidate_id"] = replacement
    if outcome == "apply" and candidate_index[candidate_id]["action"] == "replace":
        if "replaces_candidate_id" not in normalized:
            _fail("malformed", f"{label} replace action requires replaces_candidate_id")
        old = candidate_index[normalized["replaces_candidate_id"]]
        new = candidate_index[candidate_id]
        if old["current_state"] != "applied":
            _fail(
                "conflict",
                f"{label} replace old side must currently be applied",
                candidate_id=old["candidate_id"],
                state=old["current_state"],
            )
        if (old["module_id"], old["target_slot"]) != (
            new["module_id"],
            new["target_slot"],
        ):
            _fail(
                "conflict",
                f"{label} replace sides must use the same module and target slot",
                new_module=new["module_id"],
                new_slot=new["target_slot"],
                old_module=old["module_id"],
                old_slot=old["target_slot"],
            )
        if not set(old["preserve_learning_state"]) <= set(
            new["preserve_learning_state"]
        ):
            _fail(
                "conflict",
                f"{label} replace must preserve every learning-state field protected by the old side",
            )
        normalized["replaces_decision_unit_id"] = old["decision_unit_id"]
    elif "replaces_candidate_id" in normalized:
        _fail("malformed", f"{label} may only set replaces_candidate_id for a replace apply")
    if outcome == "apply" and candidate_index[candidate_id]["action"] == "retire":
        _fail("malformed", f"{label} retire candidate must use retire outcome")
    if outcome == "supersede" and candidate_index[candidate_id]["current_state"] == "applied":
        _fail(
            "conflict",
            f"{label} cannot supersede an applied mapping without an exact replace decision",
        )
    return normalized


def _apply_review_decision(registry: dict[str, Any], decision: dict[str, Any], *, at: str, run_id: str) -> None:
    index = {item["candidate_id"]: item for item in registry["candidates"]}
    candidate = index[decision["candidate_id"]]
    outcome = decision["outcome"]
    reason = decision["reason"]
    if outcome == "apply":
        if candidate["current_state"] != "qualified":
            _fail("conflict", "only qualified candidates can be approved", candidate_id=candidate["candidate_id"], state=candidate["current_state"])
        _append_review_transition(candidate, "approved", at=at, run_id=run_id, reason=reason, preview=PREVIEW_SENTINEL)
        _append_review_transition(candidate, "applied", at=at, run_id=run_id, reason="all approved portfolio edits passed postconditions")
        if candidate["action"] == "replace":
            old = index[decision["replaces_candidate_id"]]
            if old["current_state"] != "applied":
                _fail("conflict", "replace old side must currently be applied", candidate_id=old["candidate_id"], state=old["current_state"])
            _append_review_transition(old, "superseded", at=at, run_id=run_id, reason=f"replaced by {candidate['candidate_id']}")
    elif outcome == "retire":
        if candidate["current_state"] != "applied":
            _fail("conflict", "retire requires an applied candidate", candidate_id=candidate["candidate_id"], state=candidate["current_state"])
        _append_review_transition(candidate, "stale", at=at, run_id=run_id, reason=reason)
    else:
        target = {"defer": "deferred", "reject": "rejected", "supersede": "superseded", "block": "blocked"}[outcome]
        _append_review_transition(candidate, target, at=at, run_id=run_id, reason=reason)


def _normalize_write(raw: Any, label: str, operation: str, wrapper: Mapping[str, Any], allowed_decisions: set[str]) -> dict[str, Any]:
    record = _strict_object(raw, label, {"path", "role", "after_text", "module_id", "action", "decision_unit_ids"}, {"path", "role", "after_text", "decision_unit_ids"})
    path = _safe_relative(record["path"], f"{label}.path")
    role = _enum(record["role"], f"{label}.role", {"research-brief", "report", "portfolio", "progress-projection"})
    after_text = _string(record["after_text"], f"{label}.after_text", allow_empty=True)
    decision_ids = sorted(_string_list(record["decision_unit_ids"], f"{label}.decision_unit_ids"))
    if not set(decision_ids) <= allowed_decisions:
        _fail("malformed", f"{label} references decision units outside this proposal")
    modules = _configuration_indexes(wrapper)[0]
    storage = wrapper["context"]["configuration"]["storage"]
    normalized: dict[str, Any] = {"path": path, "role": role, "after_text": after_text, "decision_unit_ids": decision_ids}
    if operation == "research-brief":
        if role != "research-brief" or PurePosixPath(path).parent != PurePosixPath(storage["research_brief_directory"]):
            _fail("safety", "research-brief may only create a file under research_brief_directory", path=path)
        if decision_ids or "module_id" in record or "action" in record:
            _fail("malformed", f"{label} has fields not applicable to research-brief")
    elif operation == "refresh":
        if role != "report" or PurePosixPath(path).parent != PurePosixPath(storage["report_directory"]):
            _fail("safety", "refresh may only provide a report target", path=path)
        if "module_id" in record or "action" in record:
            _fail("malformed", f"{label} report cannot declare a portfolio action")
    else:
        if role not in {"portfolio", "progress-projection"}:
            _fail("integrity", "review cannot write reports or research briefs")
        if "module_id" not in record or "action" not in record:
            _fail("malformed", f"{label} review target requires module_id and action")
        module_id = _identifier(record["module_id"], f"{label}.module_id")
        if module_id not in modules:
            _fail("malformed", f"{label} references an unknown module")
        action = _enum(record["action"], f"{label}.action", ACTIONS)
        if action not in modules[module_id]["adapter"]["allowed_actions"]:
            _fail("malformed", f"{label}.action is not allowed by its adapter")
        expected_path = modules[module_id]["portfolio_path"] if role == "portfolio" else modules[module_id].get("progress_projection")
        if expected_path is None or path != expected_path:
            _fail("safety", f"{label} path is not the configured {role} target", path=path)
        if not decision_ids:
            _fail("malformed", f"{label} review target must bind decision units")
        anchor = modules[module_id]["adapter"].get("anchor")
        if role == "portfolio" and anchor and anchor not in after_text:
            _fail("integrity", f"{label} after_text is missing the configured adapter anchor", anchor=anchor)
        normalized.update({"module_id": module_id, "action": action, "adapter_id": modules[module_id]["adapter"]["adapter_id"], "adapter_version": modules[module_id]["adapter"]["version"]})
    return normalized


def _load_registry(repo: Path, wrapper: Mapping[str, Any]) -> tuple[dict[str, Any], str]:
    relative = wrapper["context"]["configuration"]["storage"]["registry_path"]
    path = _repo_path(repo, relative, label="registry", leaf_kind="file", allow_missing_leaf=True)
    if not _path_present(path):
        return _empty_registry(), ABSENT
    data = _read_bytes(path, "registry")
    try:
        parsed = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        _fail("malformed", "registry is not valid UTF-8 JSON", reason=str(exc))
    return validate_registry(parsed), _sha256(data)


def _validate_registered_reports(
    repo: Path, wrapper: Mapping[str, Any], registry: Mapping[str, Any]
) -> list[str]:
    report_directory = wrapper["context"]["configuration"]["storage"][
        "report_directory"
    ]
    paths: list[str] = []
    seen: set[str] = set()
    for run in registry["runs"]:
        if run["operation_kind"] != "refresh":
            continue
        report = run["report"]
        path = report["path"]
        if PurePosixPath(path).parent != PurePosixPath(report_directory):
            _fail(
                "integrity",
                "registry run references a report outside report_directory",
                run_id=run["run_id"],
                path=path,
            )
        if path in seen:
            _fail(
                "integrity",
                "multiple refresh runs reference the same immutable report",
                path=path,
            )
        seen.add(path)
        report_path = _repo_path(
            repo,
            path,
            label="immutable report",
            leaf_kind="file",
            allow_missing_leaf=False,
        )
        actual = _sha256(_read_bytes(report_path, "immutable report"))
        if actual != report["sha256"]:
            _fail(
                "integrity",
                "immutable report bytes no longer match registry",
                run_id=run["run_id"],
                path=path,
                expected=report["sha256"],
                actual=actual,
            )
        paths.append(path)
    return sorted(paths)


def _dependency_snapshots(
    repo: Path,
    wrapper: Mapping[str, Any],
    context_path: str,
    extra: Sequence[str],
    registered_reports: Sequence[str] = (),
) -> list[dict[str, str]]:
    allowlist = wrapper["allowlist"]
    tracked_files = set(allowlist["tracked_files"])
    allowed_extra = tracked_files
    snapshots: dict[tuple[str, str], dict[str, str]] = {}
    paths: list[tuple[str, str, str]] = [(context_path, "file", "managed context")]
    for source in wrapper["sources"].values():
        paths.append((source["path"], "file", "managed config source"))
    paths.extend((path, "file", "tracked fact") for path in tracked_files)
    paths.extend(
        (path, "file", "immutable historical report")
        for path in registered_reports
    )
    # Collection members have already been expanded and Git-validated by the
    # materializer.  Never walk a collection root at runtime: an untracked file
    # matching the same directory must remain invisible.
    for path in extra:
        safe = _safe_relative(path, "proposal dependency")
        if safe not in allowed_extra:
            _fail("safety", "proposal dependency is not in the materialized allowlist", path=safe)
        paths.append((safe, "file", "proposal dependency"))
    for module in wrapper["context"]["configuration"]["modules"]:
        paths.append((module["portfolio_path"], "file", "module portfolio"))
        if "progress_projection" in module:
            paths.append((module["progress_projection"], "file", "module progress projection"))
    for path, kind, label in paths:
        snapshots[(kind, path)] = _snapshot_path(repo, path, kind, label)
    result = sorted(snapshots.values(), key=lambda item: (item["path"], item["kind"]))
    for source_name, source in wrapper["sources"].items():
        snapshot = next(item for item in result if item["path"] == source["path"] and item["kind"] == "file")
        if snapshot["sha256"] != source["digest"]:
            _fail("conflict", "materialized config source changed; re-materialize before continuing", source=source_name)
    return result


def _unified_diff(path: str, before: bytes | None, after: bytes) -> str:
    try:
        before_text = "" if before is None else before.decode("utf-8")
        after_text = after.decode("utf-8")
    except UnicodeDecodeError:
        _fail("malformed", "managed text targets must be UTF-8", path=path)
    return "".join(difflib.unified_diff(before_text.splitlines(keepends=True), after_text.splitlines(keepends=True), fromfile=f"a/{path}", tofile=f"b/{path}"))


def _target_record(repo: Path, write: Mapping[str, Any]) -> dict[str, Any]:
    path = _repo_path(repo, write["path"], label="write target", leaf_kind="file", allow_missing_leaf=True)
    parent_relative = PurePosixPath(write["path"]).parent.as_posix()
    if parent_relative != ".":
        _repo_path(repo, parent_relative, label="write target parent", leaf_kind="directory", allow_missing_leaf=False)
    before = _read_bytes(path, "write target") if _path_present(path) else None
    after = write["after_text"].encode("utf-8")
    result = {key: copy.deepcopy(value) for key, value in write.items() if key != "after_text"}
    result.update({
        "before_sha256": ABSENT if before is None else _sha256(before),
        "before_base64": None if before is None else base64.b64encode(before).decode("ascii"),
        "after_sha256": _sha256(after),
        "after_base64": base64.b64encode(after).decode("ascii"),
        "diff": _unified_diff(write["path"], before, after),
    })
    return result


def _validate_proposal_top(data: Any) -> tuple[dict[str, Any], str, str, list[str]]:
    obj = _strict_object(data, "proposal", {"schema", "operation_kind", "prepared_at", "dependencies", "writes", "research", "refresh", "review"}, {"schema", "operation_kind", "prepared_at", "writes"})
    if obj["schema"] != PROPOSAL_SCHEMA:
        _fail("malformed", "unsupported proposal schema")
    operation = _enum(obj["operation_kind"], "proposal.operation_kind", {"research-brief", "refresh", "review"})
    prepared_at = _iso_time(obj["prepared_at"], "proposal.prepared_at")
    expected_payload = {"research-brief": "research", "refresh": "refresh", "review": "review"}[operation]
    for key in ("research", "refresh", "review"):
        if (key in obj) != (key == expected_payload):
            _fail("malformed", "proposal payload does not match operation_kind", operation_kind=operation)
    dependencies = _string_list(obj.get("dependencies", []), "proposal.dependencies")
    if not isinstance(obj["writes"], list):
        _fail("malformed", "proposal.writes must be an array")
    return obj, operation, prepared_at, dependencies


def _replace_preview_binding(value: Any, old: str, new: str) -> Any:
    cloned = copy.deepcopy(value)
    if isinstance(cloned, dict):
        if cloned.get("to_state") == "approved" and cloned.get("preview_digest") == old:
            cloned["preview_digest"] = new
        for key in list(cloned):
            cloned[key] = _replace_preview_binding(cloned[key], old, new)
    elif isinstance(cloned, list):
        cloned = [_replace_preview_binding(item, old, new) for item in cloned]
    return cloned


def _preview_basis(plan: Mapping[str, Any], *, current_digest: str | None = None) -> dict[str, Any]:
    targets: list[dict[str, Any]] = []
    for target in plan["targets"]:
        normalized = {key: copy.deepcopy(value) for key, value in target.items() if key not in {"after_sha256", "diff"}}
        if target["role"] == "registry":
            try:
                registry = json.loads(base64.b64decode(target["after_base64"], validate=True).decode("utf-8"))
            except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                _fail("integrity", "plan registry after bytes are invalid", reason=str(exc))
            if current_digest is not None:
                registry = _replace_preview_binding(registry, current_digest, PREVIEW_SENTINEL)
            normalized["after_base64"] = base64.b64encode(_render_json(registry)).decode("ascii")
        targets.append(normalized)
    return {
        "schema": plan["schema"],
        "operation_kind": plan["operation_kind"],
        "prepared_at": plan["prepared_at"],
        "context_path": plan["context_path"],
        "context_sha256": plan["context_sha256"],
        "proposal_sha256": plan["proposal_sha256"],
        "adapter_catalog_sha256": plan["adapter_catalog_sha256"],
        "active_overlays": plan["active_overlays"],
        "dependencies": plan["dependencies"],
        "decision_units": plan["decision_units"],
        "targets": targets,
    }


def _plan_preview_digest(plan: Mapping[str, Any], current_digest: str | None = None) -> str:
    return _sha256(_canonical_json(_preview_basis(plan, current_digest=current_digest)))


def _fill_registry_preview(target: dict[str, Any], preview_digest: str) -> None:
    registry = json.loads(base64.b64decode(target["after_base64"], validate=True).decode("utf-8"))
    registry = _replace_preview_binding(registry, PREVIEW_SENTINEL, preview_digest)
    after = _render_json(registry)
    before = None if target["before_base64"] is None else base64.b64decode(target["before_base64"], validate=True)
    target["after_base64"] = base64.b64encode(after).decode("ascii")
    target["after_sha256"] = _sha256(after)
    target["diff"] = _unified_diff(target["path"], before, after)


def _review_write_contract(
    decision_units: Sequence[Mapping[str, Any]],
    writes: Sequence[dict[str, Any]],
) -> None:
    decision_index = {unit["decision_unit_id"]: unit for unit in decision_units}
    primary_candidates = {unit["candidate_id"] for unit in decision_units}
    portfolio_counts = {decision_id: 0 for decision_id in decision_index}
    progress_counts = {decision_id: 0 for decision_id in decision_index}
    for unit in decision_units:
        replaced = unit.get("replaces_candidate_id")
        if replaced is not None and replaced in primary_candidates:
            _fail(
                "conflict",
                "a replace old side cannot also be a separate decision in the same review batch",
                candidate_id=replaced,
            )
    for write in writes:
        related: set[str] = set()
        for decision_id in write["decision_unit_ids"]:
            unit = decision_index[decision_id]
            if unit["outcome"] not in {"apply", "retire"}:
                _fail(
                    "conflict",
                    "registry-only review outcomes must not bind module writes",
                    decision_unit_id=decision_id,
                    outcome=unit["outcome"],
                )
            if write["module_id"] != unit["module_id"]:
                _fail(
                    "conflict",
                    "review target module disagrees with its decision unit",
                    decision_unit_id=decision_id,
                    expected=unit["module_id"],
                    actual=write["module_id"],
                )
            if write["action"] != unit["action"]:
                _fail(
                    "conflict",
                    "review target action disagrees with its decision unit",
                    decision_unit_id=decision_id,
                    expected=unit["action"],
                    actual=write["action"],
                )
            if "replaces_decision_unit_id" in unit:
                related.add(unit["replaces_decision_unit_id"])
            counts = (
                portfolio_counts
                if write["role"] == "portfolio"
                else progress_counts
            )
            counts[decision_id] += 1
        write["replaces_decision_unit_ids"] = sorted(related)
    for decision_id, unit in decision_index.items():
        changing = unit["outcome"] in {"apply", "retire"}
        if changing and portfolio_counts[decision_id] != 1:
            _fail(
                "malformed",
                "each portfolio-changing decision must bind exactly one portfolio target",
                decision_unit_id=decision_id,
                count=portfolio_counts[decision_id],
            )
        if not changing and (
            portfolio_counts[decision_id] or progress_counts[decision_id]
        ):
            _fail(
                "integrity",
                "registry-only decision unexpectedly binds a module target",
                decision_unit_id=decision_id,
            )
        if progress_counts[decision_id] > 1:
            _fail(
                "malformed",
                "a decision may bind at most one progress projection",
                decision_unit_id=decision_id,
            )


def _parse_resource_slots(text: str, label: str) -> tuple[str, dict[str, str]]:
    skeleton: list[str] = []
    slots: dict[str, str] = {}
    active: str | None = None
    content: list[str] = []
    for line_number, line in enumerate(text.splitlines(keepends=True), start=1):
        marker = SLOT_MARKER_RE.fullmatch(line.rstrip("\r\n"))
        if marker is None:
            if active is None:
                skeleton.append(line)
            else:
                content.append(line)
            continue
        slot, kind = marker.groups()
        if kind == "start":
            if active is not None:
                _fail(
                    "integrity",
                    f"{label} contains nested resource slots",
                    line=line_number,
                    slot=slot,
                )
            if slot in slots:
                _fail(
                    "integrity",
                    f"{label} contains a duplicate resource slot",
                    line=line_number,
                    slot=slot,
                )
            active = slot
            content = []
            skeleton.append(line)
        else:
            if active != slot:
                _fail(
                    "integrity",
                    f"{label} contains an unmatched resource slot end marker",
                    line=line_number,
                    slot=slot,
                    active=active,
                )
            slots[slot] = "".join(content)
            active = None
            content = []
            skeleton.append(line)
    if active is not None:
        _fail(
            "integrity",
            f"{label} contains an unterminated resource slot",
            slot=active,
        )
    return "".join(skeleton), slots


def _resource_state(content: str, label: str) -> dict[str, Any] | None:
    matches: list[str] = []
    for line in content.splitlines():
        marker = STATE_MARKER_RE.fullmatch(line)
        if marker is not None:
            matches.append(marker.group(1))
    if len(matches) > 1:
        _fail("integrity", f"{label} contains multiple resource-state markers")
    if not matches:
        return None

    def object_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                _fail(
                    "integrity",
                    f"{label} resource-state contains a duplicate key",
                    key=key,
                )
            result[key] = value
        return result

    try:
        state = json.loads(
            matches[0],
            object_pairs_hook=object_pairs,
            parse_constant=lambda value: _fail(
                "integrity",
                f"{label} resource-state contains a non-JSON constant",
                value=value,
            ),
        )
    except json.JSONDecodeError as exc:
        _fail(
            "integrity",
            f"{label} resource-state is invalid JSON",
            reason=str(exc),
        )
    if not isinstance(state, dict):
        _fail("integrity", f"{label} resource-state must be a JSON object")
    for key in state:
        _identifier(key, f"{label} resource-state key")
    if matches[0] != _canonical_json(state).decode("utf-8"):
        _fail(
            "integrity",
            f"{label} resource-state must use canonical compact JSON",
        )
    return state


def _validate_adapter_scoped_change(
    target: Mapping[str, Any],
    decision_index: Mapping[str, Mapping[str, Any]],
    module: Mapping[str, Any],
    label: str,
) -> None:
    if target["before_base64"] is None:
        _fail(
            "conflict",
            f"{label} requires a pre-existing adapter document with stable slots",
            path=target["path"],
        )
    before = base64.b64decode(target["before_base64"], validate=True).decode("utf-8")
    after = base64.b64decode(target["after_base64"], validate=True).decode("utf-8")
    adapter = module["adapter"]
    if adapter["adapter_id"] not in {
        "markdown-curriculum",
        "problem-curriculum",
    }:
        _fail(
            "integrity",
            f"{label} has no central scoped-diff implementation",
            adapter_id=adapter["adapter_id"],
        )
    for field in ("heading", "anchor"):
        required_text = adapter.get(field)
        if required_text and (
            required_text not in before or required_text not in after
        ):
            _fail(
                "integrity",
                f"{label} does not preserve its configured adapter {field}",
                value=required_text,
            )
    before_skeleton, before_slots = _parse_resource_slots(before, f"{label} before")
    after_skeleton, after_slots = _parse_resource_slots(after, f"{label} after")
    if before_skeleton != after_skeleton or set(before_slots) != set(after_slots):
        _fail(
            "integrity",
            f"{label} changes content or slot markers outside authorized resource slots",
            path=target["path"],
        )
    authorized_slots = {
        decision_index[decision_id]["target_slot"]
        for decision_id in target["decision_unit_ids"]
    }
    missing = sorted(authorized_slots - set(before_slots))
    if missing:
        _fail(
            "conflict",
            f"{label} references resource slots absent from the adapter document",
            slots=missing,
        )
    changed = {
        slot
        for slot in before_slots
        if before_slots[slot] != after_slots[slot]
    }
    if changed != authorized_slots:
        _fail(
            "integrity",
            f"{label} changed a different set of resource slots than its decision units",
            expected=sorted(authorized_slots),
            actual=sorted(changed),
        )
    preserve_by_slot: dict[str, set[str]] = {}
    for decision_id in target["decision_unit_ids"]:
        unit = decision_index[decision_id]
        preserve_by_slot.setdefault(unit["target_slot"], set()).update(
            unit["preserve_learning_state"]
        )
    for slot, fields in preserve_by_slot.items():
        before_state = _resource_state(
            before_slots[slot], f"{label} slot {slot} before"
        )
        after_state = _resource_state(
            after_slots[slot], f"{label} slot {slot} after"
        )
        if not fields:
            continue
        if before_state is None or after_state is None:
            _fail(
                "integrity",
                f"{label} cannot prove required learning-state preservation",
                slot=slot,
                fields=sorted(fields),
            )
        for field in sorted(fields):
            if field not in before_state or field not in after_state:
                _fail(
                    "integrity",
                    f"{label} resource-state omits a protected field",
                    slot=slot,
                    field=field,
                )
            if before_state[field] != after_state[field]:
                _fail(
                    "integrity",
                    f"{label} changes a protected learning-state field",
                    slot=slot,
                    field=field,
                )


def _validate_registry_evolution(
    before: bytes | None,
    after_registry: Mapping[str, Any],
    preview_digest: str,
    operation_kind: str,
    prepared_at: str,
    active_overlays: Sequence[str],
    decision_unit_ids: Sequence[str],
) -> Mapping[str, Any]:
    before_registry = (
        _empty_registry()
        if before is None
        else validate_registry(json.loads(before.decode("utf-8")))
    )
    if after_registry["generation"] != before_registry["generation"] + 1:
        _fail(
            "integrity",
            "registry generation must advance exactly once per managed operation",
            before=before_registry["generation"],
            after=after_registry["generation"],
        )

    before_resources = {
        (item["work_id"], item["revision_key"]): item
        for item in before_registry["resources"]
    }
    after_resources = {
        (item["work_id"], item["revision_key"]): item
        for item in after_registry["resources"]
    }
    if not set(before_resources) <= set(after_resources):
        _fail("integrity", "registry operation removes historical resource revisions")

    before_runs = {item["run_id"]: item for item in before_registry["runs"]}
    after_runs = {item["run_id"]: item for item in after_registry["runs"]}
    for run_id, old_run in before_runs.items():
        if after_runs.get(run_id) != old_run:
            _fail(
                "integrity",
                "registry operation rewrites or removes an immutable historical run",
                run_id=run_id,
            )
    new_run_ids = sorted(set(after_runs) - set(before_runs))
    if len(new_run_ids) != 1:
        _fail(
            "integrity",
            "registry operation must append exactly one run",
            run_ids=new_run_ids,
        )
    new_run = after_runs[new_run_ids[0]]
    if (
        new_run["operation_kind"] != operation_kind
        or new_run["prepared_at"] != prepared_at
        or new_run["active_overlays"] != list(active_overlays)
        or new_run["decision_unit_ids"] != list(decision_unit_ids)
    ):
        _fail(
            "integrity",
            "new registry run does not match the exact prepared operation",
            run_id=new_run["run_id"],
        )

    if operation_kind == "review":
        if after_resources != before_resources:
            _fail(
                "integrity",
                "review must not discover or rewrite resource revisions",
            )
        if after_registry["coverage"] != before_registry["coverage"]:
            _fail("integrity", "review must not change coverage or cursors")

    before_candidates = {
        item["candidate_id"]: item for item in before_registry["candidates"]
    }
    after_candidates = {
        item["candidate_id"]: item for item in after_registry["candidates"]
    }
    stable_fields = {
        "candidate_id",
        "decision_unit_id",
        "work_id",
        "revision_key",
        "module_id",
        "action",
        "target_slot",
        "claim_ids",
        "preserve_learning_state",
    }
    for candidate_id, old_candidate in before_candidates.items():
        candidate = after_candidates.get(candidate_id)
        if candidate is None:
            _fail(
                "integrity",
                "registry operation removes a historical candidate",
                candidate_id=candidate_id,
            )
        for field in stable_fields:
            if candidate[field] != old_candidate[field]:
                _fail(
                    "integrity",
                    "registry operation rewrites a candidate stable field",
                    candidate_id=candidate_id,
                    field=field,
                )
        old_events = old_candidate["events"]
        if candidate["events"][: len(old_events)] != old_events:
            _fail(
                "integrity",
                "registry operation rewrites historical candidate events",
                candidate_id=candidate_id,
            )
        if not set(old_candidate["run_ids"]) <= set(candidate["run_ids"]):
            _fail(
                "integrity",
                "registry operation removes historical candidate run references",
                candidate_id=candidate_id,
            )
        if operation_kind == "review" and (
            candidate["review_after"] != old_candidate["review_after"]
            or candidate["run_ids"] != old_candidate["run_ids"]
        ):
            _fail(
                "integrity",
                "review must not rewrite candidate discovery metadata",
                candidate_id=candidate_id,
            )
    if operation_kind == "review" and set(after_candidates) != set(before_candidates):
        _fail("integrity", "review must not discover new candidates")
    for candidate in after_registry["candidates"]:
        historical_count = len(
            before_candidates.get(candidate["candidate_id"], {}).get("events", [])
        )
        for event in candidate["events"][historical_count:]:
            if (
                event["to_state"] == "approved"
                and event["preview_digest"] != preview_digest
            ):
                _fail(
                    "integrity",
                    "new approved event is not bound to this preview",
                    event_id=event["event_id"],
                )
    return new_run


def prepare_plan(repo: Path | str, wrapper: Any, context_path: str, proposal: Any) -> dict[str, Any]:
    """Create a complete deterministic plan without writing inside *repo*."""

    root = _absolute(Path(repo))
    managed = validate_runtime_wrapper(wrapper)
    _validate_source_binding(root, managed)
    context_relative = _safe_relative(context_path, "context_path")
    context_file = _repo_path(root, context_relative, label="managed context", leaf_kind="file", allow_missing_leaf=False)
    context_bytes = _read_bytes(context_file, "managed context")
    if json.loads(context_bytes.decode("utf-8")) != wrapper:
        _fail("conflict", "provided managed context does not match context_path bytes")
    obj, operation, prepared_at, extra_dependencies = _validate_proposal_top(proposal)
    configuration = managed["context"]["configuration"]
    module_index, source_index, query_index, _overlay_index = _configuration_indexes(
        managed
    )
    registry = _empty_registry()
    registry_before_sha = ABSENT
    registered_reports: list[str] = []
    if operation in {"refresh", "review"}:
        registry, registry_before_sha = _load_registry(root, managed)
        registered_reports = _validate_registered_reports(root, managed, registry)
    journal_relative = configuration["storage"]["journal_path"]
    journal_path = _repo_path(root, journal_relative, label="transaction journal", leaf_kind="file", allow_missing_leaf=True)
    if _path_present(journal_path):
        _fail("conflict", "an unfinished transaction journal exists; recover it first", path=journal_relative)

    writes: list[dict[str, Any]] = []
    decision_units: list[dict[str, Any]] = []
    active_overlays: list[str] = []
    registry_changed = False

    if operation == "research-brief":
        research = _strict_object(obj["research"], "proposal.research", {"brief_id", "active_overlays"}, {"brief_id", "active_overlays"})
        brief_id = _run_id(research["brief_id"], "proposal.research.brief_id")
        active_overlays = _active_overlays(research["active_overlays"], managed, prepared_at)
        writes = [_normalize_write(item, f"proposal.writes[{index}]", operation, managed, set()) for index, item in enumerate(obj["writes"])]
        if len(writes) != 1:
            _fail("malformed", "research-brief must create exactly one independently authorized brief")
        decision_units = []
        del brief_id  # Identity remains in the exact brief content and proposal digest.

    elif operation == "refresh":
        refresh = _strict_object(obj["refresh"], "proposal.refresh", {"run_id", "active_overlays", "coverage", "resources", "candidates"}, {"run_id", "active_overlays", "coverage", "resources", "candidates"})
        run_id = _run_id(refresh["run_id"], "proposal.refresh.run_id")
        if any(item["run_id"] == run_id for item in registry["runs"]):
            _fail("conflict", "refresh run_id already exists", run_id=run_id)
        active_overlays = _active_overlays(refresh["active_overlays"], managed, prepared_at)
        if not isinstance(refresh["resources"], list) or not isinstance(refresh["candidates"], list) or not isinstance(refresh["coverage"], list):
            _fail("malformed", "refresh resources, candidates, and coverage must be arrays")
        module_ids = set(module_index)
        for index, raw_resource in enumerate(refresh["resources"]):
            incoming = _normalize_resource_proposal(
                raw_resource,
                f"proposal.refresh.resources[{index}]",
                module_ids,
                run_id,
                prepared_at,
            )
            _upsert_resource(registry, incoming, run_id)
        resource_index = {(item["work_id"], item["revision_key"]): item for item in registry["resources"]}
        normalized_candidates: list[dict[str, Any]] = []
        for index, raw_candidate in enumerate(refresh["candidates"]):
            candidate = _normalize_candidate_proposal(raw_candidate, f"proposal.refresh.candidates[{index}]", module_index, resource_index)
            portfolio_path = module_index[candidate["module_id"]]["portfolio_path"]
            portfolio_snapshot = _snapshot_path(root, portfolio_path, "file", "module portfolio")
            if portfolio_snapshot["sha256"] == ABSENT and candidate["desired_state"] == "qualified":
                _fail("conflict", "candidate cannot qualify while its module portfolio is missing", candidate_id=candidate["candidate_id"], module_id=candidate["module_id"])
            if candidate["desired_state"] == "qualified":
                resource = resource_index[(candidate["work_id"], candidate["revision_key"])]
                claims = [claim for claim in resource["claims"] if claim["claim_id"] in candidate["claim_ids"]]
                if not claims:
                    _fail(
                        "conflict",
                        "qualified candidate must identify key claims",
                        candidate_id=candidate["candidate_id"],
                    )
                for claim in claims:
                    direct_support = any(
                        evidence["role"] != "discovery-index"
                        and evidence["direction"] == "supports"
                        for evidence in claim["evidence"]
                    )
                    if (
                        claim["status"] not in {"verified", "qualified"}
                        or not direct_support
                    ):
                        _fail(
                            "conflict",
                            "every key claim of a qualified candidate needs a verified or qualified status and direct non-discovery support",
                            candidate_id=candidate["candidate_id"],
                            claim_id=claim["claim_id"],
                            status=claim["status"],
                        )
                has_primary_anchor = any(
                    any(
                        evidence["role"] == "normative-primary"
                        and evidence["direction"] == "supports"
                        for evidence in claim["evidence"]
                    )
                    for claim in claims
                )
                if not has_primary_anchor:
                    _fail(
                        "conflict",
                        "qualified candidate lacks a direct normative-primary anchor",
                        candidate_id=candidate["candidate_id"],
                    )
            normalized_candidates.append(candidate)
            applied = _apply_refresh_candidate(registry, candidate, at=prepared_at, run_id=run_id)
            decision_units.append({
                "decision_unit_id": applied["decision_unit_id"],
                "candidate_id": applied["candidate_id"],
                "work_id": applied["work_id"],
                "revision_key": applied["revision_key"],
                "module_id": applied["module_id"],
                "action": applied["action"],
                "target_slot": applied["target_slot"],
                "claim_ids": applied["claim_ids"],
                "outcome": applied["current_state"],
                "count_change": 0,
                "budget_change": 0,
                "preserve_learning_state": applied["preserve_learning_state"],
            })
        if len({item["candidate_id"] for item in normalized_candidates}) != len(normalized_candidates):
            _fail("malformed", "refresh contains duplicate candidate decision units")

        coverage_index = {(item["scope_kind"], item["scope_id"]): item for item in registry["coverage"]}
        normalized_coverage: list[dict[str, Any]] = []
        for index, raw_coverage in enumerate(refresh["coverage"]):
            item = _normalize_coverage(raw_coverage, f"proposal.refresh.coverage[{index}]", managed, coverage_index, prepared_at)
            key = (item["scope_kind"], item["scope_id"])
            if any((existing["scope_kind"], existing["scope_id"]) == key for existing in normalized_coverage):
                _fail("malformed", "refresh contains duplicate coverage scopes", scope_kind=key[0], scope_id=key[1])
            normalized_coverage.append(item)
            if item["status"] in {"covered", "no-hit"}:
                updated = {"scope_kind": key[0], "scope_id": key[1], "cursor": item["cursor_after"], "updated_at": prepared_at, "last_successful_run": run_id}
                if key in coverage_index:
                    coverage_index[key].update(updated)
                else:
                    registry["coverage"].append(updated)
                    coverage_index[key] = updated
        expected_coverage = {
            *[("source", scope_id) for scope_id in source_index],
            *[("query", scope_id) for scope_id in query_index],
        }
        actual_coverage = {
            (item["scope_kind"], item["scope_id"])
            for item in normalized_coverage
        }
        if actual_coverage != expected_coverage:
            missing = sorted(expected_coverage - actual_coverage)
            unexpected = sorted(actual_coverage - expected_coverage)
            _fail(
                "malformed",
                "refresh coverage must explicitly account for every configured source and query",
                missing=missing,
                unexpected=unexpected,
            )
        writes = [_normalize_write(item, f"proposal.writes[{index}]", operation, managed, {unit["decision_unit_id"] for unit in decision_units}) for index, item in enumerate(obj["writes"])]
        if len(writes) != 1:
            _fail("malformed", "refresh must create exactly one immutable report")
        report_naming = configuration["preferences"].get("report_naming")
        if report_naming is not None:
            prepared_date = dt.datetime.fromisoformat(prepared_at.replace("Z", "+00:00")).date()
            if report_naming == "run-id":
                expected_name = f"{run_id}.md"
            elif report_naming == "date":
                expected_name = f"{prepared_date.isoformat()}.md"
            else:
                iso_year, iso_week, _iso_day = prepared_date.isocalendar()
                expected_name = f"{iso_year}-W{iso_week:02d}.md"
            if PurePosixPath(writes[0]["path"]).name != expected_name:
                _fail("conflict", "refresh report path does not match configured report_naming", expected=expected_name, actual=PurePosixPath(writes[0]["path"]).name)
        if writes[0]["decision_unit_ids"]:
            _fail("malformed", "refresh report decision IDs are generated by the tool; proposal must leave them empty")
        writes[0]["decision_unit_ids"] = sorted(unit["decision_unit_id"] for unit in decision_units)
        report_metadata = {
            "schema": "agent-skills.resource-report/v1",
            "run_id": run_id,
            "prepared_at": prepared_at,
            "registry_generation": registry["generation"] + 1,
            "registry_base_sha256": registry_before_sha,
            "active_overlays": active_overlays,
            "coverage": sorted(normalized_coverage, key=lambda item: (item["scope_kind"], item["scope_id"])),
        }
        writes[0]["after_text"] = (
            "<!-- resource-planning-snapshot\n"
            + _render_json(report_metadata).decode("utf-8").rstrip("\n")
            + "\n-->\n\n"
            + writes[0]["after_text"]
        )
        report_bytes = writes[0]["after_text"].encode("utf-8")
        registry["runs"].append({
            "run_id": run_id,
            "operation_kind": "refresh",
            "prepared_at": prepared_at,
            "active_overlays": active_overlays,
            "coverage": sorted(normalized_coverage, key=lambda item: (item["scope_kind"], item["scope_id"])),
            "report": {"path": writes[0]["path"], "sha256": _sha256(report_bytes)},
            "decision_unit_ids": sorted(unit["decision_unit_id"] for unit in decision_units),
        })
        registry_changed = True

    else:
        review = _strict_object(obj["review"], "proposal.review", {"run_id", "active_overlays", "decisions"}, {"run_id", "active_overlays", "decisions"})
        run_id = _run_id(review["run_id"], "proposal.review.run_id")
        if any(item["run_id"] == run_id for item in registry["runs"]):
            _fail("conflict", "review run_id already exists", run_id=run_id)
        active_overlays = _active_overlays(review["active_overlays"], managed, prepared_at)
        if not isinstance(review["decisions"], list) or not review["decisions"]:
            _fail("malformed", "review.decisions must be a non-empty array")
        candidate_index = {item["candidate_id"]: item for item in registry["candidates"]}
        decisions = [_normalize_review_decision(item, f"proposal.review.decisions[{index}]", candidate_index) for index, item in enumerate(review["decisions"])]
        if len({item["candidate_id"] for item in decisions}) != len(decisions):
            _fail("malformed", "review contains duplicate candidate decisions")
        for decision in decisions:
            candidate = candidate_index[decision["candidate_id"]]
            if dt.datetime.fromisoformat(candidate["review_after"].replace("Z", "+00:00")) > dt.datetime.fromisoformat(prepared_at.replace("Z", "+00:00")):
                _fail("conflict", "candidate has not reached review_after", candidate_id=candidate["candidate_id"], review_after=candidate["review_after"])
            _apply_review_decision(registry, decision, at=prepared_at, run_id=run_id)
            decision_unit = {
                "decision_unit_id": decision["decision_unit_id"],
                "candidate_id": decision["candidate_id"],
                "work_id": candidate["work_id"],
                "revision_key": candidate["revision_key"],
                "module_id": candidate["module_id"],
                "action": "retire" if decision["outcome"] == "retire" else candidate["action"],
                "target_slot": candidate["target_slot"],
                "claim_ids": candidate["claim_ids"],
                "outcome": decision["outcome"],
                "count_change": decision["count_change"],
                "budget_change": decision["budget_change"],
                "preserve_learning_state": decision["preserve_learning_state"],
            }
            if "replaces_candidate_id" in decision:
                decision_unit["replaces_candidate_id"] = decision[
                    "replaces_candidate_id"
                ]
                decision_unit["replaces_decision_unit_id"] = decision[
                    "replaces_decision_unit_id"
                ]
            decision_units.append(decision_unit)
        allowed = {unit["decision_unit_id"] for unit in decision_units}
        writes = [_normalize_write(item, f"proposal.writes[{index}]", operation, managed, allowed) for index, item in enumerate(obj["writes"])]
        _review_write_contract(decision_units, writes)
        registry["runs"].append({"run_id": run_id, "operation_kind": "review", "prepared_at": prepared_at, "active_overlays": active_overlays, "coverage": [], "report": None, "decision_unit_ids": sorted(allowed)})
        registry_changed = True

    paths = [write["path"] for write in writes]
    if len(paths) != len(set(paths)):
        _fail("malformed", "proposal contains duplicate write targets")
    if registry_changed and configuration["storage"]["registry_path"] in paths:
        _fail("malformed", "proposal must not handwrite the registry target")

    dependencies = _dependency_snapshots(
        root,
        managed,
        context_relative,
        extra_dependencies,
        registered_reports,
    )
    targets = [_target_record(root, write) for write in writes]
    if operation in {"research-brief", "refresh"} and targets[0]["before_sha256"] != ABSENT:
        _fail("conflict", f"{operation} target already exists and is immutable", path=targets[0]["path"])
    if operation == "review" and any(target["before_sha256"] == target["after_sha256"] for target in targets):
        _fail("malformed", "review proposal contains a no-op target")

    if registry_changed:
        registry["generation"] += 1
        normalized_registry = validate_registry(registry, allow_preview_sentinel=True)
        registry_write = {"path": configuration["storage"]["registry_path"], "role": "registry", "after_text": _render_json(normalized_registry).decode("utf-8"), "decision_unit_ids": sorted(unit["decision_unit_id"] for unit in decision_units)}
        registry_target = _target_record(root, registry_write)
        if registry_target["before_sha256"] != registry_before_sha:
            _fail("conflict", "registry changed while preparing")
        targets.append(registry_target)

    decision_units = sorted(decision_units, key=lambda item: item["decision_unit_id"])
    plan: dict[str, Any] = {
        "schema": PLAN_SCHEMA,
        "operation_kind": operation,
        "prepared_at": prepared_at,
        "context_path": context_relative,
        "context_sha256": _sha256(context_bytes),
        "proposal_sha256": _sha256(_canonical_json(proposal)),
        "adapter_catalog_sha256": _sha256(_canonical_json(ADAPTER_CATALOG)),
        "active_overlays": active_overlays,
        "dependencies": dependencies,
        "decision_units": decision_units,
        "targets": targets,
    }
    preview = _plan_preview_digest(plan)
    for target in targets:
        if target["role"] == "registry":
            _fill_registry_preview(target, preview)
    plan["preview_digest"] = preview
    decision_ids = [unit["decision_unit_id"] for unit in decision_units]
    plan["txn_id"] = _stable_id("txn", operation, preview, decision_ids)
    validate_plan(plan, managed)
    return plan


def _validate_target_against_context(target: Mapping[str, Any], operation: str, wrapper: Mapping[str, Any]) -> None:
    path = _safe_relative(target["path"], "plan target path")
    role = target["role"]
    config = wrapper["context"]["configuration"]
    storage = config["storage"]
    modules = _configuration_indexes(wrapper)[0]
    if role == "registry":
        if operation not in {"refresh", "review"} or path != storage["registry_path"]:
            _fail("safety", "registry target is not authorized by operation/context", path=path)
    elif role == "report":
        if operation != "refresh" or PurePosixPath(path).parent != PurePosixPath(storage["report_directory"]):
            _fail("safety", "report target is not authorized by operation/context", path=path)
    elif role == "research-brief":
        if operation != "research-brief" or PurePosixPath(path).parent != PurePosixPath(storage["research_brief_directory"]):
            _fail("safety", "brief target is not authorized by operation/context", path=path)
    elif role in {"portfolio", "progress-projection"}:
        if operation != "review":
            _fail("safety", "portfolio/progress targets are review-only")
        module_id = target.get("module_id")
        if module_id not in modules:
            _fail("safety", "plan target uses an unknown module", module_id=module_id)
        expected = modules[module_id]["portfolio_path"] if role == "portfolio" else modules[module_id].get("progress_projection")
        if path != expected:
            _fail("safety", "plan target path does not match module context", path=path)
        if target.get("adapter_id") != modules[module_id]["adapter"]["adapter_id"] or target.get("adapter_version") != modules[module_id]["adapter"]["version"]:
            _fail("integrity", "plan target adapter binding changed")
    else:
        _fail("malformed", "plan target has an unsupported role", role=role)


def validate_plan(data: Any, wrapper: Mapping[str, Any]) -> dict[str, Any]:
    obj = _strict_object(data, "plan", {"schema", "operation_kind", "prepared_at", "context_path", "context_sha256", "proposal_sha256", "adapter_catalog_sha256", "active_overlays", "dependencies", "decision_units", "targets", "preview_digest", "txn_id"}, {"schema", "operation_kind", "prepared_at", "context_path", "context_sha256", "proposal_sha256", "adapter_catalog_sha256", "active_overlays", "dependencies", "decision_units", "targets", "preview_digest", "txn_id"})
    if obj["schema"] != PLAN_SCHEMA:
        _fail("malformed", "unsupported plan schema")
    operation = _enum(obj["operation_kind"], "plan.operation_kind", {"research-brief", "refresh", "review"})
    _iso_time(obj["prepared_at"], "plan.prepared_at")
    _safe_relative(obj["context_path"], "plan.context_path")
    for key in ("context_sha256", "proposal_sha256", "adapter_catalog_sha256", "preview_digest"):
        _digest(obj[key], f"plan.{key}")
    if obj["adapter_catalog_sha256"] != _sha256(_canonical_json(ADAPTER_CATALOG)):
        _fail("integrity", "plan adapter catalog does not match this tool version")
    _active_overlays(obj["active_overlays"], wrapper, obj["prepared_at"])
    if not isinstance(obj["dependencies"], list) or not isinstance(obj["decision_units"], list) or not isinstance(obj["targets"], list):
        _fail("malformed", "plan collections must be arrays")
    dep_paths: set[tuple[str, str]] = set()
    for index, raw in enumerate(obj["dependencies"]):
        dep = _strict_object(raw, f"plan.dependencies[{index}]", {"path", "kind", "sha256"}, {"path", "kind", "sha256"})
        key = (_enum(dep["kind"], f"plan.dependencies[{index}].kind", {"file"}), _safe_relative(dep["path"], f"plan.dependencies[{index}].path"))
        if key in dep_paths:
            _fail("integrity", "plan contains duplicate dependency paths")
        dep_paths.add(key)
        if dep["sha256"] != ABSENT:
            _digest(dep["sha256"], f"plan.dependencies[{index}].sha256")
    decision_ids = []
    decision_index: dict[str, Mapping[str, Any]] = {}
    for index, unit in enumerate(obj["decision_units"]):
        record = _strict_object(
            unit,
            f"plan.decision_units[{index}]",
            {
                "decision_unit_id",
                "candidate_id",
                "work_id",
                "revision_key",
                "module_id",
                "action",
                "target_slot",
                "claim_ids",
                "outcome",
                "count_change",
                "budget_change",
                "preserve_learning_state",
                "replaces_candidate_id",
                "replaces_decision_unit_id",
            },
            {
                "decision_unit_id",
                "candidate_id",
                "work_id",
                "revision_key",
                "module_id",
                "action",
                "target_slot",
                "claim_ids",
                "outcome",
                "count_change",
                "budget_change",
                "preserve_learning_state",
            },
        )
        decision_id = _string(record["decision_unit_id"], f"plan.decision_units[{index}].decision_unit_id")
        decision_ids.append(decision_id)
        decision_index[decision_id] = record
        _string_list(record["claim_ids"], f"plan.decision_units[{index}].claim_ids")
        _identifier(record["module_id"], f"plan.decision_units[{index}].module_id")
        _enum(record["action"], f"plan.decision_units[{index}].action", ACTIONS)
        _identifier(record["target_slot"], f"plan.decision_units[{index}].target_slot")
        allowed_outcomes = (
            {"draft", "blocked", "qualified"}
            if operation == "refresh"
            else {"apply", "defer", "reject", "supersede", "block", "retire"}
        )
        _enum(
            record["outcome"],
            f"plan.decision_units[{index}].outcome",
            allowed_outcomes,
        )
        for numeric in ("count_change", "budget_change"):
            if isinstance(record[numeric], bool) or not isinstance(
                record[numeric], int
            ):
                _fail(
                    "integrity",
                    f"plan.decision_units[{index}].{numeric} must be an integer",
                )
        _string_list(
            record["preserve_learning_state"],
            f"plan.decision_units[{index}].preserve_learning_state",
        )
        replacement_fields = {
            "replaces_candidate_id",
            "replaces_decision_unit_id",
        } & set(record)
        if replacement_fields and replacement_fields != {
            "replaces_candidate_id",
            "replaces_decision_unit_id",
        }:
            _fail(
                "integrity",
                "replace decision-unit binding is incomplete",
                decision_unit_id=decision_id,
            )
        if replacement_fields:
            _string(
                record["replaces_candidate_id"],
                f"plan.decision_units[{index}].replaces_candidate_id",
            )
            _string(
                record["replaces_decision_unit_id"],
                f"plan.decision_units[{index}].replaces_decision_unit_id",
            )
            if record["action"] != "replace" or record["outcome"] != "apply":
                _fail(
                    "integrity",
                    "replace old-side binding is only valid for an applied replace decision",
                    decision_unit_id=decision_id,
                )
    if decision_ids != sorted(set(decision_ids)):
        _fail("integrity", "plan decision units must be unique and sorted")
    target_paths: set[str] = set()
    registry_count = 0
    new_registry_run: Mapping[str, Any] | None = None
    report_binding: tuple[str, str] | None = None
    portfolio_bound: set[str] = set()
    module_binding_counts: dict[str, dict[str, int]] = {
        decision_id: {"portfolio": 0, "progress-projection": 0}
        for decision_id in decision_ids
    }
    for index, raw in enumerate(obj["targets"]):
        target = _strict_object(
            raw,
            f"plan.targets[{index}]",
            {
                "path",
                "role",
                "decision_unit_ids",
                "replaces_decision_unit_ids",
                "module_id",
                "action",
                "adapter_id",
                "adapter_version",
                "before_sha256",
                "before_base64",
                "after_sha256",
                "after_base64",
                "diff",
            },
            {
                "path",
                "role",
                "decision_unit_ids",
                "before_sha256",
                "before_base64",
                "after_sha256",
                "after_base64",
                "diff",
            },
        )
        path = _safe_relative(target["path"], f"plan.targets[{index}].path")
        if path in target_paths:
            _fail("integrity", "plan contains duplicate targets", path=path)
        target_paths.add(path)
        _validate_target_against_context(target, operation, wrapper)
        if target["role"] in {"registry", "report", "research-brief"} and any(key in target for key in ("module_id", "action", "adapter_id", "adapter_version", "replaces_decision_unit_ids")):
            _fail("integrity", "non-module target contains module/adapter metadata", path=path)
        if target["role"] == "registry":
            registry_count += 1
            if index != len(obj["targets"]) - 1:
                _fail("integrity", "registry must be the final replacement target")
        bound = sorted(_string_list(target["decision_unit_ids"], f"plan.targets[{index}].decision_unit_ids"))
        if not set(bound) <= set(decision_ids):
            _fail("integrity", "plan target binds an unknown decision unit")
        if target["role"] in {"registry", "report"} and bound != decision_ids:
            _fail("integrity", "registry/report target must bind the complete decision-unit set", path=path)
        if target["role"] == "research-brief" and bound:
            _fail("integrity", "research brief must not bind candidate decision units")
        if target["role"] in {"portfolio", "progress-projection"}:
            if "replaces_decision_unit_ids" not in target:
                _fail(
                    "integrity",
                    "module target lacks explicit replace old-side bindings",
                    path=path,
                )
            expected_related: set[str] = set()
            for decision_id in bound:
                if target["module_id"] != decision_index[decision_id]["module_id"]:
                    _fail(
                        "integrity",
                        "module target module disagrees with bound decision unit",
                        decision_unit_id=decision_id,
                    )
                if target["action"] != decision_index[decision_id]["action"]:
                    _fail("integrity", "module target action disagrees with bound decision unit", decision_unit_id=decision_id)
                if decision_index[decision_id]["outcome"] not in {"apply", "retire"}:
                    _fail(
                        "integrity",
                        "registry-only review outcome binds a module target",
                        decision_unit_id=decision_id,
                    )
                replacement = decision_index[decision_id].get(
                    "replaces_decision_unit_id"
                )
                if replacement is not None:
                    expected_related.add(replacement)
                module_binding_counts[decision_id][target["role"]] += 1
            related = set(
                _string_list(
                    target["replaces_decision_unit_ids"],
                    f"plan.targets[{index}].replaces_decision_unit_ids",
                )
            )
            if related != expected_related:
                _fail(
                    "integrity",
                    "module target replace old-side bindings disagree with decision units",
                    path=path,
                    expected=sorted(expected_related),
                    actual=sorted(related),
                )
            if target["role"] == "portfolio":
                portfolio_bound.update(bound)
        if target["before_sha256"] != ABSENT:
            _digest(target["before_sha256"], f"plan.targets[{index}].before_sha256")
        try:
            before = None if target["before_base64"] is None else base64.b64decode(target["before_base64"], validate=True)
            after = base64.b64decode(target["after_base64"], validate=True)
        except (ValueError, TypeError):
            _fail("integrity", "plan target contains invalid base64 bytes", path=path)
        if (before is None) != (target["before_sha256"] == ABSENT):
            _fail("integrity", "plan target before bytes/digest disagree", path=path)
        if before is not None and _sha256(before) != target["before_sha256"]:
            _fail("integrity", "plan target before bytes were tampered", path=path)
        if _sha256(after) != _digest(target["after_sha256"], f"plan.targets[{index}].after_sha256"):
            _fail("integrity", "plan target after bytes were tampered", path=path)
        if target["diff"] != _unified_diff(path, before, after):
            _fail("integrity", "plan target diff is not derived from exact bytes", path=path)
        if target["role"] == "registry":
            try:
                registry = validate_registry(json.loads(after.decode("utf-8")))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                _fail("integrity", "plan registry after bytes are invalid", reason=str(exc))
            new_registry_run = _validate_registry_evolution(
                before,
                registry,
                obj["preview_digest"],
                operation,
                obj["prepared_at"],
                obj["active_overlays"],
                decision_ids,
            )
        if target["role"] == "report":
            report_binding = (path, target["after_sha256"])
        if target["role"] == "portfolio":
            module = _configuration_indexes(wrapper)[0][target["module_id"]]
            _validate_adapter_scoped_change(
                target,
                decision_index,
                module,
                f"plan.targets[{index}]",
            )
        if target["role"] == "progress-projection":
            module = _configuration_indexes(wrapper)[0][target["module_id"]]
            _validate_adapter_scoped_change(
                target,
                decision_index,
                module,
                f"plan.targets[{index}]",
            )
        if target["role"] in {"report", "research-brief"} and target["before_sha256"] != ABSENT:
            _fail("integrity", "immutable report/brief targets must be create-only", path=path)
    expected_registry_count = 0 if operation == "research-brief" else 1
    if registry_count != expected_registry_count:
        _fail("integrity", "operation has an invalid registry target count", operation_kind=operation)
    if operation == "research-brief" and (len(obj["targets"]) != 1 or obj["targets"][0]["role"] != "research-brief"):
        _fail("integrity", "research-brief plan has an invalid write set")
    if operation == "research-brief" and decision_ids:
        _fail("integrity", "research-brief plan must not contain decision units")
    if operation == "refresh" and (len(obj["targets"]) != 2 or obj["targets"][0]["role"] != "report"):
        _fail("integrity", "refresh plan must write one report then registry")
    if operation == "refresh" and (
        new_registry_run is None
        or report_binding is None
        or new_registry_run["report"]
        != {"path": report_binding[0], "sha256": report_binding[1]}
    ):
        _fail(
            "integrity",
            "refresh registry run is not bound to the exact immutable report target",
        )
    if operation == "review" and any(target["role"] in {"report", "research-brief"} for target in obj["targets"]):
        _fail("integrity", "review plan must not write reports or briefs")
    if operation == "review":
        if not decision_ids:
            _fail("integrity", "review plan must contain at least one decision unit")
        required_portfolio = {decision_id for decision_id, unit in decision_index.items() if unit["outcome"] in {"apply", "retire"}}
        if not required_portfolio <= portfolio_bound:
            _fail("integrity", "portfolio-changing review decision lacks a portfolio target", decision_unit_ids=sorted(required_portfolio - portfolio_bound))
        for decision_id, unit in decision_index.items():
            counts = module_binding_counts[decision_id]
            if unit["outcome"] in {"apply", "retire"}:
                if counts["portfolio"] != 1 or counts["progress-projection"] > 1:
                    _fail(
                        "integrity",
                        "portfolio-changing decision has an invalid exact target binding",
                        decision_unit_id=decision_id,
                        counts=counts,
                    )
            elif counts["portfolio"] or counts["progress-projection"]:
                _fail(
                    "integrity",
                    "registry-only decision binds a module target",
                    decision_unit_id=decision_id,
                    counts=counts,
                )
    expected_preview = _plan_preview_digest(obj, current_digest=obj["preview_digest"])
    if expected_preview != obj["preview_digest"]:
        _fail("integrity", "plan preview_digest does not match exact normalized bytes", expected=expected_preview)
    expected_txn = _stable_id("txn", operation, obj["preview_digest"], decision_ids)
    if obj["txn_id"] != expected_txn:
        _fail("integrity", "plan txn_id is not deterministic", expected=expected_txn)
    return copy.deepcopy(obj)


def verify_repository(repo: Path | str, wrapper: Any, context_path: str, now: str) -> dict[str, Any]:
    """Read-only verification of context, registry, reports, cursors, and readiness."""

    root = _absolute(Path(repo))
    managed = validate_runtime_wrapper(wrapper)
    _validate_source_binding(root, managed)
    now_text = _iso_time(now, "now")
    context_relative = _safe_relative(context_path, "context_path")
    context_file = _repo_path(root, context_relative, label="managed context", leaf_kind="file", allow_missing_leaf=False)
    context_bytes = _read_bytes(context_file, "managed context")
    try:
        disk_wrapper = json.loads(context_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        _fail("malformed", "managed context file is invalid", reason=str(exc))
    if disk_wrapper != wrapper:
        _fail("conflict", "provided managed context differs from context_path")
    dependencies = _dependency_snapshots(root, managed, context_relative, [])
    required_paths = {
        context_relative,
        *(source["path"] for source in managed["sources"].values()),
        *managed["allowlist"]["tracked_files"],
    }
    for dependency in dependencies:
        if dependency["path"] in required_paths and dependency["sha256"] == ABSENT:
            _fail("conflict", "a materialized tracked input is missing", path=dependency["path"], kind=dependency["kind"])

    storage = managed["context"]["configuration"]["storage"]
    journal = _repo_path(root, storage["journal_path"], label="transaction journal", leaf_kind="file", allow_missing_leaf=True)
    if _path_present(journal):
        _fail("conflict", "an unfinished transaction journal exists; recover before any new operation", path=storage["journal_path"])
    registry, registry_sha = _load_registry(root, managed)
    _validate_registered_reports(root, managed, registry)

    modules, sources, queries, _overlays = _configuration_indexes(managed)
    for candidate in registry["candidates"]:
        if candidate["module_id"] not in modules:
            _fail("integrity", "registry candidate references a module absent from current context", candidate_id=candidate["candidate_id"], module_id=candidate["module_id"])
    for cursor in registry["coverage"]:
        index = sources if cursor["scope_kind"] == "source" else queries
        if cursor["scope_id"] not in index:
            _fail("integrity", "registry cursor references a scope absent from current context", scope_kind=cursor["scope_kind"], scope_id=cursor["scope_id"])
    now_value = dt.datetime.fromisoformat(now_text.replace("Z", "+00:00"))
    ready = sorted(candidate["candidate_id"] for candidate in registry["candidates"] if dt.datetime.fromisoformat(candidate["review_after"].replace("Z", "+00:00")) <= now_value)
    reviewable = sorted(candidate["candidate_id"] for candidate in registry["candidates"] if candidate["current_state"] in {"qualified", "deferred", "blocked"} and dt.datetime.fromisoformat(candidate["review_after"].replace("Z", "+00:00")) <= now_value)
    return {
        "repository_id": managed["repository_id"],
        "registry_present": registry_sha != ABSENT,
        "registry_sha256": registry_sha,
        "generation": registry["generation"],
        "resource_count": len(registry["resources"]),
        "candidate_count": len(registry["candidates"]),
        "ready_candidate_ids": ready,
        "reviewable_ready_candidate_ids": reviewable,
        "coverage_cursor_count": len(registry["coverage"]),
        "run_count": len(registry["runs"]),
        "dependency_count": len(dependencies),
    }


def _current_sha(path: Path) -> str:
    if not _path_present(path):
        return ABSENT
    if _is_link_or_junction(path) or not path.is_file():
        _fail("safety", "managed target is no longer a regular file", path=os.fspath(path))
    return _sha256(_read_bytes(path, "managed target"))


def _assert_plan_cas(repo: Path, plan: Mapping[str, Any]) -> None:
    for dependency in plan["dependencies"]:
        current = _snapshot_path(repo, dependency["path"], dependency["kind"], "plan dependency")["sha256"]
        if current != dependency["sha256"]:
            _fail("conflict", "plan dependency changed after preview", path=dependency["path"], expected=dependency["sha256"], actual=current)
    for target in plan["targets"]:
        path = _repo_path(repo, target["path"], label="plan target", leaf_kind="file", allow_missing_leaf=True)
        current = _current_sha(path)
        if current != target["before_sha256"]:
            _fail("conflict", "plan target changed after preview", path=target["path"], expected=target["before_sha256"], actual=current)


def _all_target_states(repo: Path, plan: Mapping[str, Any]) -> list[str]:
    states: list[str] = []
    for target in plan["targets"]:
        path = _repo_path(repo, target["path"], label="plan target", leaf_kind="file", allow_missing_leaf=True)
        current = _current_sha(path)
        if current == target["after_sha256"]:
            states.append("after")
        elif current == target["before_sha256"]:
            states.append("before")
        else:
            states.append("third")
    return states


def _atomic_replace(path: Path, content: bytes, expected_sha256: str) -> None:
    parent = path.parent
    if not parent.is_dir() or _is_link_or_junction(parent):
        _fail("safety", "managed target parent is unavailable or unsafe", path=os.fspath(parent))
    current = _current_sha(path)
    if current != expected_sha256:
        _fail("conflict", "managed target failed immediate CAS", path=os.fspath(path), expected=expected_sha256, actual=current)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=os.fspath(parent))
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        if expected_sha256 == ABSENT:
            try:
                os.link(temporary, path)
            except FileExistsError:
                _fail("conflict", "managed target appeared during create", path=os.fspath(path))
            temporary.unlink()
        else:
            if _current_sha(path) != expected_sha256:
                _fail("conflict", "managed target changed during replace", path=os.fspath(path))
            os.replace(temporary, path)
    finally:
        if _path_present(temporary):
            try:
                temporary.unlink()
            except OSError:
                pass


def _atomic_remove(path: Path, expected_sha256: str) -> None:
    if _current_sha(path) != expected_sha256:
        _fail("conflict", "managed target changed before rollback removal", path=os.fspath(path))
    try:
        path.unlink()
    except OSError as exc:
        _fail("integrity", "cannot remove transaction-created target during rollback", path=os.fspath(path), reason=str(exc))


def _journal_payload(journal: Mapping[str, Any]) -> dict[str, Any]:
    return {key: copy.deepcopy(value) for key, value in journal.items() if key != "journal_digest"}


def _seal_journal(journal: dict[str, Any]) -> bytes:
    journal["journal_digest"] = _sha256(_canonical_json(_journal_payload(journal)))
    return _render_json(journal)


def _validate_journal(data: Any, wrapper: Mapping[str, Any]) -> dict[str, Any]:
    obj = _strict_object(data, "journal", {"schema", "txn_id", "preview_digest", "phase", "completed", "plan", "journal_digest"}, {"schema", "txn_id", "preview_digest", "phase", "completed", "plan", "journal_digest"})
    if obj["schema"] != JOURNAL_SCHEMA:
        _fail("integrity", "unsupported transaction journal schema")
    _digest(obj["preview_digest"], "journal.preview_digest")
    _digest(obj["journal_digest"], "journal.journal_digest")
    if _sha256(_canonical_json(_journal_payload(obj))) != obj["journal_digest"]:
        _fail("integrity", "transaction journal digest is invalid")
    plan = validate_plan(obj["plan"], wrapper)
    if obj["txn_id"] != plan["txn_id"] or obj["preview_digest"] != plan["preview_digest"]:
        _fail("integrity", "transaction journal is not bound to its plan")
    _enum(obj["phase"], "journal.phase", {"prepared", "replacing", "validating", "rolling-back"})
    completed = _string_list(obj["completed"], "journal.completed")
    target_paths = [target["path"] for target in plan["targets"]]
    if completed != target_paths[: len(completed)]:
        _fail("integrity", "journal completed set is not an ordered plan prefix")
    return copy.deepcopy(obj)


def _create_journal(path: Path, journal: dict[str, Any]) -> None:
    data = _seal_journal(journal)
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        _fail("conflict", "an unfinished transaction journal already exists", path=os.fspath(path))
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        # A partial journal is intentionally retained for visible manual conflict.
        raise


def _update_journal(path: Path, journal: dict[str, Any]) -> None:
    data = _seal_journal(journal)
    expected = _current_sha(path)
    _atomic_replace(path, data, expected)


def _postconditions(
    repo: Path, plan: Mapping[str, Any], wrapper: Mapping[str, Any]
) -> None:
    for target in plan["targets"]:
        path = _repo_path(repo, target["path"], label="postcondition target", leaf_kind="file", allow_missing_leaf=False)
        data = _read_bytes(path, "postcondition target")
        if _sha256(data) != target["after_sha256"]:
            _fail("integrity", "target failed after-byte postcondition", path=target["path"])
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            _fail("integrity", "managed target is not UTF-8", path=target["path"])
        if target["role"] == "registry":
            validate_registry(json.loads(text))
    if plan["operation_kind"] in {"refresh", "review"}:
        registry, _registry_sha = _load_registry(repo, wrapper)
        _validate_registered_reports(repo, wrapper, registry)


def validate_execution_envelope(data: Any, plan: Mapping[str, Any]) -> dict[str, Any]:
    obj = _strict_object(data, "execution envelope", {"schema", "operation_kind", "txn_id", "preview_digest", "decision_unit_ids", "authorized"}, {"schema", "operation_kind", "txn_id", "preview_digest", "decision_unit_ids", "authorized"})
    if obj["schema"] != ENVELOPE_SCHEMA or obj["operation_kind"] != plan["operation_kind"] or obj["txn_id"] != plan["txn_id"] or obj["preview_digest"] != plan["preview_digest"]:
        _fail("conflict", "execution envelope does not match the exact plan")
    if obj["authorized"] is not True:
        _fail("conflict", "execution envelope is not authorized")
    decision_ids = sorted(_string_list(obj["decision_unit_ids"], "execution envelope.decision_unit_ids"))
    expected = [unit["decision_unit_id"] for unit in plan["decision_units"]]
    if decision_ids != expected:
        _fail("conflict", "execution envelope decision units do not match the preview", expected=expected, actual=decision_ids)
    return {"schema": ENVELOPE_SCHEMA, "operation_kind": plan["operation_kind"], "txn_id": plan["txn_id"], "preview_digest": plan["preview_digest"], "decision_unit_ids": decision_ids, "authorized": True}


def _rollback_exact(repo: Path, journal_path: Path, journal: dict[str, Any]) -> None:
    plan = journal["plan"]
    journal["phase"] = "rolling-back"
    _update_journal(journal_path, journal)
    for target in reversed(plan["targets"]):
        path = _repo_path(repo, target["path"], label="rollback target", leaf_kind="file", allow_missing_leaf=True)
        current = _current_sha(path)
        if current == target["before_sha256"]:
            continue
        if current != target["after_sha256"]:
            _fail("conflict", "rollback encountered a third-state target", path=target["path"], current=current)
        if target["before_sha256"] == ABSENT:
            _atomic_remove(path, target["after_sha256"])
        else:
            before = base64.b64decode(target["before_base64"], validate=True)
            _atomic_replace(path, before, target["after_sha256"])
    if any(state != "before" for state in _all_target_states(repo, plan)):
        _fail("integrity", "rollback did not restore every before state")
    journal_path.unlink()


def publish_plan(repo: Path | str, wrapper: Any, plan_data: Any, envelope_data: Any) -> dict[str, Any]:
    root = _absolute(Path(repo))
    managed = validate_runtime_wrapper(wrapper)
    _validate_source_binding(root, managed)
    plan = validate_plan(plan_data, managed)
    validate_execution_envelope(envelope_data, plan)
    context = _repo_path(root, plan["context_path"], label="managed context", leaf_kind="file", allow_missing_leaf=False)
    if _sha256(_read_bytes(context, "managed context")) != plan["context_sha256"]:
        _fail("conflict", "managed context changed after preview")
    journal_relative = managed["context"]["configuration"]["storage"]["journal_path"]
    journal_path = _repo_path(root, journal_relative, label="transaction journal", leaf_kind="file", allow_missing_leaf=True)
    if _path_present(journal_path):
        _fail("conflict", "an unfinished transaction exists; recover it first", path=journal_relative)

    if plan["operation_kind"] in {"refresh", "review"}:
        current_registry, _current_registry_sha = _load_registry(root, managed)
        _validate_registered_reports(root, managed, current_registry)

    states = _all_target_states(root, plan)
    if states and all(state == "after" for state in states):
        _postconditions(root, plan, managed)
        return {"status": "already-applied", "txn_id": plan["txn_id"], "preview_digest": plan["preview_digest"], "target_count": len(plan["targets"])}
    if any(state != "before" for state in states):
        _fail("conflict", "targets are neither the complete before nor complete after set", states=states)
    _assert_plan_cas(root, plan)

    journal = {"schema": JOURNAL_SCHEMA, "txn_id": plan["txn_id"], "preview_digest": plan["preview_digest"], "phase": "prepared", "completed": [], "plan": plan}
    _create_journal(journal_path, journal)
    try:
        # Close the race between the pre-journal CAS and exclusive journal
        # creation.  The journal is now the repository-local transaction lock.
        _assert_plan_cas(root, plan)
        journal["phase"] = "replacing"
        _update_journal(journal_path, journal)
        for target in plan["targets"]:
            path = _repo_path(root, target["path"], label="publish target", leaf_kind="file", allow_missing_leaf=True)
            after = base64.b64decode(target["after_base64"], validate=True)
            _atomic_replace(path, after, target["before_sha256"])
            journal["completed"].append(target["path"])
            _update_journal(journal_path, journal)
        journal["phase"] = "validating"
        _update_journal(journal_path, journal)
        _postconditions(root, plan, managed)
        journal_path.unlink()
    except (KeyboardInterrupt, SystemExit):
        raise
    except BaseException as original:
        try:
            current_journal = _validate_journal(_read_json_path(journal_path, "transaction journal"), managed)
            failed_states = _all_target_states(root, current_journal["plan"])
            if failed_states and all(state == "after" for state in failed_states):
                try:
                    _postconditions(root, current_journal["plan"], managed)
                except BaseException:
                    _rollback_exact(root, journal_path, current_journal)
                else:
                    journal_path.unlink()
                    return {"status": "applied", "txn_id": plan["txn_id"], "preview_digest": plan["preview_digest"], "target_count": len(plan["targets"])}
            else:
                _rollback_exact(root, journal_path, current_journal)
        except BaseException as rollback_error:
            _fail("integrity", "publish failed and automatic rollback could not complete", publish_error=str(original), rollback_error=str(rollback_error), journal=journal_relative)
        if isinstance(original, ResourcePlanningError):
            raise original
        _fail("integrity", "publish failed; all targets were rolled back", reason=str(original))
    return {"status": "applied", "txn_id": plan["txn_id"], "preview_digest": plan["preview_digest"], "target_count": len(plan["targets"])}


def recover_transaction(repo: Path | str, wrapper: Any) -> dict[str, Any]:
    root = _absolute(Path(repo))
    managed = validate_runtime_wrapper(wrapper)
    _validate_source_binding(root, managed)
    journal_relative = managed["context"]["configuration"]["storage"]["journal_path"]
    journal_path = _repo_path(root, journal_relative, label="transaction journal", leaf_kind="file", allow_missing_leaf=True)
    if not _path_present(journal_path):
        return {"status": "clean", "journal": journal_relative}
    journal = _validate_journal(_read_json_path(journal_path, "transaction journal"), managed)
    states = _all_target_states(root, journal["plan"])
    if any(state == "third" for state in states):
        _fail("conflict", "recovery found a third-state target; manual resolution is required", states=states, journal=journal_relative)
    if states and all(state == "after" for state in states):
        try:
            _postconditions(root, journal["plan"], managed)
        except ResourcePlanningError:
            _rollback_exact(root, journal_path, journal)
            return {"status": "rolled-back", "txn_id": journal["txn_id"], "reason": "after postcondition failed"}
        journal_path.unlink()
        return {"status": "completed", "txn_id": journal["txn_id"]}
    _rollback_exact(root, journal_path, journal)
    return {"status": "rolled-back", "txn_id": journal["txn_id"]}


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        _fail("usage", message)


def _parser() -> argparse.ArgumentParser:
    parser = _Parser(description="Deterministic resource-planning validator and publisher")
    subparsers = parser.add_subparsers(dest="command", required=True)

    verify = subparsers.add_parser("verify", help="read-only validation")
    verify.add_argument("--repo", required=True)
    verify.add_argument("--context", required=True)
    verify.add_argument("--now", required=True, help="timezone-aware ISO-8601 timestamp")

    prepare = subparsers.add_parser("prepare", help="build a zero-repository-write preview plan")
    prepare.add_argument("--repo", required=True)
    prepare.add_argument("--context", required=True)
    prepare.add_argument("--proposal", required=True)
    prepare.add_argument("--plan-out", help="optional new plan file outside the repository")

    publish = subparsers.add_parser("publish", help="publish one exact approved plan")
    publish.add_argument("--repo", required=True)
    publish.add_argument("--context", required=True)
    publish.add_argument("--plan", required=True)
    publish.add_argument("--envelope", required=True)

    recover = subparsers.add_parser("recover", help="mechanically resolve an existing journal")
    recover.add_argument("--repo", required=True)
    recover.add_argument("--context", required=True)
    return parser


def _load_context_argument(repo: Path, raw: str) -> tuple[dict[str, Any], str]:
    relative = _argument_relative(repo, raw, "--context")
    path = _repo_path(repo, relative, label="managed context", leaf_kind="file", allow_missing_leaf=False)
    data = _read_json_path(path, "managed context")
    return validate_runtime_wrapper(data), relative


def _read_external_json(raw: str, label: str) -> Any:
    path = _absolute(Path(raw))
    if not _path_present(path) or _is_link_or_junction(path) or not path.is_file():
        _fail("safety", f"{label} must be an existing regular file", path=os.fspath(path))
    return _read_json_path(path, label)


def _write_plan_outside_repo(repo: Path, raw: str, plan: Mapping[str, Any]) -> str:
    path = _absolute(Path(raw))
    root = _absolute(repo)
    try:
        common = os.path.commonpath([os.fspath(root), os.fspath(path)])
    except ValueError:
        common = ""
    if common and os.path.normcase(common) == os.path.normcase(os.fspath(root)):
        _fail("safety", "--plan-out must be outside the consumption repository")
    if _path_present(path):
        _fail("conflict", "--plan-out target already exists", path=os.fspath(path))
    if not path.parent.is_dir() or _is_link_or_junction(path.parent):
        _fail("safety", "--plan-out parent must be an existing real directory", path=os.fspath(path.parent))
    data = _render_json(plan)
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError:
        _fail("conflict", "--plan-out target appeared during create", path=os.fspath(path))
    except OSError as exc:
        _fail("integrity", "cannot write --plan-out", path=os.fspath(path), reason=str(exc))
    return os.fspath(path)


def _exit_for(code: str) -> int:
    return {"usage": EXIT_USAGE, "malformed": EXIT_MALFORMED, "safety": EXIT_SAFETY, "conflict": EXIT_CONFLICT, "integrity": EXIT_INTEGRITY}.get(code, EXIT_INTEGRITY)


def _emit(value: Any) -> None:
    sys.stdout.buffer.write(_render_json(value))


def main(argv: Sequence[str] | None = None) -> int:
    command: str | None = None
    try:
        arguments = _parser().parse_args(argv)
        command = arguments.command
        repo = _absolute(Path(arguments.repo))
        if not repo.is_dir() or _is_link_or_junction(repo):
            _fail("safety", "--repo must be an existing real directory", path=os.fspath(repo))
        wrapper, context_relative = _load_context_argument(repo, arguments.context)
        if command == "verify":
            data = verify_repository(repo, wrapper, context_relative, arguments.now)
        elif command == "prepare":
            proposal = _read_external_json(arguments.proposal, "proposal")
            plan = prepare_plan(repo, wrapper, context_relative, proposal)
            data = {"plan": plan}
            if arguments.plan_out:
                data["plan_path"] = _write_plan_outside_repo(repo, arguments.plan_out, plan)
        elif command == "publish":
            plan = _read_external_json(arguments.plan, "plan")
            envelope = _read_external_json(arguments.envelope, "execution envelope")
            data = publish_plan(repo, wrapper, plan, envelope)
        else:
            data = recover_transaction(repo, wrapper)
        _emit({"schema_version": 1, "ok": True, "command": command, "data": data})
        return 0
    except ResourcePlanningError as exc:
        _emit({"schema_version": 1, "ok": False, "command": command, "error": {"code": exc.code, "message": exc.message, "details": exc.details}})
        return _exit_for(exc.code)
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError, TypeError) as exc:
        _emit({"schema_version": 1, "ok": False, "command": command, "error": {"code": "integrity", "message": "unexpected deterministic processing failure", "details": {"reason": str(exc)}}})
        return EXIT_INTEGRITY


if __name__ == "__main__":
    raise SystemExit(main())
