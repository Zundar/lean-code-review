# Platform adapters

Read this file for installation, runtime troubleshooting or isolation checks.
The shared workflow is platform-neutral. The sole launcher is `lean-review`;
its runtime adapter is supplied by the current executor, not selected by the
reviewer. Use one global checkout and
`~/.agents/skills/lean-code-review` discovery link, as described in the README.

## Exact input

Use a collision-safe private directory and never rewrite a hashed artifact:

```sh
umask 077
review_dir=$(mktemp -d)
git diff --binary --full-index --find-renames "$base" "$target" > "$review_dir/diff.patch"
chmod 400 "$review_dir/diff.patch"
sha256sum "$review_dir/diff.patch"
```

For a working tree, explicitly enumerate task-owned paths. A temporary index
includes final staged, unstaged and untracked task-owned bytes without touching
the actual index:

```sh
umask 077
review_dir=$(mktemp -d)
GIT_INDEX_FILE="$review_dir/index" git read-tree "$base"
GIT_INDEX_FILE="$review_dir/index" git add -A -- path/to/task-file path/to/new-file
GIT_INDEX_FILE="$review_dir/index" git diff --cached --binary --full-index \
  --find-renames "$base" -- path/to/task-file path/to/new-file > "$review_dir/diff.patch"
rm -- "$review_dir/index"
chmod 400 "$review_dir/diff.patch"
sha256sum "$review_dir/diff.patch"
```

Use `target:worktree` for these exact current bytes. When the target changes,
create another private directory and artifact. The parent owns completeness,
task scope, sanitization, evidence and publication authorization. The launcher
validates SHA-256 before and after the run; its private copy is read-only and
its complete contents are delivered in the reviewer packet. A changed digest
requires another final review. Do not include credentials or unrelated data.

## OpenCode 1

The adapter targets the OpenCode 1.x permission/bash/task contract. Each review
uses a new runtime Git root outside the target repository, separate HOME,
XDG config/cache/state, and external skill scans disabled. Only the existing authentication file is linked into the isolated XDG data store. Inherited OpenCode config overrides are
removed. The target repository's `.opencode` files never load.

The parent integration supplies the current runtime adapter, effective
`provider/model`, and absolute `LEAN_REVIEW_OPENCODE_CLI` plus matching
`LEAN_REVIEW_OPENCODE_VERSION` through the launch context. The launcher uses
that caller-bound executable for version preflight and launch; it never resolves
`opencode` through `PATH`, which can select a different major version in a dual
install. Include `assets/platforms/opencode/binding.ts` as a V1 plugin alongside
the existing `shell.env` binding; it contributes the V1 host executable and
version while preserving the caller's existing session/model binding. The launcher preserves that exact
model unless an explicit full `provider/model` override is supplied; both remain
inside the OpenCode adapter. The same selected identifier and canonical effort
are reapplied on resume, without rereading caller context. Provider credentials
alone do not supply a custom transport/model definition. When the selected
model is present in the resolved user-local config, the launcher copies only its
HTTPS OpenAI-compatible endpoint and allowlisted model metadata into the
private runtime. Plugins, MCP, project config and credentials are never copied;
an unsupported or absent provider remains BLOCKED. Do not bypass the checker.

`SKILL_ROOT` is the standalone checkout; `LEAN_REVIEW_TARGET_REPO` supplies the
separate target to the bounded tools. Only canonical profile bytes and the
bounded `lean_review.ts` provider are materialized. The runtime changes
`mode: subagent` to `mode: primary` so the selected reviewer runs directly,
with no parent or task tool. The checker compares bytes with the standalone
Git index, rejects extra providers/MCP/plugins, and verifies effective tools
and final deny/allow rules before starting review.

Only `lean_review_read`, `lean_review_list`, and `lean_review_grep` are allowed.
Built-in read/glob/grep, edit, bash, task, web, skill and unknown tools are denied.
The bounded implementation reads only project-relative regular text files,
rejects traversal/symlink/secret targets and limits size, depth, entries and
output. It uses no shell or subprocess. This is a capability boundary, not an
OS sandbox against other processes running as the same user.

Rechecks resume the same directly selected reviewer session ID. A changed
canonical profile/provider identity or conflicting explicit model blocks session
reuse. Legacy sessions without model binding require a new review. Retain runtime
folders until final PASS; cleanup is always address-specific.

## OpenCode 2

The `/lean-review` command reads its exact caller `sessionID` and selected
provider/model/variant through the V2 APIs. The generic launcher freezes the
artifact, digest, base, target, and repository before the command creates a
distinct `spec-reviewer-*` session in the same service. Only that service
resolves its provider-owned connection; no credential values or SQLite file
move between processes. `lean-review install --platform opencode` links the V2
agent Markdown and global plugin entrypoint directly to canonical source;
`index.ts` imports the bounded tools from its sibling `reviewer.ts` without
an npm dependency tree. The V1 caller and Codex execution paths remain separate.

The reviewer session is created with the exact caller model reference and
deny-all session permissions, except Code Mode `execute` and the bounded
`lean_review_read/list/grep` actions. Its tool registry is shared by the
service, but tool execution is restricted to the verified reviewer session and
an immutable per-session repository binding. Agent/session/model/permissions
and canonical V2 agent instructions are read back before prompting. A context
hook replaces ambient system parts (project/global instructions and references)
with the verified canonical agent instructions and bounded Code Mode catalog;
it checks only those three tools, no MCP instructions, and no other direct tool
before the first model request. This is session/agent/tool/instruction isolation, not a
separate OS process. The launcher rechecks the artifact and canonical bytes
when the reviewer finishes; unsupported resume bindings fail closed.

## Codex

The `lean-review-codex` caller binds `runtime_adapter=codex` and delegates to
the generic `lean-review` launcher. New reviews use the caller-bound current
model or an explicit `--model` override when provided. If neither is set, Codex
starts without a model override and the launcher binds the effective model from
the current persisted turn context. An incompatible caller adapter or malformed
provided model is BLOCKED before the child process.

Canonical profiles set medium effort for lite and high effort for strict. Depth
changes effort and contract, not the selected model.

The selected model is never written into canonical assets. The launcher uses a new
runtime Git root and isolated `CODEX_HOME`, linking only the existing auth
file. User config/rules and project instructions are disabled; no project
configuration is inherited. It runs `codex exec --sandbox read-only` with
`approval_policy="never"`, disabled web search and delegation. The persisted
turn context must prove effective read-only/never before accepting a result.
A new review is BLOCKED when the current invocation does not report one
effective model, or reports a model different from the selected current/explicit
model. For strict fixes,
`exec resume` keeps the same thread and explicitly reapplies the saved observed
model and canonical read-only/never configuration; a current turn context is
still required. Startup/auth/isolation failures are BLOCKED.

## AGY

The canonical `assets/platforms/agy/spec-reviewer-*.md` contracts use only
`view_file` and `grep_search`, lite flash / strict pro. In known AGY CLI versions,
direct `--agent` invocation does not enforce the custom-agent tool allowlist.
A credible adapter needs an actual custom child and effective tool verification;
a writable parent or a post-hoc transcript alone is not a prevention boundary.
The initial launcher therefore returns BLOCKED. No profiles are installed into
projects or substituted with a general agent. No custom-agent mechanism is
substituted.

## Claude

The launcher materializes the canonical prompt at runtime, isolates user
configuration, disables hooks, automatic skills and MCP, and supplies only
Read/Grep/Glob with noninteractive permission denial. Bash is removed even
though the portable source contract allows read-only shell inspection.
It checks the effective initialization tool catalog before accepting a verdict.
The caller supplies the current model and it is pinned on resume. Init-reported
model is an observation, not
proof that an alias has immutable weights. Missing authentication is BLOCKED.
A separate global skill symlink is optional
because Claude uses its own skill discovery path.

## Hosted parents

Hosted parents can invoke the universal launcher using their current secure
runtime adapter. There is no invented custom-agent mechanism. Hosted parents
without an independent read-only backend likewise report BLOCKED.
