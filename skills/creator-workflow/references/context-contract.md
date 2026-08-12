# Managed context contract

Use a version 2 consumer index and point `config.skills.creator-workflow` to a Git-tracked
`agent-skills.creator-workflow/v1` configuration. Unknown fields are errors at every level.

## Exact public shape

```json
{
  "schema": "agent-skills.creator-workflow/v1",
  "skill": "creator-workflow",
  "repository_fact_refs": [
    {"fact_id": "package", "role": "package-manifest", "kind": "file"},
    {"fact_id": "project-template", "role": "project-template", "kind": "collection"}
  ],
  "storage": {
    "state_root": ".creator-workflow",
    "project_roots": [{"id": "projects", "path": "projects/managed"}],
    "work_roots": [{"id": "work", "path": "work/managed"}],
    "output_roots": [{"id": "outputs", "path": "outputs/managed"}],
    "publication_roots": []
  },
  "profiles": [
    {
      "id": "content",
      "adapter": "generic-content-project-v1",
      "project_root": "projects",
      "work_root": "work",
      "output_root": "outputs",
      "template_fact_ref": "project-template",
      "routes": ["browser", "check"]
    }
  ],
  "routes": [
    {
      "id": "browser",
      "adapter": "selected-skill-v1",
      "skill": "playwright-cli",
      "effects": {"billable": false, "remote": true, "destructive": false, "publish": false}
    },
    {
      "id": "check",
      "adapter": "package-script-v1",
      "manifest_fact_ref": "package",
      "script": "check",
      "subcommands": ["run"],
      "argument_keys": ["target-path"],
      "effects": {"billable": false, "remote": false, "destructive": false, "publish": false}
    }
  ],
  "protected_roots": ["projects/frozen-project"]
}
```

Every route must contain exactly the four boolean `effects`. They are a strict route classification, not
authorization: an operation must match the route's `billable`, `remote`, and `destructive` values exactly,
and `publish` must match whether the operation kind is `publish`. Define separate route IDs when the same
underlying capability has materially different effects (for example, browser observation versus browser
publication). Billable work, remote dispatch, overwrite or deletion, and publication still require their
normal operation preview and exact grants.

`selected-skill-v1` accepts one lowercase-hyphen Skill name, rejects `creator-workflow` recursion, and makes
that Skill a required selection on every host where `creator-workflow` is materialized. Several routes may use the same Skill; the
materializer verifies one sorted, unique dependency with matching host coverage. `package-script-v1` accepts only a selected
`package-manifest` file fact, one safe package-script token, a finite non-empty list of safe subcommand
tokens, and a finite allowlist of data argument keys. A package plan binds exactly one subcommand plus an
`arguments` object whose keys are a subset of that allowlist. Every package plan must also bind the route's
exact package-manifest file as one digest-checked `managed-fact` input, so a script-definition change
invalidates the preview before execution. Neither adapter stores or executes arbitrary
commands, flags, working directories, environment values, URLs, headers, credentials, or complete prompt
bodies; bind larger inputs as digest-checked artifacts.

## Fact and profile binding

Profile and route locators bind both role and kind:

| Use | Required fact |
| --- | --- |
| Generic project template | `project-template` collection |
| Publication template | `publication-template` collection |
| Publication contract | `publication-contract` file |
| Package-script manifest | `package-manifest` file |

A collection fact must not declare a repository `section`; selecting a collection always means its tracked
UTF-8 members. The materializer expands only those Git-tracked members.

`generic-content-project-v1` uses named project, work, and output roots.
`pathnote-publication-v1` instead uses one named publication root plus publication-template and
publication-contract facts. Artifact business state remains profile-owned.

## Storage and protection

Every declared managed root must be used by a profile, and all managed write roots must be mutually
disjoint. A protected root may be disjoint from writes or a strict descendant of one managed root; it may
never equal or contain a managed root. This permits future packages under `publications` while freezing an
exact existing package.

Materialized write paths are ceilings, not authorization for an operation, overwrite, billable call,
publication, commit, or push. Public configuration must not contain credentials, remote job state, prompts,
authorization text, arbitrary commands, URLs, headers, or current workflow state.

With no valid materialized context, remain conversation-only or route a simple request directly to its
dedicated Skill. Do not guess repository paths or create a durable repository ledger.
