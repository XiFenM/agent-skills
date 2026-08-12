# Capability routing

Route by responsibility, not by copied command instructions.

- A single browser action goes directly to the configured browser Skill. In a project, this workflow supplies the goal, evidence contract, and authorization boundary; the browser Skill owns sessions, snapshots, element references, traces, and detach behavior.
- Remotion work uses only the configured aggregate `remotion-best-practices` entry. Load its nested references for captions, creation, maps, rendering, or upgrades; do not invoke retired top-level Remotion Skill names.
- Use provider context Skills for current model, API, or pricing facts; setup Skills for integration; usage Skills for account usage. An explicitly configured execution adapter owns actual generation.
- Use configured validators for media metadata, code checks, publication package checks, and delivery acceptance. A successful validator does not establish rights or content approval unless its profile says so.
- Keep publish, upload, send, purchase, delete, and final form submission behind an exact external-write grant.

A selected-Skill route identifies a capability reference. A new package-script route uses `package-script-v2` to identify a repository-owned package script, a finite list of subcommands, typed argument bindings, deterministic output derivations, and—for billable routes—exact billing bindings. Retain `package-script-v1` only for backward-compatible non-producing routes. Neither route auto-executes. Configuration cannot contain arbitrary commands, working directories, flags, environment values, URLs, or credentials. The operation plan must still state the exact action and arguments and receive the required authorization.

For a package script, every actual argument key must be declared. Input-path arguments mechanically select the plan inputs and their digest checks; target-path arguments select exact targets; output-base arguments produce targets only through configured `exact`, `suffix`, or `indexed-by-count` rules. Optional outputs use an explicit argument-presence or boolean-true condition. Never accept a target merely because the plan repeats a path that cannot be recomputed from these bindings.

Declare exact scalar types and use a canonical constant for fixed flags such as a required no-wait or compression mode. Use a separate observation-only v2 route when a status subcommand must bind an earlier unknown operation's opaque receipt; do not let an ordinary status route stand in for that binding.

When a delegated Skill conflicts with repository credential, cost, browser, or publication policy, follow the stricter repository and central workflow policy.
