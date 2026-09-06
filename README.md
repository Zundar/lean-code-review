# Lean Code Review

A portable skill that chooses the smallest sufficient independent, read-only
review of a concrete change: **skip** for non-behavioral edits, **lite** for
bounded changes, **strict** for sensitive or high-impact changes. The parent
implements; one configured `spec-reviewer-lite` or `spec-reviewer-strict`
reviews the complete exact diff. The workflow is in [SKILL.md](SKILL.md).

## Install once

Python 3.11+, Git, and an authenticated supported reviewer CLI are required.
On WSL/Linux, keep one checkout and global discovery links:

```sh
git clone https://github.com/Zundar/lean-code-review ~/agent-skills/lean-code-review
cd ~/agent-skills/lean-code-review
python3 scripts/install.py install
lean-review doctor
```

Ensure `~/.local/bin` is on `PATH`. Installation creates only:

```text
~/.agents/skills/lean-code-review -> ~/agent-skills/lean-code-review
~/.local/bin/lean-review -> ~/agent-skills/lean-code-review/scripts/lean-review
```

OpenCode, Codex and Crush use global skill discovery. For Claude's separate
skill discovery, explicitly run `lean-review install --platform claude` to
add one global `~/.claude/skills/lean-code-review` symlink. No installer writes
into a project or replaces an existing foreign path. Reviewers use temporary
runtime profiles, never project-local copies.

## Review

Ask your parent agent to use `lean-code-review`. Its IDE need not match the
reviewer backend. Prepare an exact immutable diff with SHA-256, base, target,
task paths and focused evidence; see [adapter details](references/platform-adapters.md).

```sh
lean-review --backend auto --depth strict --repo /path/to/project \
  --artifact /private/review/diff.patch --sha256 "$digest" \
  --base "$base" --target "commit:$target" \
  --goal 'Fix the task-owned behavior' --task-paths 'path/to/file' \
  --requirements 'Preserve the public signature' --evidence 'Focused regression passed'
```

The artifact may instead describe `--target worktree`. The launcher verifies
its hash, creates a private immutable copy, sends the entire artifact as review
data, and binds its JSON result to the exact digest/base/target. Maximum input
is 1 MiB of UTF-8 diff, including Git binary patch records. It does not create
or infer a diff for you. Treat findings as exit 2 and **BLOCKED** as exit 1;
exit 0 requires exactly **PASS**. A CLI exit code alone is never PASS.

For a narrow fix, prepare a new artifact and pass `--resume <runtime>` with
the previous result's runtime directory. This retains the same reviewer
session, repository and depth. Runtime directories and private logs stay under
`~/.cache/lean-code-review/` for rechecks and diagnosis; remove only a completed
review's exact directory when you no longer need it.

## Backends

| Backend | Launcher contract |
| --- | --- |
| Codex | Separate persisted `exec` process; read-only sandbox, approvals never, isolated config, effective session verification |
| OpenCode | Fresh isolated HOME/XDG/config, canonical provider identity check, deny by default, bounded read/list/grep only |
| Claude | Canonical reviewer prompt, isolated config, only Read/Grep/Glob, no MCP or hooks, effective tool catalog verification |
| AGY | Canonical custom-agent contracts preserved; launcher returns BLOCKED until independent execution can be verified |
| Crush | Parent skill discovery supported; reviewer backend returns BLOCKED because no verified custom reviewer isolation is available |

`auto` selects the first installed backend in **Codex → OpenCode → Claude**
order. It never falls back after a runtime/isolation/authentication failure.
Explicit backend requests never switch silently. No `general` or `explore`
agent substitutes for a reviewer.

Optional local model overrides live outside this repository:

```toml
# ~/.config/lean-code-review/config.toml
[codex.strict]
model = "your-available-coding-model"

[opencode.strict]
model = "provider/model"
```

Canonical public profiles remain unchanged. Overrides cannot relax Codex
sandbox or approval policy.

## Check, extend, remove

`lean-review doctor --project /path/to/project` checks discovery links, PATH,
canonical assets and obvious project duplicates. Missing optional CLIs are
reported as unavailable. Backend availability is separate from authentication
and effective isolation: each actual review must pass its runtime preflight.

To add a backend, keep its specifics in `adapters/`, canonical profiles in
`assets/platforms/`, and runtime notes in `references/platform-adapters.md`.
Preserve the launcher packet/result contract. Require independent read-only
execution and representative negative tests before enabling it in `auto`.
Do not change the neutral workflow to mention a platform.

```sh
uv sync
uv run pytest -q
uv run ruff check .
lean-review uninstall
```

Uninstall removes only global symlinks still pointing to this checkout. It
preserves foreign paths, local settings, neighboring skills and runtime logs.
Licensed under [MIT](LICENSE).

## Development hooks

Enable the optional local commit check with `uvx pre-commit install`.
It runs `ruff check --no-fix` on staged Python files using Ruff from `uv.lock`;
lint errors block the commit without rewriting files. Run it manually with
`uvx pre-commit run --all-files`.
