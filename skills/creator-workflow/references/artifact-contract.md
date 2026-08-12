# Artifact contract

Use profiles to describe repository-specific packages without imposing one universal business manifest.

## Universal minimum

For each registered artifact, record only what the orchestration layer can prove:

- stable artifact ID and disposition: `candidate`, `accepted`, `rejected`, or `superseded`;
- repository-relative path or a redacted external locator;
- SHA-256 digest when local bytes exist;
- producing operation and upstream artifact IDs;
- media or document kind and optional profile-owned metadata;
- validation operation IDs and acceptance evidence.

Do not store secrets, cookies, authorization headers, browser storage, signed query strings, private raw URLs, or base64 payloads. Redact a URL before recording it when its path or query contains confidential identifiers.

Operation success and artifact acceptance are separate facts. Preserve rejected and failed derivatives when a profile requires auditability, but do not present them as deliverables.

## Source and derivative rules

- Preserve sources and create derivatives instead of overwriting them.
- Bind every operation to exact source digests. If a source changes, prepare a new operation.
- Predeclare every package-script output. Derive exact paths, filename suffixes, and numbered
  batches mechanically from configured arguments; use an explicit target-path argument when
  an adapter's output naming cannot be reproduced before dispatch.
- Record rights, consent, and sensitivity decisions in the relevant profile when they affect use or publication.
- Keep large or reproducible output placement and Git policy in consumer configuration, not in this central contract.
- Treat untracked local source media as an exact per-operation input. Never scan a broad directory or infer permission from a configured write root.

## Profile boundary

The central event ledger is the universal provenance source. A profile may additionally own a project manifest, publication package, generation history, review model, or delivery report. Do not copy those profile states into the central snapshot and do not retrofit a new profile into frozen legacy artifacts without a separate adoption preview and confirmation.
