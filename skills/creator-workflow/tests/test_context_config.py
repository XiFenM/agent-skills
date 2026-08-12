from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "context_config.py"
SPEC = importlib.util.spec_from_file_location("creator_context_config", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
context_config = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(context_config)


def _repository() -> dict:
    return {
        "schema": "agent-skills.repository/v1",
        "repository_id": "creator-fixture",
        "language": "zh-CN",
        "timezone": "Asia/Shanghai",
        "facts": {
            "guidelines": {"path": "AGENTS.md"},
            "package": {"path": "package.json"},
            "project-template": {"path": "projects/_template"},
            "publication-contract": {"path": ".pathnote/contract-lock.json"},
            "publication-template": {"path": ".pathnote/templates/publication"},
        },
    }


def _config() -> dict:
    return {
        "schema": "agent-skills.creator-workflow/v1",
        "skill": "creator-workflow",
        "repository_fact_refs": [
            {"fact_id": "guidelines", "role": "repository-instructions", "kind": "file"},
            {"fact_id": "package", "role": "package-manifest", "kind": "file"},
            {"fact_id": "project-template", "role": "project-template", "kind": "collection"},
            {"fact_id": "publication-contract", "role": "publication-contract", "kind": "file"},
            {"fact_id": "publication-template", "role": "publication-template", "kind": "collection"},
        ],
        "storage": {
            "state_root": ".creator-workflow",
            "project_roots": [{"id": "managed-projects", "path": "projects/managed"}],
            "work_roots": [{"id": "managed-work", "path": "work/managed"}],
            "output_roots": [{"id": "managed-outputs", "path": "outputs/managed"}],
            "publication_roots": [{"id": "pathnote-publications", "path": "publications"}],
        },
        "routes": [
            {
                "id": "browser",
                "adapter": "selected-skill-v1",
                "skill": "playwright-cli",
                "effects": {
                    "billable": False,
                    "remote": True,
                    "destructive": False,
                    "publish": False,
                },
            },
            {
                "id": "workspace-check",
                "adapter": "package-script-v1",
                "manifest_fact_ref": "package",
                "script": "check",
                "subcommands": ["run"],
                "argument_keys": ["target-path"],
                "effects": {
                    "billable": False,
                    "remote": False,
                    "destructive": False,
                    "publish": False,
                },
            },
        ],
        "profiles": [
            {
                "id": "content-project",
                "adapter": "generic-content-project-v1",
                "project_root": "managed-projects",
                "work_root": "managed-work",
                "output_root": "managed-outputs",
                "template_fact_ref": "project-template",
                "routes": ["browser", "workspace-check"],
            },
            {
                "id": "pathnote-publication",
                "adapter": "pathnote-publication-v1",
                "publication_root": "pathnote-publications",
                "template_fact_ref": "publication-template",
                "contract_fact_ref": "publication-contract",
                "routes": ["browser", "workspace-check"],
            },
        ],
        "protected_roots": [
            ".pathnote",
            "projects/algorithm-interview-course",
            "work/algorithm-interview-course",
            "outputs/algorithm-interview-course",
            "publications/existing-draft",
        ],
    }


def test_canonical_context_and_allowlists() -> None:
    result = context_config.validate_materialized_context(_repository(), _config())
    assert set(result) == {
        "context",
        "tracked_files",
        "tracked_collections",
        "write_paths",
        "required_skills",
    }
    assert result["context"]["schema"] == "agent-skills.creator-workflow-context/v1"
    assert result["tracked_files"] == [
        ".pathnote/contract-lock.json",
        "AGENTS.md",
        "package.json",
    ]
    assert result["tracked_collections"] == [
        ".pathnote/templates/publication",
        "projects/_template",
    ]
    assert result["write_paths"] == [
        ".creator-workflow",
        "outputs/managed",
        "projects/managed",
        "publications",
        "work/managed",
    ]
    assert result["required_skills"] == ["playwright-cli"]
    routes = result["context"]["configuration"]["routes"]
    assert routes[0]["effects"] == {
        "billable": False,
        "remote": True,
        "destructive": False,
        "publish": False,
    }
    assert json.loads(json.dumps(result, ensure_ascii=False)) == result
    assert result == context_config.validate_materialized_context(_repository(), _config())


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("credentials", {"token": "secret"}),
        ("authorization", "yes"),
        ("job_id", "remote-1"),
        ("command", "rm -rf anything"),
        ("env", {"API_KEY": "secret"}),
    ],
)
def test_rejects_runtime_secret_and_authorization_fields(field: str, value: object) -> None:
    config = _config()
    config[field] = value
    with pytest.raises(context_config.ContextConfigError, match="unknown fields"):
        context_config.validate_materialized_context(_repository(), config)


def test_package_route_rejects_shell_and_undeclared_manifest() -> None:
    config = _config()
    route = config["routes"][1]
    route["script"] = "check && publish"
    with pytest.raises(context_config.ContextConfigError, match="safe package script"):
        context_config.validate_materialized_context(_repository(), config)

    config = _config()
    config["routes"][1]["manifest_fact_ref"] = "not-selected"
    with pytest.raises(context_config.ContextConfigError, match="undeclared manifest"):
        context_config.validate_materialized_context(_repository(), config)


@pytest.mark.parametrize("route_index", [0, 1])
def test_every_route_requires_exact_boolean_effects(route_index: int) -> None:
    config = _config()
    del config["routes"][route_index]["effects"]
    with pytest.raises(context_config.ContextConfigError, match="missing fields"):
        context_config.validate_materialized_context(_repository(), config)

    config = _config()
    config["routes"][route_index]["effects"]["credential"] = False
    with pytest.raises(context_config.ContextConfigError, match="unknown fields"):
        context_config.validate_materialized_context(_repository(), config)

    for field in ("billable", "remote", "destructive", "publish"):
        config = _config()
        config["routes"][route_index]["effects"][field] = 0
        with pytest.raises(context_config.ContextConfigError, match="must be boolean"):
            context_config.validate_materialized_context(_repository(), config)


def test_package_route_subcommands_are_finite_safe_and_unique() -> None:
    config = _config()
    config["routes"][1]["command"] = "check --all"
    with pytest.raises(context_config.ContextConfigError, match="unknown fields"):
        context_config.validate_materialized_context(_repository(), config)

    config = _config()
    config["routes"][1]["subcommands"] = ["run", "run"]
    with pytest.raises(context_config.ContextConfigError, match="duplicates"):
        context_config.validate_materialized_context(_repository(), config)

    config = _config()
    config["routes"][1]["subcommands"] = ["run --force"]
    with pytest.raises(context_config.ContextConfigError, match="lowercase hyphen"):
        context_config.validate_materialized_context(_repository(), config)


def _billable_package_route() -> dict:
    return {
        "id": "bounded-generate",
        "adapter": "package-script-v2",
        "manifest_fact_ref": "package",
        "script": "generate",
        "subcommands": ["image"],
        "argument_bindings": [
            {
                "key": "model",
                "kind": "value",
                "value_type": "string",
                "required": True,
                "cardinality": "one",
            },
            {
                "key": "count",
                "kind": "value",
                "value_type": "int",
                "required": True,
                "cardinality": "one",
            },
            {
                "key": "prompt-file",
                "kind": "input-path",
                "authority": "user-provided",
                "required": True,
                "cardinality": "one",
            },
            {
                "key": "out",
                "kind": "output-base",
                "required": True,
                "cardinality": "one",
            },
            {
                "key": "metadata",
                "kind": "value",
                "value_type": "bool",
                "required": False,
                "cardinality": "one",
            },
            {
                "key": "last-frame-out",
                "kind": "target-path",
                "required": False,
                "cardinality": "one",
            },
        ],
        "output_bindings": [
            {
                "id": "images",
                "kind": "indexed-by-count",
                "source_argument": "out",
                "count_argument": "count",
                "condition": {"kind": "always"},
            },
            {
                "id": "metadata-sidecar",
                "kind": "suffix",
                "source_argument": "out",
                "suffix": ".json",
                "condition": {
                    "kind": "argument-true",
                    "argument": "metadata",
                },
            },
        ],
        "billing_bindings": {
            "provider": {"kind": "literal", "value": "fixture-provider"},
            "model_or_tier": {"kind": "argument", "argument": "model"},
            "count": {"kind": "argument", "argument": "count"},
            "request_bounds": {
                "count": {"kind": "argument", "argument": "count"},
                "format": {"kind": "literal", "value": "png"},
            },
        },
        "effects": {
            "billable": True,
            "remote": True,
            "destructive": False,
            "publish": False,
        },
    }


def test_declarative_package_bindings_are_canonical_and_strict() -> None:
    config = _config()
    route = _billable_package_route()
    config["routes"].append(route)
    config["profiles"][0]["routes"].append("bounded-generate")
    result = context_config.validate_materialized_context(_repository(), config)
    materialized = next(
        item
        for item in result["context"]["configuration"]["routes"]
        if item["id"] == "bounded-generate"
    )
    assert [item["key"] for item in materialized["argument_bindings"]] == sorted(
        item["key"] for item in route["argument_bindings"]
    )
    assert [item["id"] for item in materialized["output_bindings"]] == [
        "images",
        "metadata-sidecar",
    ]
    assert list(materialized["billing_bindings"]["request_bounds"]) == [
        "count",
        "format",
    ]

    assert context_config.validate_materialized_context(_repository(), _config())

    old_shape = _config()
    package_route = old_shape["routes"][1]
    package_route["adapter"] = "package-script-v2"
    with pytest.raises(context_config.ContextConfigError, match="unknown fields"):
        context_config.validate_materialized_context(_repository(), old_shape)

    missing_billing = _config()
    billable = _billable_package_route()
    del billable["billing_bindings"]
    missing_billing["routes"].append(billable)
    with pytest.raises(context_config.ContextConfigError, match="missing fields"):
        context_config.validate_materialized_context(_repository(), missing_billing)

    unexpected_billing = _config()
    unexpected_billing["routes"][1]["billing_bindings"] = copy.deepcopy(
        _billable_package_route()["billing_bindings"]
    )
    with pytest.raises(context_config.ContextConfigError, match="unknown fields"):
        context_config.validate_materialized_context(_repository(), unexpected_billing)


def test_output_and_billing_bindings_reject_unrecomputable_shapes() -> None:
    config = _config()
    route = _billable_package_route()
    route["output_bindings"][0]["source_argument"] = "prompt-file"
    config["routes"].append(route)
    with pytest.raises(context_config.ContextConfigError, match="output-base"):
        context_config.validate_materialized_context(_repository(), config)

    config = _config()
    route = _billable_package_route()
    count = next(
        item for item in route["argument_bindings"] if item["key"] == "count"
    )
    count["required"] = False
    config["routes"].append(route)
    with pytest.raises(context_config.ContextConfigError, match="required scalar"):
        context_config.validate_materialized_context(_repository(), config)

    config = _config()
    route = _billable_package_route()
    route["output_bindings"][1]["suffix"] = "../metadata.json"
    config["routes"].append(route)
    with pytest.raises(context_config.ContextConfigError, match="filename suffix"):
        context_config.validate_materialized_context(_repository(), config)

    config = _config()
    route = _billable_package_route()
    route["output_bindings"] = []
    config["routes"].append(route)
    with pytest.raises(context_config.ContextConfigError, match="does not derive"):
        context_config.validate_materialized_context(_repository(), config)

    config = _config()
    route = _billable_package_route()
    route["billing_bindings"]["model_or_tier"] = {
        "kind": "argument",
        "argument": "prompt-file",
    }
    config["routes"].append(route)
    with pytest.raises(context_config.ContextConfigError, match="required scalar"):
        context_config.validate_materialized_context(_repository(), config)

    config = _config()
    config["routes"][1]["argument_keys"] = ["target-path", "target-path"]
    with pytest.raises(context_config.ContextConfigError, match="duplicates"):
        context_config.validate_materialized_context(_repository(), config)

    config = _config()
    config["routes"][1]["argument_keys"] = ["--api-key"]
    with pytest.raises(context_config.ContextConfigError, match="lowercase hyphen"):
        context_config.validate_materialized_context(_repository(), config)


def test_value_bindings_require_strict_types_and_constants() -> None:
    config = _config()
    route = _billable_package_route()
    model = next(
        item for item in route["argument_bindings"] if item["key"] == "model"
    )
    del model["value_type"]
    config["routes"].append(route)
    with pytest.raises(context_config.ContextConfigError, match="missing fields"):
        context_config.validate_materialized_context(_repository(), config)

    config = _config()
    route = _billable_package_route()
    metadata = next(
        item for item in route["argument_bindings"] if item["key"] == "metadata"
    )
    metadata["const"] = "true"
    config["routes"].append(route)
    with pytest.raises(context_config.ContextConfigError, match="exactly match"):
        context_config.validate_materialized_context(_repository(), config)

    config = _config()
    route = _billable_package_route()
    metadata = next(
        item for item in route["argument_bindings"] if item["key"] == "metadata"
    )
    metadata["const"] = True
    metadata["cardinality"] = "many"
    config["routes"].append(route)
    with pytest.raises(context_config.ContextConfigError, match="cardinality 'one'"):
        context_config.validate_materialized_context(_repository(), config)

    config = _config()
    route = _billable_package_route()
    route["output_bindings"][1]["condition"]["argument"] = "model"
    config["routes"].append(route)
    with pytest.raises(context_config.ContextConfigError, match="scalar value argument"):
        context_config.validate_materialized_context(_repository(), config)

    config = _config()
    route = _billable_package_route()
    route["billing_bindings"]["model_or_tier"]["argument"] = "count"
    config["routes"].append(route)
    with pytest.raises(context_config.ContextConfigError, match="value_type 'string'"):
        context_config.validate_materialized_context(_repository(), config)

    config = _config()
    route = _billable_package_route()
    route["billing_bindings"]["count"]["argument"] = "model"
    config["routes"].append(route)
    with pytest.raises(context_config.ContextConfigError, match="value_type 'int'"):
        context_config.validate_materialized_context(_repository(), config)


def _observation_package_route() -> dict:
    return {
        "id": "observe-job",
        "adapter": "package-script-v2",
        "manifest_fact_ref": "package",
        "script": "observe",
        "subcommands": ["status"],
        "argument_bindings": [
            {
                "key": "job-id",
                "kind": "value",
                "value_type": "string",
                "required": True,
                "cardinality": "one",
            }
        ],
        "output_bindings": [],
        "observation_receipt_argument": "job-id",
        "effects": {
            "billable": False,
            "remote": True,
            "destructive": False,
            "publish": False,
        },
    }


def test_observation_package_route_is_explicit_and_receipt_bound() -> None:
    config = _config()
    route = _observation_package_route()
    config["routes"].append(route)
    config["profiles"][0]["routes"].append("observe-job")
    result = context_config.validate_materialized_context(_repository(), config)
    materialized = next(
        item
        for item in result["context"]["configuration"]["routes"]
        if item["id"] == "observe-job"
    )
    assert materialized["observation_receipt_argument"] == "job-id"

    for mutate, message in (
        (lambda item: item["effects"].update({"remote": False}), "remote"),
        (
            lambda item: item["argument_bindings"][0].update({"required": False}),
            "required",
        ),
        (
            lambda item: item["argument_bindings"][0].update(
                {"value_type": "int"}
            ),
            "scalar string",
        ),
        (
            lambda item: item["argument_bindings"][0].update(
                {"const": "fixed-job"}
            ),
            "non-constant",
        ),
        (
            lambda item: item["argument_bindings"].append(
                {
                    "key": "out",
                    "kind": "target-path",
                    "required": False,
                    "cardinality": "one",
                }
            ),
            "must not declare outputs",
        ),
    ):
        invalid = _config()
        route = _observation_package_route()
        mutate(route)
        invalid["routes"].append(route)
        with pytest.raises(context_config.ContextConfigError, match=message):
            context_config.validate_materialized_context(_repository(), invalid)


def test_repository_fact_text_rejects_urls_and_credential_like_values() -> None:
    for description in (
        "Authorization: Bearer secret",
        "Authorization: audit-secret",
        "Read https://private.example/path?token=secret",
        "access_token=secret",
        "credential=abc",
        "secret: abc",
    ):
        repository = _repository()
        repository["facts"]["guidelines"]["description"] = description
        with pytest.raises(context_config.ContextConfigError, match="URL or credential"):
            context_config.validate_materialized_context(repository, _config())

    for field, value in (
        ("language", "Authorization: secret-value"),
        ("timezone", "https://private.example/?token=secret"),
    ):
        repository = _repository()
        repository[field] = value
        with pytest.raises(context_config.ContextConfigError, match="URL or credential"):
            context_config.validate_materialized_context(repository, _config())


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (
            lambda config: config["profiles"][0].update(
                {"template_fact_ref": "package"}
            ),
            "project-template",
        ),
        (
            lambda config: config["profiles"][1].update(
                {"template_fact_ref": "project-template"}
            ),
            "publication-template",
        ),
        (
            lambda config: config["profiles"][1].update(
                {"contract_fact_ref": "guidelines"}
            ),
            "publication-contract",
        ),
        (
            lambda config: config["routes"][1].update(
                {"manifest_fact_ref": "guidelines"}
            ),
            "package-manifest",
        ),
    ],
)
def test_profile_and_route_fact_uses_bind_role_and_kind(mutate, message: str) -> None:
    config = _config()
    mutate(config)
    with pytest.raises(context_config.ContextConfigError, match=message):
        context_config.validate_materialized_context(_repository(), config)


def test_collection_fact_must_not_declare_a_section() -> None:
    repository = _repository()
    repository["facts"]["project-template"]["section"] = "Template"
    with pytest.raises(context_config.ContextConfigError, match="must not declare a section"):
        context_config.validate_materialized_context(repository, _config())


def test_selected_skill_dependencies_are_non_recursive_unique_and_deterministic() -> None:
    config = _config()
    duplicate_capability_route = {
        "id": "browser-publish",
        "adapter": "selected-skill-v1",
        "skill": "playwright-cli",
        "effects": {
            "billable": False,
            "remote": True,
            "destructive": False,
            "publish": True,
        },
    }
    config["routes"].append(duplicate_capability_route)
    config["profiles"][1]["routes"].append("browser-publish")
    first = context_config.validate_materialized_context(_repository(), config)
    config["routes"].reverse()
    second = context_config.validate_materialized_context(_repository(), config)
    assert first == second
    assert first["required_skills"] == ["playwright-cli"]

    recursive = _config()
    recursive["routes"][0]["skill"] = "creator-workflow"
    with pytest.raises(context_config.ContextConfigError, match="recursively"):
        context_config.validate_materialized_context(_repository(), recursive)

    duplicate_id = _config()
    duplicate_id["routes"].append(copy.deepcopy(duplicate_id["routes"][0]))
    with pytest.raises(context_config.ContextConfigError, match="duplicate id"):
        context_config.validate_materialized_context(_repository(), duplicate_id)


@pytest.mark.parametrize(
    "unsafe",
    ["../outside", "C:/outside", "a\\b", "/absolute", "a/*", "NUL/work"],
)
def test_rejects_nonportable_paths(unsafe: str) -> None:
    config = _config()
    config["storage"]["project_roots"][0]["path"] = unsafe
    with pytest.raises(context_config.ContextConfigError):
        context_config.validate_materialized_context(_repository(), config)


def test_protected_child_is_allowed_but_ancestor_or_equal_is_rejected() -> None:
    context_config.validate_materialized_context(_repository(), _config())
    config = _config()
    config["protected_roots"] = ["publications"]
    with pytest.raises(context_config.ContextConfigError, match="strict descendant"):
        context_config.validate_materialized_context(_repository(), config)

    config = _config()
    config["protected_roots"] = ["projects"]
    with pytest.raises(context_config.ContextConfigError, match="strict descendant"):
        context_config.validate_materialized_context(_repository(), config)


def test_rejects_unused_or_overlapping_managed_roots() -> None:
    config = _config()
    config["storage"]["project_roots"].append({"id": "unused", "path": "projects/unused"})
    with pytest.raises(context_config.ContextConfigError, match="unused roots"):
        context_config.validate_materialized_context(_repository(), config)

    config = _config()
    config["storage"]["work_roots"][0]["path"] = "projects/managed/work"
    with pytest.raises(context_config.ContextConfigError, match="write roots must be disjoint"):
        context_config.validate_materialized_context(_repository(), config)


def test_does_not_mutate_inputs_or_access_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repository, config = _repository(), _config()
    before_repository, before_config = copy.deepcopy(repository), copy.deepcopy(config)
    monkeypatch.chdir(tmp_path)
    assert context_config.validate_materialized_context(repository, config)
    assert repository == before_repository
    assert config == before_config
    assert list(tmp_path.iterdir()) == []
