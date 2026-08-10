# Learning archive operations

Use this reference when creating, adopting, updating, pausing, resuming, or completing a
durable learning program.

## Contents

1. [Archive root and layout](#archive-root-and-layout)
2. [Lifecycle states](#lifecycle-states)
3. [Index responsibilities](#index-responsibilities)
4. [Lesson record responsibilities](#lesson-record-responsibilities)
5. [Synchronization events](#synchronization-events)
6. [Pause and resume](#pause-and-resume)
7. [Adopting an existing archive](#adopting-an-existing-archive)
8. [Evidence and writing rules](#evidence-and-writing-rules)

## Archive root and layout

Prefer `docs/learning/<subject-slug>/` when the repository has no established learning
documentation convention. Use a shorter `docs/<subject>-learning/` or an existing tree when
that is already the local convention.

```text
<archive>/
├── README.md
├── templates/
│   └── lesson-record.md
├── lessons/
│   └── 01-<lesson-slug>.md
├── dialogues/
│   └── 01-<lesson-slug>.md
├── references/
└── attachments/
    └── 01-<lesson-slug>/
```

- Keep the subject index and current recovery checkpoint in `README.md`.
- Keep one authoritative structured record per lesson.
- Keep learner-created code, notebooks, designs, or other artifacts in the repository's
  normal source locations; link to them from the lesson.
- Store only bulky, generated, or machine-readable evidence under `attachments/`.
- Preserve source materials in place. Do not annotate or rewrite vendored or official
  snapshots unless the user explicitly wants an edited copy.
- Store generated visible-dialogue archives under `dialogues/` and never hand-polish them.

Run the initializer from the repository root when creating the default layout:

```bash
python <skill-dir>/scripts/init_learning_archive.py \
  --root . \
  --subject "Rust async programming" \
  --slug rust-async \
  --source "The Rust Async Book and local examples"
```

Use `--archive` to select an established documentation location. The initializer refuses to
replace an existing path.

## Lifecycle states

Use this stable state set unless the repository already defines an equivalent one:

| State | Meaning |
| --- | --- |
| `not-started` | Indexed, but no teaching work has begun |
| `explaining` | The main source case is being explained |
| `questions` | The learner is resolving conceptual questions |
| `practicing` | Exercises are assigned or being implemented |
| `reviewing` | An artifact is under review and revision |
| `mastery-check` | Implementation gates passed; transfer is being checked |
| `paused` | Work deliberately stopped with a recovery checkpoint |
| `complete` | Mastery gate passed and the learner agreed to proceed |

Record state changes in the lesson changelog. Do not label a lesson complete merely because
the example runs or the learner wants to skip unresolved blocking findings.

## Index responsibilities

Keep `README.md` concise and operational. Include:

- the subject, intended outcome, source authority, and archive start date;
- the fixed learning loop and documentation conventions;
- a lesson table with number, source unit, record link, state, and dialogue status;
- one current checkpoint with active lesson, current phase, evidence, open work, next action,
  and the advancement gate;
- stable principles such as source/evidence separation, agent ownership of routine validation,
  and learner ownership of the core practice artifact.

Update the index when a lesson is created, its state changes, a dialogue is exported, a pause
snapshot changes the recovery entry point, or the course plan changes.

## Lesson record responsibilities

Create a lesson from `templates/lesson-record.md` and retain every section. Mark a section
“not applicable” with a reason instead of silently deleting it.

Keep the following distinct:

- **Source facts**: exact behavior or claims from code, documentation, paper, or other source.
- **Observed evidence**: commands, cases, outputs, measurements, or review reproduction.
- **Explanation**: the model used to make source facts understandable.
- **Inference**: a hypothesis, likely implication, or unverified performance claim.
- **Learner understanding**: the learner's current model, questions, and restatement.

Do not copy entire source files or learner implementations into the record. Quote only the
small fragment required to discuss a mechanism and link to the authoritative artifact.

## Synchronization events

Update the lesson after these events:

1. **Lesson setup**: objectives, prerequisites, source map, and expected evidence.
2. **Explanation delivered**: mental model, important mechanisms, constraints, and pitfalls.
3. **Question resolved**: original question, initial assumption, explanation, minimal example,
   conclusion, status, and derived question.
4. **Practice assigned**: purpose, requirements, constraints, hints, representative cases,
   agent-authored test or rubric paths, exact commands, initial red/sanity result, and completion gate.
5. **Artifact submitted**: paths, learner design, commands, environment, and first results against
   the provided validation.
6. **Review completed**: numbered findings, severity, evidence, recommendation, disposition,
   current status, and any agent-authored regression-test changes.
7. **Revision verified**: changed behavior, validation output, regressions, and findings closed.
8. **Pause or completion**: checkpoint, mastery result, dialogue status, and next boundary.

Avoid rewriting old entries to reflect later understanding. Add corrections and state
transitions so the reasoning history remains visible.

## Pause and resume

Write a pause snapshot whenever the user deliberately stops, changes focus for an extended
period, or asks for a checkpoint. Include:

| Field | Required content |
| --- | --- |
| Position | Active lesson and exact phase |
| Completed | Concepts, exercises, and reviews already finished |
| Evidence | Latest reproducible commands and results |
| Open work | Findings, questions, missing validation, or unverified changes, each with an owner |
| Next actions | Small ordered steps that can be started immediately |
| Advancement gate | Conditions required before the next lesson |
| Dialogue | Export file or explicit “not yet exported” state |

On resume:

1. Read the index checkpoint and active lesson snapshot.
2. Verify cheap, drift-prone state such as current files and test status.
3. State the recovered position and first next action.
4. Continue from that point; do not recreate finished explanations or overwrite history.

## Adopting an existing archive

Do not run the initializer over an existing learning tree. Instead:

1. Map existing files to index, lesson, dialogue, reference, and attachment roles.
2. Preserve names and links unless inconsistent naming blocks automation.
3. Add only missing lifecycle fields and recovery information.
4. Copy the generic lesson template only if the archive lacks an equivalent template.
5. Record the migration decision in the index and affected lesson changelog.

When the archive is domain-specific, retain valuable domain fields in its lesson template.
Generalize the workflow, not the knowledge that makes the domain record useful.

## Evidence and writing rules

- Record actual commands and salient output, not retrospective claims that a check passed.
- Capture environment details only when they can change correctness, compatibility, or
  performance.
- Separate correctness from performance and exclude warm-up or first-use costs when claiming
  steady-state performance.
- Give every review finding a durable ID and preserve rejected findings with rationale.
- Attribute routine test/rubric changes to the agent and core artifact changes to the learner.
- Prefer relative repository links in generated records.
- Use the learner's language unless they request otherwise.
- Keep the structured record readable without the raw dialogue, and keep the raw dialogue
  meaningful without editorial corrections from the structured record.
