# Platform adapters

Read this file for installation, runtime troubleshooting or isolation checks.
The shared workflow is platform-neutral. The sole launcher is `lean-review`;
its backend is independent of the parent IDE. Use one global checkout and
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

## OpenCode

The adapter targets the OpenCode 1.x permission/bash/task contract. Each review
uses a new runtime Git root outside the target repository, separate HOME,
XDG config/cache/state, and external skill scans disabled. Only the existing authentication file is linked into the isolated XDG data store. Inherited OpenCode config overrides are
removed. The target repository's `.opencode` files never load.

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
canonical profile/provider identity blocks session reuse. Retain runtime
folders until final PASS; cleanup is always address-specific.

## Codex

Canonical profiles select an economical coding model with medium effort for
lite and a strong coding model with high effort for strict. A user may override
only the model in `~/.config/lean-code-review/config.toml`, for example:

```toml
[codex.strict]
model = "gpt-5.6-sol"
```

The override is never written into canonical assets. The launcher uses a new
runtime Git root and isolated `CODEX_HOME`, linking only the existing auth
file. User config/rules and project instructions are disabled; no project
configuration is inherited. It runs `codex exec --sandbox read-only` with
`approval_policy="never"`, disabled web search and delegation. The persisted
turn context must prove effective read-only/never before accepting a result.
For strict fixes, `exec resume` keeps the same thread and explicitly reapplies
the read-only/never configuration. Startup/auth/isolation failures are BLOCKED.

## AGY

The canonical `assets/platforms/agy/spec-reviewer-*.md` contracts use only
`view_file` and `grep_search`, lite flash / strict pro. In known AGY CLI versions,
direct `--agent` invocation does not enforce the custom-agent tool allowlist.
A credible adapter needs an actual custom child and effective tool verification;
a writable parent or a post-hoc transcript alone is not a prevention boundary.
The initial launcher therefore returns BLOCKED. No profiles are installed into
projects or substituted with a general agent. Select an available supported
backend explicitly or use the documented auto policy.

## Claude

The launcher materializes the canonical prompt at runtime, isolates user
configuration, disables hooks, automatic skills and MCP, and supplies only
Read/Grep/Glob with noninteractive permission denial. Bash is removed even
though the portable source contract allows read-only shell inspection.
It checks the effective initialization tool catalog before accepting a verdict.
Missing authentication is BLOCKED. A separate global skill symlink is optional
because Claude uses its own skill discovery path.

## Crush and hosted parents

Crush discovers the user-wide `.agents/skills` installation. Its parent can
invoke the universal launcher using another secure backend. `--backend crush`
returns BLOCKED; there is no invented custom-agent mechanism. Hosted parents
without an independent read-only backend likewise report BLOCKED.
