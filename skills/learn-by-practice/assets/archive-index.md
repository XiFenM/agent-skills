# {{SUBJECT}} learning archive

This directory preserves both the final understanding and the path used to reach it: source-based
explanations, learner questions, practice artifacts, experiments, reviews, revisions, mastery
checks, and pause checkpoints.

## Program profile

| Field | Value |
| --- | --- |
| Subject | {{SUBJECT_TABLE}} |
| Subject slug | `{{SUBJECT_SLUG}}` |
| Intended outcome | To be agreed with the learner |
| Primary sources | {{SOURCE_DESCRIPTION_TABLE}} |
| Started | {{START_DATE}} |
| Archive state | active |

## Learning loop

1. Orient the lesson and verify prerequisites.
2. Explain one complete source unit and its mental model.
3. Resolve and record learner questions.
4. Agree on graduated practice with explicit behavioral acceptance criteria.
5. Let the AI agent write the minimal acceptance tests or rubric before implementation.
6. Let the learner create the core artifact using test-driven feedback.
7. Review with numbered, evidence-backed findings and agent-authored regression tests.
8. Let the learner revise the core artifact and verify each finding.
9. Check conceptual, practical, and transferable mastery.
10. Close or pause with a recovery checkpoint.

## Directory layout

```text
.
├── README.md
├── templates/lesson-record.md
├── lessons/
├── references/
└── attachments/
```

- Keep lesson conclusions in `lessons/`.
- Keep practice artifacts in the repository's normal source locations and link to them.
- Keep bulky generated evidence in `attachments/<lesson>/`.
- Do not edit authoritative source snapshots merely to add notes.

## Lesson index

Use states: `not-started`, `explaining`, `questions`, `practicing`, `reviewing`,
`mastery-check`, `paused`, and `complete`.

| Lesson | Source unit | Structured record | State |
| --- | --- | --- | --- |
| 01 | To be selected | `lessons/01-<lesson>.md` | not-started |

## Current checkpoint

| Field | Current value |
| --- | --- |
| Active lesson | Lesson 01, not started |
| Current phase | Course setup |
| Latest evidence | Archive initialized |
| Open work | Select the first source unit and confirm learning objectives |
| Next action | Create the first lesson from `templates/lesson-record.md` |
| Advancement gate | Lesson-specific blocking findings closed and mastery demonstrated |

## Recording principles

- Separate source facts, observations, explanations, inferences, and learner understanding.
- Preserve mistakes, failed experiments, changed assumptions, and review history.
- Record reproducible evidence before claiming correctness or performance.
- Keep routine tests or rubrics agent-owned and the core practice artifact learner-owned.
- Treat “changed,” “verified,” and “closed” as different review states.
- Only when the user explicitly requests conversation discovery, extraction, or archiving,
  delegate it to `study-log` and link the reviewed, user-approved output if this archive needs it.
- Resume from the latest checkpoint instead of reconstructing the course from memory.
