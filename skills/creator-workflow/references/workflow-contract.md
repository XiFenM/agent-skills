# Workflow and recovery contract

## Operation model

Use generic operation kinds: `research`, `design`, `create`, `transform`, `compose`,
`verify`, `package`, `publish`, and `maintain`.

The immutable event sequence is the state fact source. A snapshot is only a validated
projection. The lifecycle is:

`prepared -> authorized -> running -> dispatching -> submitted -> waiting -> succeeded | failed | unknown | cancelled`

Operations may skip only inapplicable intermediate states. Before execution, every declared
dependency must already be `succeeded`. A billable or remote operation must persist
`dispatching` before invocation; a submitted job must record one opaque provider receipt,
and that first receipt is immutable. A successful remote, billable, or publish operation
must retain that receipt. Terminal states are immutable. A retry is a new operation with
`retry_of`; it never rewrites the original operation.

An observation of an `unknown` operation is also a new operation. Its plan must declare
`observation_of` and the exact immutable `observed_receipt`; the reducer accepts it only
when that earlier operation is already terminal `unknown` with the same receipt. An
observation is a non-billable, non-destructive remote `verify` operation with no targets or
ordinary dependencies. It reports what was learned while leaving the original outcome
unchanged.

## Authorization envelope

Bind a one-use grant to:

- workflow and operation ID;
- canonical plan and preview digest;
- the exact required grants: `billable`, `retry`, `publish`, or `destructive`;
- exact request bounds and authorization time.

For every billable plan, persist a sanitized `billing` envelope containing the provider,
model or tier, count, non-empty request bounds, cost boundary (`hard-cap` or
`estimate-only` with currency and positive decimal amount), and
`one_attempt_max: true`. Authorization grants must equal the plan's required grants;
extra grants are rejected. Prompts, headers, credentials, and opaque request bodies never
belong in this envelope—bind larger request inputs by digest.

Any plan, input, route, profile, configuration, manifest, argument binding, derived target,
or billing-bound value drift invalidates the grant. For a package route, the manifest plus
all input-path arguments must be the complete plan input set; direct target arguments plus
configured derivations must be the complete target set; and provider, model or tier, count,
and request bounds must exactly equal the configured literal or argument sources.
Generation permission does not imply publication permission.

A managed `package-script-v2` operation may enter `succeeded` only with canonical artifact evidence that
lists every planned target exactly once as `path` plus SHA-256. The managed append reloads the current
context, revalidates the route and bindings, rechecks bound input digests, and verifies that each artifact
is a real regular file whose current bytes match the recorded digest. Legacy `package-script-v1` and
repository-external one-off ledgers retain their existing success semantics.

## Durable files

A durable workflow keeps a sanitized state directory under the configured state root:

```text
<state-root>/<workflow-id>/
|-- workflow.json
|-- events.jsonl
|-- snapshot.json
`-- transaction/
```

`events.jsonl` uses a SHA-256 hash chain. `snapshot.json` is reproduced from those events
and must equal the stored projection. Transaction files, locks, and temporary replacements
are recovery mechanisms, not a second business state source. Every managed append and
recovery revalidates that the workflow is the direct configured state-root child for its
identity.

Use a repository-external temporary state root for a one-off remote operation. The CLI
provides `prepare-one-off`, `init-one-off`, `record-prepared-one-off`,
`record-one-off`, `recover-one-off`, and `break-stale-lock-one-off`; each stateful command
binds the exact external state root and direct workflow child. A one-off plan cannot
declare repository targets or managed-fact inputs, and only the dedicated prepared command
may introduce a plan. Delete the external workflow only after a terminal result has been
verified. If cleanup cannot be proven, report the path and required cleanup.

## Failure and recovery

- Persist local intent before a remote call and use a provider idempotency key when supported.
- On crash or timeout, inspect the existing operation and provider receipt. Do not infer failure from lack of a local response.
- An uncertain submission or outcome makes the original operation terminal `unknown`. Investigate the original receipt or job through a typed `observation_of` operation bound to that exact receipt; do not rewrite the original outcome. A replacement attempt is a separate operation with a separate retry grant.
- Use an exclusive cooperative lock for append and recovery, before digests including `ABSENT`, temporary files, and atomic replacements for local state. An existing directory is never equivalent to an absent file target.
- A hard crash may leave the lock file behind. Do not delete it manually. After verifying that its recorded PID is no longer active, use `break-stale-lock` or `break-stale-lock-one-off` with the exact lock SHA-256 and explicit confirmation; then run recovery. An active, malformed, changed, or unconfirmed lock is never removed.
- If a target is neither its recorded before nor after digest, stop for conflict. Never overwrite a third state during recovery.
- Do not claim atomicity against uncooperative writers or across a remote provider and the local filesystem.

The deterministic runtime performs bookkeeping and integrity checks only. The agent or
delegated tool performs the actual work and records the returned observation.
