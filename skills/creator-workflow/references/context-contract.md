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
      "routes": ["browser", "generate"]
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
      "id": "generate",
      "adapter": "package-script-v2",
      "manifest_fact_ref": "package",
      "script": "generate",
      "subcommands": ["image"],
      "argument_bindings": [
        {"key": "model", "kind": "value", "value_type": "string", "required": true, "cardinality": "one"},
        {"key": "count", "kind": "value", "value_type": "int", "required": true, "cardinality": "one"},
        {"key": "prompt-file", "kind": "input-path", "authority": "user-provided", "required": true, "cardinality": "one"},
        {"key": "out", "kind": "output-base", "required": true, "cardinality": "one"},
        {"key": "metadata", "kind": "value", "value_type": "bool", "const": true, "required": false, "cardinality": "one"},
        {"key": "last-frame-out", "kind": "target-path", "required": false, "cardinality": "one"}
      ],
      "output_bindings": [
        {"id": "images", "kind": "indexed-by-count", "source_argument": "out", "count_argument": "count", "condition": {"kind": "always"}},
        {"id": "metadata", "kind": "suffix", "source_argument": "out", "suffix": ".json", "condition": {"kind": "argument-true", "argument": "metadata"}}
      ],
      "billing_bindings": {
        "provider": {"kind": "literal", "value": "configured-provider"},
        "model_or_tier": {"kind": "argument", "argument": "model"},
        "count": {"kind": "argument", "argument": "count"},
        "request_bounds": {
          "count": {"kind": "argument", "argument": "count"},
          "format": {"kind": "literal", "value": "png"}
        }
      },
      "effects": {"billable": true, "remote": true, "destructive": false, "publish": false}
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
that Skill a required selection on every host where `creator-workflow` is materialized. Several routes may
use the same Skill; the materializer verifies one sorted, unique dependency with matching host coverage.

`package-script-v1` remains the compatibility adapter for existing finite `argument_keys` routes. It
checks the selected package manifest but does not claim mechanical path, output, or billing binding. Do not
use it for a new billable or artifact-producing route.

`package-script-v2` accepts only a selected `package-manifest` file fact, one safe package-script token,
a finite non-empty list of safe subcommand tokens, typed `argument_bindings`, deterministic
`output_bindings`, and exact `billing_bindings` when `effects.billable` is true. Neither adapter stores or
executes arbitrary commands, flags, working directories, environment values, URLs, headers, credentials,
or complete prompt bodies; bind larger inputs as digest-checked artifacts.

## Declarative package bindings

Every argument binding contains `key`, `kind`, `required`, and `cardinality` (`one` or `many`). A `value`
also declares the exact scalar `value_type` (`bool`, `int`, or `string`) and may declare a same-type
canonical `const` when cardinality is `one`. An `input-path` additionally declares `authority` as
`managed-fact` or `user-provided`.

| Argument kind | Mechanical meaning |
| --- | --- |
| `value` | A bounded scalar or scalar list of the declared exact type. A configured `const` must match type and value exactly. It creates no file authority. |
| `input-path` | Each value equals one plan input path with the declared authority; its digest is verified against the exact file. |
| `output-base` | A scalar portable path consumed by one or more output rules. It is not itself a target. |
| `target-path` | Each value is an exact plan target, for adapters that expose the final output path directly. |

Every actual argument key must have one binding, every required key must be present, and cardinality is
strict. The complete plan input set must be exactly the manifest plus all input-path values; extra evidence
or an omitted argument input is an error. Large prompts, references, and media therefore travel by an exact
path and digest, not as inline configuration or ledger payloads.

An output rule consumes one `output-base` and has a unique ID plus a condition:

- `exact` emits the base path;
- `suffix` appends one configured portable filename suffix to the base path;
- `indexed-by-count` emits the base path when the bound count is one; for larger counts it inserts
  `-1` through `-N` before the base path's final extension, where `N` comes from a required scalar
  `int` count argument;
- `always`, `argument-present`, and `argument-true` conditions make optional outputs explicit.

The runtime recomputes the complete target set from enabled output rules and target-path arguments. An
enabled rule requires its base argument; a supplied base must have an enabled rule; duplicate derived paths
are rejected. If a provider has an output such as a last frame whose name cannot be deterministically
derived, expose a dedicated target-path argument or leave that option out of the route.

A billable route must bind `provider`, `model_or_tier`, `count`, and a non-empty `request_bounds` object.
Each value comes from either a required scalar value argument or a credential-free public literal. The
runtime requires type-sensitive exact equality between these resolved values and the plan's sanitized
billing envelope. The cost boundary and one-attempt maximum remain explicit authorization limits rather
than tool arguments.

A remote, non-billable v2 route may declare `observation_receipt_argument`. It must name a required,
non-constant scalar `string` value argument; the route must be non-destructive, non-publishing, and declare
no outputs. This declaration makes the route observation-only. The plan must declare `observation_of`, and
the named argument must equal `observed_receipt` exactly. A v2 package observation cannot use an ordinary
route without this declaration; define separate ordinary-status and observation-status route IDs when both
behaviors are needed.

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
