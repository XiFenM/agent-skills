# Post-hoc dialogue archive

Use this reference only at a deliberate pause or lesson boundary when a Codex rollout JSONL is
available. Keep the structured lesson record authoritative for conclusions and the dialogue
archive authoritative for the visible conversational sequence.

## Contents

1. [Extraction boundary](#extraction-boundary)
2. [Locate and preview a session](#locate-and-preview-a-session)
3. [Export a lesson](#export-a-lesson)
4. [Review before linking](#review-before-linking)
5. [Snapshots and multiple sessions](#snapshots-and-multiple-sessions)
6. [Known limitations](#known-limitations)

## Extraction boundary

The bundled exporter retains only `response_item` message payloads whose role is `user` or
`assistant`. By default it:

- retains user text, assistant commentary, assistant final answers, timestamps, and Markdown;
- removes standalone environment context and IDE request wrappers while preserving the request;
- removes standalone `<skill>...</skill>` documents injected by the client while preserving the
  user's explicit Skill invocation text;
- removes adjacent identical messages after normalization;
- excludes system/developer messages, reasoning, tool calls, tool results, and internal events.

This is a rule-based visible-dialogue export, not a byte-for-byte session copy. Preserve the
rollout JSONL as the final provenance source. Use `--keep-client-context --keep-duplicates` only
when injected client context is part of the research question.

## Locate and preview a session

List likely Codex sessions:

```bash
rg --files /home/coder/.codex/sessions -g 'rollout-*.jsonl'
```

Confirm candidates by modification time, session ID, and user-message previews. Do not choose a
session only from its filename date.

```bash
python <skill-dir>/scripts/export_codex_dialogue.py list \
  <session.jsonl> \
  --role user \
  --preview 180
```

Choose a distinctive lesson-opening user message and the first user message belonging to the
next phase. Prefer semantic text boundaries because they remain understandable in the record;
add timestamps when text repeats.

## Export a lesson

```bash
python <skill-dir>/scripts/export_codex_dialogue.py export \
  <session.jsonl> \
  docs/learning/<subject>/dialogues/01-<lesson>.md \
  --title 'Lesson 01: <title> — raw learning dialogue' \
  --lesson 01-<lesson> \
  --start-user '<opening message fragment>' \
  --end-before-user '<next-phase message fragment>'
```

- `--start-user` is inclusive.
- `--end-before-user` is exclusive and searches only after the selected start.
- `--start-time` is inclusive and `--end-time` is exclusive; both accept ISO-8601.
- Text and time selectors intersect when used together.
- `--final-only` removes assistant commentary but normally loses useful visible process.
- `--overwrite` is required to replace an existing archive.

Do not export an active session to its current end without an explicit boundary. A later message
could silently become part of the wrong lesson when the command is rerun.

## Review before linking

Check all of the following:

1. The first and last messages belong to the intended lesson.
2. The message count and user/assistant ordering are plausible.
3. The next lesson, meta-discussion, system instructions, reasoning, and tool events are absent.
4. Credentials, private attachment contents, unrelated personal data, or sensitive paths were not
   unintentionally included.
5. The frontmatter contains source file, session ID, source snapshot hash, selected-dialogue hash,
   first/last timestamps, message count, and normalization settings.
6. The subject index and lesson record link to the archive and label a partial export accurately.

Do not manually edit message bodies after export. If selection or privacy is wrong, adjust the
boundary or normalization logic and regenerate so provenance remains meaningful.

## Snapshots and multiple sessions

An active rollout file continues to grow, so `source_sha256` represents the snapshot read at
export time. The selected `dialogue_sha256` remains stable when the same normalized messages are
selected.

For a partial lesson:

- label the archive “partial” or “pause snapshot” in the structured record;
- preserve the opening boundary and record the ending boundary;
- re-export with `--overwrite` only after reviewing the diff at final closure.

For a lesson spanning multiple sessions, export one file per session segment. Keep provenance for
each segment and create an ordered list in the lesson record. Do not concatenate bodies while
discarding their individual source metadata.

## Known limitations

- Rollout schemas can change; verify synthetic tests or inspect payload shapes after a Codex
  upgrade.
- Substring boundaries choose the first matching user message in the eligible range.
- Only `input_text` and `output_text` are embedded; images and other non-text inputs remain in the
  source session or separately archived attachments.
- Client wrapper normalization is intentionally conservative and may need updating for a new IDE
  format.
- A dialogue archive contains what was visible, not every internal event that affected the turn.
