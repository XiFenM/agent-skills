from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "creator_workflow.py"
SPEC = importlib.util.spec_from_file_location("creator_workflow_runtime", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
runtime = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runtime)

TIME = "2026-08-12T12:00:00+08:00"
CONTEXT_DIGEST = "1" * 64


def _proposal(**updates: object) -> dict:
    value = {
        "schema": runtime.PROPOSAL_SCHEMA,
        "workflow_id": "launch-package",
        "operation_id": "generate-hero",
        "kind": "create",
        "profile_id": "content-project",
        "route_id": "zenmux",
        "summary": "Generate one bounded hero image candidate.",
        "inputs": [],
        "targets": [{"path": "outputs/managed/launch/hero.png", "before_sha256": runtime.ABSENT}],
        "dependencies": [],
        "parameters": {"count": 1, "width": 1600, "height": 900},
        "billable": True,
        "billing": {
            "provider": "zenmux",
            "model_or_tier": "image-standard",
            "count": 1,
            "request_bounds": {"width": 1600, "height": 900},
            "cost_boundary": {
                "kind": "estimate-only",
                "currency": "USD",
                "amount": "1.00",
            },
            "one_attempt_max": True,
        },
        "destructive": False,
        "remote": True,
    }
    value.update(updates)
    if value["billable"] is False and "billing" not in updates:
        value.pop("billing", None)
    return value


def _authorization(plan: dict, grants: list[str] | None = None) -> dict:
    return {
        "schema": runtime.AUTH_SCHEMA,
        "workflow_id": plan["workflow_id"],
        "operation_id": plan["operation_id"],
        "preview_digest": plan["preview_digest"],
        "grants": grants if grants is not None else list(plan["required_grants"]),
        "confirmed": True,
        "authorized_at": TIME,
    }


def _workflow(tmp_path: Path, plan: dict | None = None) -> tuple[Path, dict]:
    if plan is None:
        plan = runtime.prepare_operation(_proposal(), CONTEXT_DIGEST)
    state_root = tmp_path / ".creator-workflow"
    workflow = runtime.initialize_workflow(
        state_root, plan["workflow_id"], plan["profile_id"], CONTEXT_DIGEST
    )
    runtime.record_prepared(workflow, plan, "prepared-one", TIME)
    return workflow, plan


def test_prepare_is_deterministic_and_classifies_grants() -> None:
    first = runtime.prepare_operation(_proposal(), CONTEXT_DIGEST)
    second = runtime.prepare_operation(_proposal(), CONTEXT_DIGEST)
    assert first == second
    assert first["required_grants"] == ["billable"]
    assert runtime.validate_plan(first) == first

    missing_billing = _proposal()
    missing_billing.pop("billing")
    with pytest.raises(runtime.WorkflowError, match="provider, tier"):
        runtime.prepare_operation(missing_billing, CONTEXT_DIGEST)

    retry = runtime.prepare_operation(
        _proposal(
            operation_id="retry-hero",
            kind="publish",
            destructive=True,
            retry_of="generate-hero",
        ),
        CONTEXT_DIGEST,
    )
    assert retry["required_grants"] == ["billable", "destructive", "publish", "retry"]


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("count", 0, "count"),
        ("request_bounds", {}, "request_bounds"),
        ("one_attempt_max", False, "one_attempt_max"),
        (
            "cost_boundary",
            {"kind": "estimate-only", "currency": "USD", "amount": "0"},
            "positive",
        ),
    ],
)
def test_billable_request_envelope_is_bounded(
    field: str, value: object, message: str
) -> None:
    proposal = _proposal()
    proposal["billing"][field] = value
    with pytest.raises(runtime.WorkflowError, match=message):
        runtime.prepare_operation(proposal, CONTEXT_DIGEST)


def test_plan_tamper_and_sensitive_payload_are_rejected() -> None:
    plan = runtime.prepare_operation(_proposal(), CONTEXT_DIGEST)
    plan["parameters"]["count"] = 2
    with pytest.raises(runtime.WorkflowError, match="digest"):
        runtime.validate_plan(plan)

    with pytest.raises(runtime.WorkflowError, match="sensitive"):
        runtime.prepare_operation(_proposal(parameters={"api_key": "secret"}), CONTEXT_DIGEST)
    with pytest.raises(runtime.WorkflowError, match="encoded payload"):
        runtime.prepare_operation(_proposal(parameters={"image": "A" * 300}), CONTEXT_DIGEST)
    for parameters in (
        {"headers": {"Authorization": "Bearer secret"}},
        {"access_token": "secret"},
        {"credential": "secret"},
        {"reference": "https://example.invalid/file?token=secret"},
        {"arguments": ["--api-key=secret"]},
        {"arguments": ["--header=Authorization: Bearer secret"]},
    ):
        with pytest.raises(runtime.WorkflowError, match="sensitive|credential"):
            runtime.prepare_operation(_proposal(parameters=parameters), CONTEXT_DIGEST)
    for credential in (
        "sk-proj-" + "A" * 48,
        "ghp_" + "B" * 36,
        "github_pat_" + "C" * 60,
        "AKIA" + "C" * 16,
        "ya29." + "D" * 48,
        "eyJheaderabc.eyJpayloadabc.signaturevalue123456",
    ):
        with pytest.raises(runtime.WorkflowError, match="sensitive|secret|encoded"):
            runtime._opaque_receipt(credential, "remote_receipt")
    with pytest.raises(runtime.WorkflowError, match="canonical JSON"):
        runtime.prepare_operation(_proposal(parameters={"count": float("nan")}), CONTEXT_DIGEST)


@pytest.mark.parametrize(
    "path",
    ["outputs/*.png", "outputs/bad:name.png", "outputs/CON.txt", "outputs/trailing. /x"],
)
def test_plan_rejects_nonportable_target_paths(path: str) -> None:
    with pytest.raises(runtime.WorkflowError, match="portable|Windows-unsafe"):
        runtime.prepare_operation(
            _proposal(targets=[{"path": path, "before_sha256": runtime.ABSENT}]),
            CONTEXT_DIGEST,
        )


def test_plan_rejects_overlapping_targets_and_ungranted_overwrite() -> None:
    with pytest.raises(runtime.WorkflowError, match="overlapping targets"):
        runtime.prepare_operation(
            _proposal(
                targets=[
                    {"path": "outputs/managed/item", "before_sha256": runtime.ABSENT},
                    {"path": "outputs/managed/item/file.md", "before_sha256": runtime.ABSENT},
                ]
            ),
            CONTEXT_DIGEST,
        )
    with pytest.raises(runtime.WorkflowError, match="destructive"):
        runtime.prepare_operation(
            _proposal(
                billable=False,
                remote=False,
                targets=[{"path": "outputs/managed/item.md", "before_sha256": "2" * 64}],
            ),
            CONTEXT_DIGEST,
        )


def test_billable_operation_requires_exact_authorization_and_dispatching_first(tmp_path: Path) -> None:
    workflow, plan = _workflow(tmp_path)
    with pytest.raises(runtime.WorkflowError, match="requires authorization"):
        runtime.append_state(
            workflow,
            operation_id=plan["operation_id"],
            state="dispatching",
            event_type="remote-dispatching",
            payload={},
            event_id="dispatch-one",
            occurred_at=TIME,
            repo=tmp_path,
        )

    bad = _authorization(plan, [])
    with pytest.raises(runtime.WorkflowError, match="exactly match"):
        runtime.append_state(
            workflow,
            operation_id=plan["operation_id"],
            state="authorized",
            event_type="operation-authorized",
            payload={"authorization": bad},
            event_id="authorized-one",
            occurred_at=TIME,
        )

    extra = _authorization(plan, ["billable", "retry"])
    with pytest.raises(runtime.WorkflowError, match="exactly match"):
        runtime.append_state(
            workflow,
            operation_id=plan["operation_id"],
            state="authorized",
            event_type="operation-authorized",
            payload={"authorization": extra},
            event_id="authorized-extra",
            occurred_at=TIME,
        )

    runtime.append_state(
        workflow,
        operation_id=plan["operation_id"],
        state="authorized",
        event_type="operation-authorized",
        payload={"authorization": _authorization(plan)},
        event_id="authorized-two",
        occurred_at=TIME,
    )
    runtime.append_state(
        workflow,
        operation_id=plan["operation_id"],
        state="dispatching",
        event_type="remote-dispatching",
        payload={},
        event_id="dispatch-two",
        occurred_at=TIME,
        repo=tmp_path,
    )
    assert runtime.verify_workflow(workflow)["snapshot"]["operations"][plan["operation_id"]]["state"] == "dispatching"


def test_non_authorized_event_cannot_hide_credentials_in_fake_envelope(
    tmp_path: Path,
) -> None:
    plan = runtime.prepare_operation(
        _proposal(billable=False, remote=False, targets=[]), CONTEXT_DIGEST
    )
    workflow, _ = _workflow(tmp_path, plan)
    fake = {
        "schema": runtime.AUTH_SCHEMA,
        "workflow_id": plan["workflow_id"],
        "operation_id": plan["operation_id"],
        "preview_digest": plan["preview_digest"],
        "grants": [],
        "confirmed": True,
        "authorized_at": TIME,
        "token": "secret",
    }
    with pytest.raises(runtime.WorkflowError, match="sensitive"):
        runtime.append_state(
            workflow,
            operation_id=plan["operation_id"],
            state="running",
            event_type="operation-running",
            payload={"authorization": fake},
            event_id="running-fake-auth",
            occurred_at=TIME,
            repo=tmp_path,
        )


def test_dependency_and_target_cas_stop_execution(tmp_path: Path) -> None:
    source = tmp_path / "input.md"
    source.write_text("before", encoding="utf-8")
    proposal = _proposal(
        billable=False,
        remote=False,
        inputs=[{"path": "input.md", "sha256": runtime._sha(source.read_bytes()), "authority": "user-provided"}],
        targets=[],
    )
    plan = runtime.prepare_operation(proposal, CONTEXT_DIGEST)
    workflow, plan = _workflow(tmp_path, plan)
    source.write_text("after", encoding="utf-8")
    with pytest.raises(runtime.WorkflowError, match="input digest changed"):
        runtime.append_state(
            workflow,
            operation_id=plan["operation_id"],
            state="running",
            event_type="operation-running",
            payload={},
            event_id="running-one",
            occurred_at=TIME,
            repo=tmp_path,
        )
    assert runtime.verify_workflow(workflow)["snapshot"]["operations"][plan["operation_id"]]["state"] == "prepared"


def test_unknown_remote_outcome_is_terminal_and_retry_is_new_operation(tmp_path: Path) -> None:
    workflow, plan = _workflow(tmp_path)
    runtime.append_state(workflow, operation_id=plan["operation_id"], state="authorized", event_type="operation-authorized", payload={"authorization": _authorization(plan)}, event_id="authorized-one", occurred_at=TIME)
    runtime.append_state(workflow, operation_id=plan["operation_id"], state="dispatching", event_type="remote-dispatching", payload={}, event_id="dispatch-one", occurred_at=TIME, repo=tmp_path)
    runtime.append_state(workflow, operation_id=plan["operation_id"], state="unknown", event_type="remote-outcome-unknown", payload={"remote_receipt": "opaque-job-1"}, event_id="unknown-one", occurred_at=TIME)
    with pytest.raises(runtime.WorkflowError, match="invalid operation transition"):
        runtime.append_state(workflow, operation_id=plan["operation_id"], state="dispatching", event_type="remote-dispatching", payload={}, event_id="dispatch-again", occurred_at=TIME, repo=tmp_path)

    retry_plan = runtime.prepare_operation(
        _proposal(operation_id="retry-hero", retry_of=plan["operation_id"]), CONTEXT_DIGEST
    )
    runtime.record_prepared(workflow, retry_plan, "prepared-retry", TIME)
    snapshot = runtime.verify_workflow(workflow)["snapshot"]
    assert snapshot["operations"][plan["operation_id"]]["state"] == "unknown"
    assert snapshot["operations"]["retry-hero"]["state"] == "prepared"
    assert "retry" in retry_plan["required_grants"]

    observation = runtime.prepare_operation(
        _proposal(
            operation_id="observe-hero",
            kind="verify",
            billable=False,
            destructive=False,
            remote=True,
            targets=[],
            dependencies=[],
            parameters={"action": "query-existing-job"},
            observation_of=plan["operation_id"],
            observed_receipt="opaque-job-1",
        ),
        CONTEXT_DIGEST,
    )
    runtime.record_prepared(workflow, observation, "prepared-observation", TIME)
    assert observation["required_grants"] == []
    assert observation["observation_of"] == plan["operation_id"]

    wrong_receipt = runtime.prepare_operation(
        _proposal(
            operation_id="observe-wrong-job",
            kind="verify",
            billable=False,
            destructive=False,
            remote=True,
            targets=[],
            dependencies=[],
            parameters={"action": "query-existing-job"},
            observation_of=plan["operation_id"],
            observed_receipt="different-job",
        ),
        CONTEXT_DIGEST,
    )
    with pytest.raises(runtime.WorkflowError, match="immutable receipt"):
        runtime.record_prepared(workflow, wrong_receipt, "prepared-wrong-observation", TIME)


def test_observation_plan_shape_is_strict() -> None:
    base = {
        "operation_id": "observe-hero",
        "kind": "verify",
        "billable": False,
        "destructive": False,
        "remote": True,
        "targets": [],
        "dependencies": [],
        "observation_of": "generate-hero",
        "observed_receipt": "opaque-job-1",
    }
    for update in (
        {"observed_receipt": None},
        {"retry_of": "generate-hero"},
        {"kind": "create"},
        {"remote": False},
        {"billable": True},
        {"destructive": True},
        {"dependencies": ["generate-hero"]},
        {"targets": [{"path": "outputs/managed/observation.md", "before_sha256": runtime.ABSENT}]},
    ):
        proposal = _proposal(**{**base, **update})
        if proposal["billable"] is True and "billing" not in proposal:
            proposal["billing"] = _proposal()["billing"]
        with pytest.raises(runtime.WorkflowError, match="observation|trimmed string"):
            runtime.prepare_operation(proposal, CONTEXT_DIGEST)


def test_remote_work_cannot_skip_dispatching_and_receipt_is_immutable(tmp_path: Path) -> None:
    workflow, plan = _workflow(tmp_path)
    runtime.append_state(workflow, operation_id=plan["operation_id"], state="authorized", event_type="operation-authorized", payload={"authorization": _authorization(plan)}, event_id="authorized-one", occurred_at=TIME)
    runtime.append_state(workflow, operation_id=plan["operation_id"], state="running", event_type="operation-running", payload={}, event_id="running-one", occurred_at=TIME, repo=tmp_path)
    with pytest.raises(runtime.WorkflowError, match="persist dispatching"):
        runtime.append_state(workflow, operation_id=plan["operation_id"], state="succeeded", event_type="operation-succeeded", payload={"remote_receipt": "job-a"}, event_id="succeeded-too-soon", occurred_at=TIME)

    other, other_plan = _workflow(tmp_path / "other")
    runtime.append_state(other, operation_id=other_plan["operation_id"], state="authorized", event_type="operation-authorized", payload={"authorization": _authorization(other_plan)}, event_id="authorized-two", occurred_at=TIME)
    runtime.append_state(other, operation_id=other_plan["operation_id"], state="dispatching", event_type="remote-dispatching", payload={}, event_id="dispatch-two", occurred_at=TIME, repo=tmp_path / "other")
    with pytest.raises(runtime.WorkflowError, match="must record an opaque receipt"):
        runtime.append_state(other, operation_id=other_plan["operation_id"], state="submitted", event_type="remote-submitted", payload={}, event_id="submitted-missing", occurred_at=TIME)
    runtime.append_state(other, operation_id=other_plan["operation_id"], state="submitted", event_type="remote-submitted", payload={"remote_receipt": "job-a"}, event_id="submitted-two", occurred_at=TIME)
    with pytest.raises(runtime.WorkflowError, match="immutable"):
        runtime.append_state(other, operation_id=other_plan["operation_id"], state="waiting", event_type="remote-waiting", payload={"remote_receipt": "job-b"}, event_id="waiting-bad", occurred_at=TIME)
    runtime.append_state(other, operation_id=other_plan["operation_id"], state="waiting", event_type="remote-waiting", payload={}, event_id="waiting-good", occurred_at=TIME)
    runtime.append_state(other, operation_id=other_plan["operation_id"], state="succeeded", event_type="operation-succeeded", payload={}, event_id="succeeded-good", occurred_at=TIME)
    operation = runtime.verify_workflow(other)["snapshot"]["operations"][other_plan["operation_id"]]
    assert operation["remote_receipt"] == "job-a"

    synchronous, sync_plan = _workflow(tmp_path / "sync")
    runtime.append_state(synchronous, operation_id=sync_plan["operation_id"], state="authorized", event_type="operation-authorized", payload={"authorization": _authorization(sync_plan)}, event_id="authorized-sync", occurred_at=TIME)
    runtime.append_state(synchronous, operation_id=sync_plan["operation_id"], state="dispatching", event_type="remote-dispatching", payload={}, event_id="dispatch-sync", occurred_at=TIME, repo=tmp_path / "sync")
    runtime.append_state(synchronous, operation_id=sync_plan["operation_id"], state="succeeded", event_type="operation-succeeded", payload={"remote_receipt": "request-42"}, event_id="succeeded-sync", occurred_at=TIME)
    assert runtime.verify_workflow(synchronous)["snapshot"]["operations"][sync_plan["operation_id"]]["remote_receipt"] == "request-42"


def test_operation_dependencies_must_succeed_before_execution(tmp_path: Path) -> None:
    parent = runtime.prepare_operation(
        _proposal(operation_id="parent", billable=False, remote=False, targets=[]),
        CONTEXT_DIGEST,
    )
    child = runtime.prepare_operation(
        _proposal(operation_id="child", billable=False, remote=False, targets=[], dependencies=["parent"]),
        CONTEXT_DIGEST,
    )
    workflow, _ = _workflow(tmp_path, parent)
    runtime.record_prepared(workflow, child, "prepared-child", TIME)
    with pytest.raises(runtime.WorkflowError, match="dependencies must succeed"):
        runtime.append_state(workflow, operation_id="child", state="running", event_type="operation-running", payload={}, event_id="child-too-soon", occurred_at=TIME, repo=tmp_path)
    runtime.append_state(workflow, operation_id="parent", state="running", event_type="operation-running", payload={}, event_id="parent-running", occurred_at=TIME, repo=tmp_path)
    runtime.append_state(workflow, operation_id="parent", state="succeeded", event_type="operation-succeeded", payload={}, event_id="parent-succeeded", occurred_at=TIME)
    runtime.append_state(workflow, operation_id="child", state="running", event_type="operation-running", payload={}, event_id="child-running", occurred_at=TIME, repo=tmp_path)

    dangling = runtime.prepare_operation(
        _proposal(operation_id="dangling", billable=False, remote=False, targets=[], dependencies=["not-declared"]),
        CONTEXT_DIGEST,
    )
    with pytest.raises(runtime.WorkflowError, match="declared earlier"):
        runtime.record_prepared(workflow, dangling, "prepared-dangling", TIME)

    with pytest.raises(runtime.WorkflowError, match="depend on itself"):
        runtime.prepare_operation(
            _proposal(operation_id="self", dependencies=["self"]),
            CONTEXT_DIGEST,
        )


def test_event_chain_and_snapshot_tamper_are_detected(tmp_path: Path) -> None:
    workflow, _plan = _workflow(tmp_path)
    event_path = workflow / "events.jsonl"
    events = event_path.read_bytes()
    event_path.write_bytes(events.replace(b"Generate one", b"Generate two"))
    with pytest.raises(runtime.WorkflowError, match="hash"):
        runtime.verify_workflow(workflow)

    workflow2, _plan2 = _workflow(tmp_path / "other")
    snapshot = json.loads((workflow2 / "snapshot.json").read_text(encoding="ascii"))
    snapshot["event_count"] = 999
    (workflow2 / "snapshot.json").write_text(json.dumps(snapshot), encoding="ascii")
    with pytest.raises(runtime.WorkflowError, match="snapshot"):
        runtime.verify_workflow(workflow2)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("sequence", True, "sequence"),
        ("occurred_at", {"bad": True}, "occurred_at"),
        ("event_type", ["bad"], "event_type"),
    ],
)
def test_reducer_revalidates_event_identity_fields(
    tmp_path: Path, field: str, value: object, message: str
) -> None:
    workflow, _plan = _workflow(tmp_path)
    events = runtime._parse_events((workflow / "events.jsonl").read_bytes())
    events[0][field] = value
    unsigned = {key: item for key, item in events[0].items() if key != "event_hash"}
    events[0]["event_hash"] = runtime._digest_value(unsigned)
    with pytest.raises(runtime.WorkflowError, match=message):
        runtime.reduce_events(events)


def test_recovery_rolls_back_before_after_mix_and_completes_all_after(tmp_path: Path) -> None:
    workflow, plan = _workflow(tmp_path)
    events_path, snapshot_path = workflow / "events.jsonl", workflow / "snapshot.json"
    before_events, before_snapshot = events_path.read_bytes(), snapshot_path.read_bytes()
    candidate_events = [
        *runtime._parse_events(before_events),
        runtime._new_event(runtime._parse_events(before_events), plan["operation_id"], "operation-authorized", "authorized", {"authorization": _authorization(plan)}, "authorized-one", TIME),
    ]
    after_events = runtime._events_bytes(candidate_events)
    after_snapshot = runtime._canonical(runtime.reduce_events(candidate_events))
    journal = {
        "schema": runtime.JOURNAL_SCHEMA,
        "targets": [
            {"path": "events.jsonl", "before": runtime._encode(before_events), "after": runtime._encode(after_events), "before_sha256": runtime._sha(before_events), "after_sha256": runtime._sha(after_events)},
            {"path": "snapshot.json", "before": runtime._encode(before_snapshot), "after": runtime._encode(after_snapshot), "before_sha256": runtime._sha(before_snapshot), "after_sha256": runtime._sha(after_snapshot)},
        ],
    }
    journal_path = workflow / "transaction" / "journal.json"
    runtime._replace(journal_path, runtime._canonical(journal))
    runtime._replace(events_path, after_events)
    assert runtime.recover(workflow) == "rolled-back"
    assert events_path.read_bytes() == before_events
    assert snapshot_path.read_bytes() == before_snapshot

    runtime._replace(journal_path, runtime._canonical(journal))
    runtime._replace(events_path, after_events)
    runtime._replace(snapshot_path, after_snapshot)
    assert runtime.recover(workflow) == "completed"
    assert runtime.verify_workflow(workflow)["snapshot"]["operations"][plan["operation_id"]]["state"] == "authorized"


def test_recovery_refuses_third_state(tmp_path: Path) -> None:
    workflow, plan = _workflow(tmp_path)
    events = (workflow / "events.jsonl").read_bytes()
    snapshot = (workflow / "snapshot.json").read_bytes()
    candidate_events = [
        *runtime._parse_events(events),
        runtime._new_event(
            runtime._parse_events(events),
            plan["operation_id"],
            "operation-authorized",
            "authorized",
            {"authorization": _authorization(plan)},
            "authorized-third-state",
            TIME,
        ),
    ]
    after_events = runtime._events_bytes(candidate_events)
    after_snapshot = runtime._canonical(runtime.reduce_events(candidate_events))
    journal = {
        "schema": runtime.JOURNAL_SCHEMA,
        "targets": [
            {"path": "events.jsonl", "before": runtime._encode(events), "after": runtime._encode(after_events), "before_sha256": runtime._sha(events), "after_sha256": runtime._sha(after_events)},
            {"path": "snapshot.json", "before": runtime._encode(snapshot), "after": runtime._encode(after_snapshot), "before_sha256": runtime._sha(snapshot), "after_sha256": runtime._sha(after_snapshot)},
        ],
    }
    runtime._replace(workflow / "transaction" / "journal.json", runtime._canonical(journal))
    (workflow / "events.jsonl").write_bytes(b"third")
    with pytest.raises(runtime.WorkflowError, match="third state"):
        runtime.recover(workflow)


def test_recovery_honors_existing_lock(tmp_path: Path) -> None:
    workflow, _plan = _workflow(tmp_path)
    lock = workflow / ".creator-workflow.lock"
    lock.write_text("held", encoding="utf-8")
    with pytest.raises(runtime.WorkflowError, match="locked"):
        runtime.recover(workflow)
    assert lock.read_text(encoding="utf-8") == "held"


def test_stale_lock_break_requires_dead_owner_exact_digest_and_confirmation(
    tmp_path: Path,
) -> None:
    workflow, _plan = _workflow(tmp_path)
    lock = workflow / ".creator-workflow.lock"
    active = runtime._canonical(
        {
            "schema": runtime.LOCK_SCHEMA,
            "pid": runtime.os.getpid(),
            "token": "a" * 48,
            "created_at": TIME,
        }
    )
    lock.write_bytes(active)
    with pytest.raises(runtime.WorkflowError, match="still active"):
        runtime._break_stale_lock(workflow, runtime._sha(active), True)
    assert lock.read_bytes() == active

    stale = runtime._canonical(
        {
            "schema": runtime.LOCK_SCHEMA,
            "pid": 2_147_483_647,
            "token": "b" * 48,
            "created_at": TIME,
        }
    )
    lock.write_bytes(stale)
    with pytest.raises(runtime.WorkflowError, match="digest changed"):
        runtime._break_stale_lock(workflow, "0" * 64, True)
    with pytest.raises(runtime.WorkflowError, match="requires confirmation"):
        runtime._break_stale_lock(workflow, runtime._sha(stale), False)
    assert lock.read_bytes() == stale
    assert runtime._break_stale_lock(workflow, runtime._sha(stale), True) == runtime._sha(stale)
    assert not lock.exists()
    assert runtime.recover(workflow) == "clean"


@pytest.mark.parametrize(
    "raw",
    [
        b'{"schema":"agent-skills.creator-lock/v1","pid":2147483647,"pid":2147483647,"token":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb","created_at":"2026-08-12T12:00:00+08:00"}\n',
        runtime._canonical(
            {
                "schema": runtime.LOCK_SCHEMA,
                "pid": 0x1_0000_0000,
                "token": "b" * 48,
                "created_at": TIME,
            }
        ),
        runtime._canonical(
            {
                "schema": runtime.LOCK_SCHEMA,
                "pid": 2_147_483_647,
                "token": "b" * 48,
                "created_at": "2999-01-01T00:00:00+00:00",
            }
        ),
    ],
)
def test_stale_lock_break_rejects_noncanonical_or_impossible_records(
    tmp_path: Path, raw: bytes
) -> None:
    workflow, _plan = _workflow(tmp_path)
    lock = workflow / ".creator-workflow.lock"
    lock.write_bytes(raw)
    with pytest.raises(runtime.WorkflowError, match="canonical|pid|future"):
        runtime._break_stale_lock(workflow, runtime._sha(raw), True)
    assert lock.read_bytes() == raw


def test_recovery_keeps_invalid_all_after_journal(tmp_path: Path) -> None:
    workflow, _plan = _workflow(tmp_path)
    events_path, snapshot_path = workflow / "events.jsonl", workflow / "snapshot.json"
    events, snapshot = events_path.read_bytes(), snapshot_path.read_bytes()
    invalid_snapshot = runtime._canonical({"schema": runtime.SNAPSHOT_SCHEMA, "invalid": True})
    journal = {
        "schema": runtime.JOURNAL_SCHEMA,
        "targets": [
            {"path": "events.jsonl", "before": runtime._encode(events), "after": runtime._encode(events), "before_sha256": runtime._sha(events), "after_sha256": runtime._sha(events)},
            {"path": "snapshot.json", "before": runtime._encode(snapshot), "after": runtime._encode(invalid_snapshot), "before_sha256": runtime._sha(snapshot), "after_sha256": runtime._sha(invalid_snapshot)},
        ],
    }
    journal_path = workflow / "transaction" / "journal.json"
    runtime._replace(journal_path, runtime._canonical(journal))
    runtime._replace(snapshot_path, invalid_snapshot)
    with pytest.raises(runtime.WorkflowError, match="invalid snapshot projection"):
        runtime.recover(workflow)
    assert journal_path.is_file()


def test_recovery_rejects_duplicate_or_reordered_journal_targets(tmp_path: Path) -> None:
    workflow, _plan = _workflow(tmp_path)
    events = (workflow / "events.jsonl").read_bytes()
    record = {"path": "events.jsonl", "before": runtime._encode(events), "after": runtime._encode(events), "before_sha256": runtime._sha(events), "after_sha256": runtime._sha(events)}
    runtime._replace(
        workflow / "transaction" / "journal.json",
        runtime._canonical({"schema": runtime.JOURNAL_SCHEMA, "targets": [record, record]}),
    )
    with pytest.raises(runtime.WorkflowError, match="exact ordered ledger pair"):
        runtime.recover(workflow)


def test_runtime_contains_no_provider_or_process_execution_surface() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    for forbidden in ("import socket", "import subprocess", "requests.", "urllib.request", "os.system", "shell=True"):
        assert forbidden not in source


def _managed_fixture(tmp_path: Path) -> tuple[dict, Path]:
    repository = {
        "schema": "agent-skills.repository/v1",
        "repository_id": "managed-fixture",
        "facts": {
            "guidelines": {"path": "AGENTS.md"},
            "package": {"path": "package.json"},
            "template": {"path": "projects/_template"},
        },
    }
    config = {
        "schema": "agent-skills.creator-workflow/v1",
        "skill": "creator-workflow",
        "repository_fact_refs": [
            {"fact_id": "guidelines", "role": "repository-instructions", "kind": "file"},
            {"fact_id": "package", "role": "package-manifest", "kind": "file"},
            {"fact_id": "template", "role": "project-template", "kind": "collection"},
        ],
        "storage": {
            "state_root": ".creator-workflow",
            "project_roots": [{"id": "projects", "path": "projects/managed"}],
            "work_roots": [{"id": "work", "path": "work/managed"}],
            "output_roots": [{"id": "outputs", "path": "outputs/managed"}],
            "publication_roots": [],
        },
        "routes": [
            {
                "id": "browser",
                "adapter": "selected-skill-v1",
                "skill": "playwright-cli",
                "effects": {
                    "billable": False,
                    "remote": False,
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
                "project_root": "projects",
                "work_root": "work",
                "output_root": "outputs",
                "template_fact_ref": "template",
                "routes": ["browser", "workspace-check"],
            }
        ],
        "protected_roots": [".creator-workflow/blocked", "projects/managed/frozen"],
    }
    (tmp_path / "projects" / "_template").mkdir(parents=True)
    (tmp_path / "projects" / "_template" / "brief.md").write_text("brief", encoding="utf-8")
    (tmp_path / "AGENTS.md").write_text("rules", encoding="utf-8")
    (tmp_path / "package.json").write_text("{}", encoding="utf-8")
    config_dir = tmp_path / ".agent-skills-config"
    config_dir.mkdir()
    repository_path, skill_path = config_dir / "repository.json", config_dir / "creator-workflow.json"
    repository_path.write_text(json.dumps(repository), encoding="utf-8")
    skill_path.write_text(json.dumps(config), encoding="utf-8")
    validated = runtime._CONTEXT_MODULE.validate_materialized_context(repository, config)
    wrapper = {
        "version": 1,
        "manager": "agent-skills",
        "skill": "creator-workflow",
        "repository_id": "managed-fixture",
        "sources": {
            "repository": {"path": ".agent-skills-config/repository.json", "digest": runtime._sha(repository_path.read_bytes())},
            "skill": {"path": ".agent-skills-config/creator-workflow.json", "digest": runtime._sha(skill_path.read_bytes())},
        },
        "context": validated["context"],
        "allowlist": {
            "tracked_files": ["AGENTS.md", "package.json", "projects/_template/brief.md"],
            "tracked_collections": validated["tracked_collections"],
            "write_paths": validated["write_paths"],
        },
    }
    target_root = tmp_path / ".agents" / "skills" / "creator-workflow"
    target_root.mkdir(parents=True)
    (target_root / "SKILL.md").write_text("# Creator workflow\n", encoding="utf-8")
    context_path = target_root / ".agent-skills-context.json"
    context_path.write_text(json.dumps(wrapper), encoding="utf-8")
    context_digest = runtime._sha(context_path.read_bytes())
    record = {
        "skill": "creator-workflow",
        "host": "codex",
        "source": "skills/creator-workflow",
        "digest": runtime._managed_skill_digest(target_root),
        "source_digest": "3" * 64,
        "context_digest": context_digest,
    }
    (target_root / ".agent-skills-managed.json").write_text(
        json.dumps({"version": 1, "manager": "agent-skills", **record}),
        encoding="utf-8",
    )
    support_record = {
        "skill": "playwright-cli",
        "host": "codex",
        "source": "vendor/microsoft-playwright-cli/skills/playwright-cli",
        "digest": "4" * 64,
        "source_digest": "5" * 64,
        "context_digest": None,
    }
    support_root = tmp_path / ".agents" / "skills" / "playwright-cli"
    support_root.mkdir(parents=True)
    (support_root / "SKILL.md").write_text("# Playwright CLI\n", encoding="utf-8")
    support_record["digest"] = runtime._managed_skill_digest(support_root)
    (support_root / ".agent-skills-managed.json").write_text(
        json.dumps({"version": 1, "manager": "agent-skills", **support_record}),
        encoding="utf-8",
    )
    (tmp_path / ".agent-skills.state.json").write_text(
        json.dumps(
            {
                "version": 1,
                "manager": "agent-skills",
                "managed": {
                    ".agents/skills/creator-workflow": record,
                    ".agents/skills/playwright-cli": support_record,
                },
            }
        ),
        encoding="utf-8",
    )
    return runtime.load_managed_context(tmp_path, context_path), context_path


def test_managed_prepare_enforces_profile_route_write_and_protected_roots(tmp_path: Path) -> None:
    wrapper, _context_path = _managed_fixture(tmp_path)
    proposal = _proposal(
        route_id="browser",
        billable=False,
        remote=False,
        targets=[{"path": "outputs/managed/demo/hero.png", "before_sha256": runtime.ABSENT}],
    )
    plan = runtime.prepare_managed_operation(tmp_path, wrapper, proposal)
    assert plan["context_digest"] == runtime.managed_context_digest(wrapper)

    outside = _proposal(route_id="browser", billable=False, remote=False, targets=[{"path": "outputs/outside.png", "before_sha256": runtime.ABSENT}])
    with pytest.raises(runtime.WorkflowError, match="outside its profile"):
        runtime.prepare_managed_operation(tmp_path, wrapper, outside)

    protected = _proposal(route_id="browser", billable=False, remote=False, targets=[{"path": "projects/managed/frozen/file.md", "before_sha256": runtime.ABSENT}])
    with pytest.raises(runtime.WorkflowError, match="protected"):
        runtime.prepare_managed_operation(tmp_path, wrapper, protected)

    effect_mismatch = _proposal(route_id="browser", billable=False, remote=True, targets=[])
    with pytest.raises(runtime.WorkflowError, match="effects"):
        runtime.prepare_managed_operation(tmp_path, wrapper, effect_mismatch)

    invalid_subcommand = _proposal(
        route_id="workspace-check",
        billable=False,
        remote=False,
        targets=[],
        parameters={"subcommand": "unsafe", "arguments": {}},
    )
    with pytest.raises(runtime.WorkflowError, match="subcommand"):
        runtime.prepare_managed_operation(tmp_path, wrapper, invalid_subcommand)
    injected_command = _proposal(
        route_id="workspace-check",
        billable=False,
        remote=False,
        targets=[],
        parameters={"subcommand": "run", "arguments": {}, "command": "Remove-Item everything"},
    )
    with pytest.raises(runtime.WorkflowError, match="unknown fields"):
        runtime.prepare_managed_operation(tmp_path, wrapper, injected_command)
    valid_arguments = _proposal(
        route_id="workspace-check",
        billable=False,
        remote=False,
        inputs=[{
            "path": "package.json",
            "sha256": runtime._sha((tmp_path / "package.json").read_bytes()),
            "authority": "managed-fact",
        }],
        targets=[],
        parameters={"subcommand": "run", "arguments": {"target-path": "outputs/managed/demo"}},
    )
    assert runtime.prepare_managed_operation(tmp_path, wrapper, valid_arguments)["parameters"]["arguments"]["target-path"] == "outputs/managed/demo"
    plan = runtime.prepare_managed_operation(tmp_path, wrapper, valid_arguments)
    (tmp_path / "package.json").write_text('{"changed":true}', encoding="utf-8")
    with pytest.raises(runtime.WorkflowError, match="input digest changed"):
        runtime.verify_dependencies(tmp_path, plan)
    undeclared_argument = _proposal(
        route_id="workspace-check",
        billable=False,
        remote=False,
        targets=[],
        parameters={"subcommand": "run", "arguments": {"api-key": "secret"}},
    )
    with pytest.raises(runtime.WorkflowError, match="unknown fields|sensitive"):
        runtime.prepare_managed_operation(tmp_path, wrapper, undeclared_argument)


def test_existing_directory_is_not_an_absent_target(tmp_path: Path) -> None:
    target = tmp_path / "outputs" / "managed" / "existing"
    target.mkdir(parents=True)
    plan = runtime.prepare_operation(
        _proposal(billable=False, remote=False, targets=[{"path": "outputs/managed/existing", "before_sha256": runtime.ABSENT}]),
        CONTEXT_DIGEST,
    )
    with pytest.raises(runtime.WorkflowError, match="regular file"):
        runtime.verify_dependencies(tmp_path, plan)


def test_managed_inputs_are_exact_and_config_drift_invalidates_context(tmp_path: Path) -> None:
    wrapper, context_path = _managed_fixture(tmp_path)
    source = tmp_path / "AGENTS.md"
    proposal = _proposal(
        route_id="browser",
        billable=False,
        remote=False,
        inputs=[{"path": "AGENTS.md", "sha256": runtime._sha(source.read_bytes()), "authority": "managed-fact"}],
        targets=[],
    )
    runtime.prepare_managed_operation(tmp_path, wrapper, proposal)
    bad = _proposal(
        route_id="browser",
        billable=False,
        remote=False,
        inputs=[{"path": "not-allowed.md", "sha256": "2" * 64, "authority": "managed-fact"}],
        targets=[],
    )
    with pytest.raises(runtime.WorkflowError, match="tracked-file allowlist"):
        runtime.prepare_managed_operation(tmp_path, wrapper, bad)

    loaded = runtime.load_managed_context(tmp_path, context_path)
    assert loaded == runtime.validate_runtime_wrapper(dict(wrapper))
    (tmp_path / ".agent-skills-config" / "creator-workflow.json").write_text("{}", encoding="utf-8")
    with pytest.raises(runtime.WorkflowError, match="digest changed"):
        runtime.load_managed_context(tmp_path, context_path)


def test_managed_context_requires_materializer_ownership_binding(tmp_path: Path) -> None:
    wrapper, context_path = _managed_fixture(tmp_path)
    arbitrary = tmp_path / "arbitrary-context.json"
    arbitrary.write_text(json.dumps(dict(wrapper)), encoding="utf-8")
    with pytest.raises(runtime.WorkflowError, match="materialized target"):
        runtime.load_managed_context(tmp_path, arbitrary)

    marker_path = context_path.parent / ".agent-skills-managed.json"
    marker = json.loads(marker_path.read_text(encoding="utf-8"))
    marker["context_digest"] = "4" * 64
    marker_path.write_text(json.dumps(marker), encoding="utf-8")
    with pytest.raises(runtime.WorkflowError, match="does not bind"):
        runtime.load_managed_context(tmp_path, context_path)

    with pytest.raises(TypeError, match="load_managed_context"):
        runtime.ManagedContext(dict(wrapper))
    with pytest.raises(TypeError, match="immutable"):
        wrapper["context"] = {}  # type: ignore[index]


def test_managed_context_requires_materialized_route_dependencies(
    tmp_path: Path,
) -> None:
    _wrapper, context_path = _managed_fixture(tmp_path)
    (tmp_path / ".agents" / "skills" / "playwright-cli" / ".agent-skills-managed.json").unlink()
    with pytest.raises(runtime.WorkflowError, match="required materialized Skill"):
        runtime.load_managed_context(tmp_path, context_path)


def test_managed_context_rejects_creator_and_required_skill_content_drift(
    tmp_path: Path,
) -> None:
    _wrapper, context_path = _managed_fixture(tmp_path)
    creator_skill = context_path.parent / "SKILL.md"
    creator_skill.write_text("drifted", encoding="utf-8")
    with pytest.raises(runtime.WorkflowError, match="creator-workflow Skill content drifted"):
        runtime.load_managed_context(tmp_path, context_path)

    required_repo = tmp_path / "required"
    _wrapper, context_path = _managed_fixture(required_repo)
    required_skill = (
        required_repo / ".agents" / "skills" / "playwright-cli" / "SKILL.md"
    )
    required_skill.unlink()
    with pytest.raises(runtime.WorkflowError, match="required materialized Skill content drifted"):
        runtime.load_managed_context(required_repo, context_path)


def test_managed_init_derives_state_root_and_context_digest(tmp_path: Path) -> None:
    wrapper, _context_path = _managed_fixture(tmp_path)
    workflow = runtime.initialize_managed_workflow(tmp_path, wrapper, "demo-flow", "content-project")
    assert workflow == tmp_path / ".creator-workflow" / "demo-flow"
    identity = runtime.verify_workflow(workflow)["identity"]
    assert identity["context_digest"] == runtime.managed_context_digest(wrapper)
    with pytest.raises(runtime.WorkflowError, match="protected"):
        runtime.initialize_managed_workflow(tmp_path, wrapper, "blocked", "content-project")
    assert not (tmp_path / ".creator-workflow" / "blocked").exists()

    plan = runtime.prepare_managed_operation(
        tmp_path,
        wrapper,
        _proposal(
            workflow_id="blocked",
            operation_id="blocked-operation",
            route_id="browser",
            billable=False,
            remote=False,
            targets=[],
        ),
    )
    bypass = runtime.initialize_workflow(
        tmp_path / ".creator-workflow",
        plan["workflow_id"],
        plan["profile_id"],
        plan["context_digest"],
    )
    lock = bypass / ".creator-workflow.lock"
    with pytest.raises(runtime.WorkflowError, match="protected"):
        runtime.record_prepared(
            bypass, plan, "blocked-prepared", TIME, repo=tmp_path, wrapper=wrapper
        )
    assert not lock.exists()
    with pytest.raises(runtime.WorkflowError, match="protected"):
        runtime.append_state(
            bypass,
            operation_id=plan["operation_id"],
            state="prepared",
            event_type="operation-prepared",
            payload={"plan": plan},
            event_id="blocked-append",
            occurred_at=TIME,
            repo=tmp_path,
            wrapper=wrapper,
        )
    assert not lock.exists()
    with pytest.raises(runtime.WorkflowError, match="protected"):
        runtime.recover_managed(tmp_path, wrapper, bypass)
    assert not lock.exists()

    sentinel = b"protected-lock-sentinel"
    lock.write_bytes(sentinel)
    with pytest.raises(runtime.WorkflowError, match="protected"):
        runtime.break_managed_lock(
            tmp_path, wrapper, bypass, runtime._sha(sentinel), True
        )
    assert lock.read_bytes() == sentinel


def test_managed_recording_cannot_escape_configured_state_root(tmp_path: Path) -> None:
    wrapper, _context_path = _managed_fixture(tmp_path)
    plan = runtime.prepare_managed_operation(
        tmp_path,
        wrapper,
        _proposal(
            route_id="browser",
            billable=False,
            remote=False,
            targets=[],
        ),
    )
    outside = runtime.initialize_workflow(
        tmp_path / "outside-state",
        plan["workflow_id"],
        plan["profile_id"],
        plan["context_digest"],
    )
    with pytest.raises(runtime.WorkflowError, match="configured state root"):
        runtime.record_prepared(
            outside,
            plan,
            "prepared-outside",
            TIME,
            repo=tmp_path,
            wrapper=wrapper,
        )
    lock = outside / ".creator-workflow.lock"
    assert not lock.exists()
    with pytest.raises(runtime.WorkflowError, match="configured state root"):
        runtime.append_state(
            outside,
            operation_id=plan["operation_id"],
            state="prepared",
            event_type="operation-prepared",
            payload={"plan": plan},
            event_id="append-outside",
            occurred_at=TIME,
            repo=tmp_path,
            wrapper=wrapper,
        )
    assert not lock.exists()
    with pytest.raises(runtime.WorkflowError, match="configured state root"):
        runtime.recover_managed(tmp_path, wrapper, outside)
    assert not lock.exists()


def test_one_off_recovery_state_is_external_and_has_no_repository_targets(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "consumer"
    repo.mkdir()
    external = tmp_path / "external-state"
    external.mkdir()
    proposal = _proposal(targets=[])
    plan = runtime.prepare_one_off_operation(proposal, CONTEXT_DIGEST)
    workflow = runtime.initialize_workflow(
        runtime._external_state_root(repo, external),
        plan["workflow_id"],
        plan["profile_id"],
        plan["context_digest"],
    )
    runtime._validate_one_off_workflow_location(repo, external, workflow)
    runtime.record_prepared_one_off(
        repo, external, workflow, plan, "one-off-prepared", TIME
    )
    with pytest.raises(runtime.WorkflowError, match="record_prepared_one_off"):
        runtime.append_one_off_state(
            repo,
            external,
            workflow,
            operation_id="bypass",
            state="prepared",
            event_type="operation-prepared",
            payload={"plan": runtime.prepare_operation(_proposal(), CONTEXT_DIGEST)},
            event_id="bypass-prepared",
            occurred_at=TIME,
        )
    assert runtime.recover_one_off(repo, external, workflow) == "clean"

    with pytest.raises(runtime.WorkflowError, match="outside the repository"):
        runtime._external_state_root(repo, repo)
    with pytest.raises(runtime.WorkflowError, match="must not declare repository targets"):
        runtime.prepare_one_off_operation(_proposal(), CONTEXT_DIGEST)

    wrong = external / "not-the-workflow"
    wrong.mkdir()
    with pytest.raises(runtime.WorkflowError, match="regular file|direct child"):
        runtime.recover_one_off(repo, external, wrong)
    assert not (wrong / ".creator-workflow.lock").exists()
