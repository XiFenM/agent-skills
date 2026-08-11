---
name: learn-by-practice
description: Run structured, repository-aware learning programs that combine source-based explanation, learner questions, agent-authored acceptance tests, test-driven learner practice, artifact review, revision, mastery checks, and durable progress records. Use when a user asks Codex to teach or study a technical or non-technical topic over multiple sessions; learn from tutorials, documentation, examples, papers, or a codebase; assign and review exercises; resume a paused course; maintain a learning journal; or transfer this guided-learning workflow to another subject or repository.
---

# Learn by Practice

Build understanding through a repeatable loop: explain, question, define behavior,
write acceptance tests, let the learner implement, review, revise, demonstrate mastery,
and preserve the evidence. Keep the learner in control of the core practice artifact.
For coding exercises, let the agent own routine test authoring so the learner can focus
on test-driven implementation. Treat the archive as part of the learning process.

## Choose the operating mode

Infer the narrowest mode that satisfies the request:

- **Start a course**: inspect sources, agree on scope and outcomes, create an archive,
  and begin the first lesson.
- **Continue a lesson**: recover the current checkpoint and resume the next unfinished
  phase without repeating completed material.
- **Resolve questions**: answer the learner's questions, test the explanation with a
  minimal example when useful, and update the lesson record.
- **Assign practice**: design exercises that target the concepts just discussed,
  define observable acceptance criteria, and author the executable behavioral tests
  before the learner begins a coding implementation.
- **Review work**: inspect the learner's artifact, run proportionate checks, record
  findings, add or repair regression tests when required behavior is uncovered, and
  let the learner revise the core artifact unless they explicitly ask for implementation.
- **Pause or close**: write a recovery checkpoint and synchronize learning evidence.

Do not force a full course archive for a one-off explanation unless the user asks for
ongoing study or durable records.

## Establish or recover context

1. Inspect repository instructions, layout, current status, relevant source material,
   existing learning records, and available validation commands.
2. Infer the topic, learner level, source authority, desired outcome, and artifact
   location when evidence is strong. Ask one concise question only when a missing choice
   would materially change the course.
3. Prefer primary material selected by the user. Distinguish source behavior, observed
   results, explanations, and hypotheses in both teaching and records.
4. When an archive already exists, read its index, the active lesson, and the latest
   pause checkpoint before acting. Preserve its conventions and history.
5. When durable records are requested and no archive exists, read
   [references/learning-archive.md](references/learning-archive.md), then run
   `scripts/init_learning_archive.py`. Adapt to an established repository convention
   instead of creating a competing documentation tree.

## Run one learning cycle at a time

### 1. Orient the lesson

- Identify the exact source unit, prerequisites, learning objectives, and completion
  evidence.
- Map the source's structure and execution or argument flow before discussing details.
- Record uncertain prerequisites without turning them into assumed deficiencies.

### 2. Explain the complete case

- Explain motivation, vocabulary, components, data or control flow, constraints,
  boundary behavior, verification, and tradeoffs at the learner's level.
- Tie explanations to exact local files or authoritative sources.
- Use small examples, diagrams, or experiments only when they materially clarify a
  relationship.
- Finish with the mental model the learner should be able to restate, then invite
  questions before assigning practice.

### 3. Resolve questions

- Preserve each original question and the learner's initial assumption.
- Answer the mechanism behind the behavior, not only the immediate symptom.
- Separate closely related operations when conflating them would create a fragile
  mental model.
- Confirm the resolved conclusion and record any derived question.

### 4. Design graduated practice

- Target recently discussed concepts rather than introducing unrelated complexity.
- Provide purpose, task, constraints, allowed hints, representative cases, validation
  method, completion definition, and optional extensions.
- Include at least one boundary or counterexample and one transfer variation when the
  subject permits it.
- For coding exercises, use a tests-first handoff: agree on the behavioral contract,
  write the smallest useful acceptance suite in the repository, run it to distinguish
  an expected red result from a broken test or environment, then give the learner the
  exact command and a concise case map.
- Test public behavior, invariants, boundaries, and invalid inputs without encoding or
  revealing the intended internal implementation. Keep the suite small enough to read
  and use as feedback rather than turning test construction into the lesson.
- For benchmark exercises, test the performance factors under study and the validity of
  the measurement boundary, such as warm-up, synchronization, resource configuration,
  workload accounting, and reproducibility. Do not add parameter-validation or error-path
  tests unless validation itself is a learning objective or the learner explicitly asks
  for them. Keep correctness in a separate functional suite when the benchmark is
  measurement-only.
- Keep the core implementation for the learner. Do not assign routine test-case writing,
  fixture work, or test refactoring to the learner unless testing itself is an explicit
  learning objective or the learner opts in. Supply stronger implementation hints only
  when requested or when the learner is genuinely blocked.
- Minimize work outside the core learning objective. Omit optional scaffolding, metadata,
  refactors, and evidence that do not affect mastery; let the agent handle small routine
  support work when safe, or defer it explicitly instead of expanding the learner task.

### 5. Review the learner's artifact

- Inspect before editing. Run repository-native validation in proportion to the risk.
- Treat acceptance tests as agent-owned learning infrastructure. If a required behavior
  lacks coverage or a test is wrong, add or repair the smallest test yourself before
  handing the production-code revision back to the learner.
- Lead with correctness and conceptual fidelity; then cover boundaries, error behavior,
  clarity, maintainability, reproducibility, and performance where relevant.
- Number findings, assign a severity, cite evidence, propose a direction, and track the
  learner's disposition across revisions.
- Do not create a learner finding merely because routine tests are missing. Record test
  changes and learner implementation changes separately so authorship remains clear.
- Distinguish “implemented” from “verified” and “closed.” Do not erase failed attempts
  or superseded findings from the record.

### 6. Verify mastery

- Ask the learner to restate the central model in their own words.
- Require an independent variation, prediction, comparison, or application that cannot
  be completed by copying the source mechanically.
- Require the learner's implementation to pass the agent-authored acceptance tests and
  ask them to explain at least one important boundary or failure case represented there.
- Close the lesson only when blocking findings are closed, required evidence passes,
  the explanation is transferable, and the learner agrees to proceed.

Read [references/practice-review-mastery.md](references/practice-review-mastery.md) when
designing nontrivial exercises, reviewing an artifact, or deciding whether a lesson is
complete.

## Keep records synchronized

Update the structured lesson record at meaningful transitions: after the main
explanation, after each question cluster, when assigning practice, after every review,
after verification, and at pause or completion. Link to source and learner artifacts;
do not duplicate large implementations that will drift.

Preserve:

- misunderstandings and their corrections;
- failed experiments, hypotheses, commands, and observed output;
- numbered review findings and their state transitions;
- environment details needed to reproduce results;
- the current checkpoint and exact next actions.

Keep structured conclusions separate from any dialogue material supplied by another
workflow. Do not reconstruct dialogue inside this Skill or rewrite it to make the
learning process appear cleaner.

## Pause and resume

When interrupted, add a checkpoint containing the current phase, completed work,
evidence, open findings, unresolved questions, next ordered actions, and the gate for
advancing. On resume, use that checkpoint as the entry point.

When the user explicitly requests dialogue discovery, extraction, or archiving, hand
that work to `study-log` and consume its reviewed output if the learning record needs a
link. Do not inspect provider session formats or maintain a second extraction path here.

## Resource map

- `scripts/init_learning_archive.py`: create a new subject archive without overwriting
  existing material.
- `assets/archive-index.md`: template consumed by the archive initializer.
- `assets/lesson-record.md`: comprehensive, domain-neutral lesson template.
- [references/learning-archive.md](references/learning-archive.md): archive layout,
  lifecycle, update rules, and migration guidance.
- [references/practice-review-mastery.md](references/practice-review-mastery.md):
  exercise design, review taxonomy, and mastery gates.
