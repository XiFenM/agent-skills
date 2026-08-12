---
name: creator-workflow
description: Coordinate multi-stage, traceable content and creation lifecycles across research, design, generation, composition, verification, packaging, recovery, and publication handoff. Use when a request needs two or more capability lanes, durable artifacts, resumable paid or asynchronous work, project acceptance, or a publishable package. Do not use for a simple one-tool generation, browser action, edit, or inspection that a dedicated Skill can complete directly.
---

# Creator Workflow

Orchestrate creation without taking over provider-, browser-, framework-, or repository-specific behavior.

## Choose the smallest mode

1. Use `consult` for planning or review in the conversation. Write nothing.
2. Route a simple one-tool request directly to its dedicated Skill. Do not create a durable workflow merely for bookkeeping.
3. Use `one-off` for an explicitly requested billable or asynchronous operation that needs a temporary recovery receipt but no repository project.
4. Use `project` when the work spans multiple stages, must survive sessions, or needs traceable acceptance and packaging.
5. Use `resume` or `recover` only from an existing verified ledger. Never infer a remote result or silently submit a replacement job.

When a materialized context exists, verify it before reading repository facts or proposing durable paths. Treat every path and route in context as a locator or mechanical ceiling, never as operation authorization. With no context, remain in `consult` or a direct one-tool lane and perform no repository writes.

## Prepare before side effects

1. Capture the goal, audience, scope, acceptance criteria, required sources, rights or sensitivity constraints, and requested delivery form.
2. Divide the work into explicit operations. Use only the stages that matter: intake, research, design, production, assembly, verification, packaging, publication, and maintenance.
3. Resolve each operation through an allowed route. Read [references/capability-routing.md](references/capability-routing.md) before delegating to browser, generation, composition, validation, or publication tools.
4. For a durable project, read [references/workflow-contract.md](references/workflow-contract.md) and use the deterministic runtime to prepare the plan and preview digest before changing managed state.
5. Read [references/artifact-contract.md](references/artifact-contract.md) before accepting inputs or registering artifacts.

## Apply exact authorization gates

- A clear generation request may authorize one first billable attempt only when provider or capability, model or tier, count, request bounds, and cost boundary are explicit. If a monetary hard cap is unavailable, disclose that the estimate is non-binding and bind the request by input, duration or token limits, count, and one-attempt maximum.
- Treat a retry, a new billable attempt, overwrite or deletion, and external publish or send as separate grants. Bind each grant to the exact operation and preview digest.
- Persist `dispatching` before a remote call. If submission or result is uncertain, record the original operation as terminal `unknown`; investigate the original receipt or job ID through a typed `observation_of` operation bound to that receipt. Never rewrite the original outcome or auto-submit a replacement.
- Configuration, templates, an available account, a target path, prior permission, or a provider suggestion never grants a side effect.
- Never ask for or record API keys, cookies, authorization headers, browser storage, signed private URLs, or large encoded payloads. Repository policy overrides a delegated Skill that suggests weaker credential handling.

## Keep ownership separate

- This Skill owns orchestration plans, operation events, provenance links, recovery state, and acceptance records.
- Dedicated Skills and adapters own the semantics of browser, generation, editing, composition, validation, and publishing actions.
- A remote provider owns remote job state; record only opaque receipts and observations.
- Artifact profiles own their business states. For example, a publication profile may own draft/reviewed/published; do not collapse that state into the generic operation lifecycle.
- The user owns source materials and accepted deliverables. Preserve originals and derive new artifacts.

## Finish or pause safely

Verify event-chain integrity, dependency and target digests, profile-specific checks, and acceptance evidence. Distinguish operation success from artifact acceptance. Report created and changed artifacts, external calls, billable attempts, validation performed, unresolved remote outcomes, and limitations. A publish operation is complete only when its adapter returns a verifiable receipt.

For managed repository configuration, read [references/context-contract.md](references/context-contract.md). The deterministic runtime records and verifies operations; it never invokes a provider, shell, Git, browser, or network on the agent's behalf.
