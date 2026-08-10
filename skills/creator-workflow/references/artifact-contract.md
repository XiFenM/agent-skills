# Artifact contract

Use this layout for durable creator projects:

```text
projects/<slug>/
├── brief.md
├── project.json
├── manifest.json
├── prompts/
├── inputs/
└── notes/

outputs/<slug>/
├── images/
├── video/
├── audio/
└── reports/
```

Keep small source files, prompts, props, and metadata in Git. Keep large or reproducible generated media in `outputs/`, which is ignored except for its placeholder.

`manifest.json` should be an object with a `generations` array. Each generation entry should contain:

```json
{
  "kind": "image | video | understanding | render",
  "provider": "zenmux | remotion | other",
  "model": "provider/model-or-null",
  "createdAt": "ISO-8601 timestamp",
  "requestId": "provider request or job ID",
  "inputs": ["repo-relative paths or URLs"],
  "outputs": ["repo-relative paths"],
  "parameters": {},
  "notes": ""
}
```

Do not place API keys, cookies, authorization headers, private browser state, or base64 media payloads in project files or manifests.
