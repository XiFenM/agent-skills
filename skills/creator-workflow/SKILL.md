---
name: creator-workflow
description: Coordinate end-to-end creator and self-media work across research, browser operations, ZenMux image or video generation and understanding, Remotion composition, and final media QA. Use for multi-step content production requests that should produce a reusable brief, tracked prompts, generated assets, a controllable video, or a publish-ready package.
---

# Creator Workflow

Turn a content idea into traceable source files and verified deliverables. Keep orchestration here; defer provider-specific and framework-specific details to their official skills.

## Route the request

1. Create or reuse `projects/<slug>/`.
2. Copy `projects/_template/brief.md` and `project.json` when starting a durable project.
3. Select only the lanes needed:
   - For browser work, read `playwright-cli`. Attach to the user's Chrome only when existing tabs or login state are needed; otherwise open an isolated CLI session.
   - After attaching to an external browser, detach instead of closing it. Never inspect or persist authentication material unless the user explicitly requests it.
   - For ZenMux API facts, read `zenmux-context`; for credentials and integration, read `zenmux-setup`.
   - For images, generated videos, or media understanding, use `pnpm zenmux`.
   - For a controllable composition, read `remotion-best-practices` plus the narrow Remotion skill needed by the task.
   - For media metadata and output validation, use `pnpm media:probe`.
4. Read [references/artifact-contract.md](references/artifact-contract.md) before creating deliverables.

## Plan before billable work

- Capture the target platform, audience, aspect ratio, duration, tone, required text, and acceptance criteria in the brief.
- Run ZenMux commands with `--dry-run` when validating a new request shape or when generation intent is ambiguous.
- Treat an explicit user request to generate media as authorization for one reasonable generation attempt.
- Before retrying a failed or timed-out asynchronous job, query its existing job ID to avoid duplicate charges.
- Never request that a user paste a secret into chat. Ask them to set it in `.env` locally.

## Produce traceable artifacts

- Save prompts and human-editable inputs under `projects/<slug>/`.
- Save large generated files under `outputs/<slug>/`; do not commit them by default.
- Record provider, model, timestamp, input paths, output paths, generation or job ID, and key parameters in `projects/<slug>/manifest.json`.
- Keep Remotion content in props JSON rather than hard-coding campaign copy into components.
- Preserve source assets; create derivatives instead of overwriting inputs.

## Verify

1. Run `pnpm media:probe -- <file>` for final audio or video when FFprobe is available.
2. Preview Remotion work in Studio and render a still before a full render.
3. Check duration, dimensions, aspect ratio, readable text, safe margins, audio presence, and obvious black or frozen frames.
4. Run `pnpm check` after code changes.
5. Report output paths, models used, known limitations, and any unverified item.
