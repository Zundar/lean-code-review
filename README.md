# Lean Code Review

A portable skill that chooses the smallest sufficient independent, read-only
review of a concrete change: **skip** for non-behavioral edits, **lite** for
bounded changes, **strict** for sensitive or high-impact changes. The parent
implements; one configured `spec-reviewer-lite` or `spec-reviewer-strict`
reviews the complete declared diff. The workflow is in [SKILL.md](SKILL.md).

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
lean-review --depth strict --repo /path/to/project \
  --artifact /private/review/diff.patch --sha256 "$digest" \
  --base "$base" --target "commit:$target" \
  --goal 'Fix the task-owned behavior' --task-paths 'path/to/file' \
  --requirements 'Preserve the public signature' --evidence 'Focused regression passed'
```

The artifact may instead describe `--target worktree`. The launcher verifies
its hash, creates a private immutable copy, sends the entire artifact as review
data, and binds its JSON result to the exact digest/base/target. It does not
create or infer a diff for you. Treat findings as exit 2 and **BLOCKED** as exit 1;
exit 0 requires exactly **PASS**. A CLI exit code alone is never PASS.

For a narrow fix, prepare a new artifact and pass `--resume <runtime>` with
the previous result's runtime directory. This retains the same reviewer
session, repository, depth and selected backend/model. Changing local defaults
does not change a resume; explicit conflicting backend/model flags are BLOCKED.
Sessions without saved model/effort binding require a new review, not migration.
Runtime directories and private logs stay under
`~/.cache/lean-code-review/` for rechecks and diagnosis; remove only a completed
review's exact directory when you no longer need it.

When backend counters are available, the result includes `usage` with `calls`,
`input_tokens`, `cached_input_tokens`, and `output_tokens`, summed across this
reviewer's session, including resumes. `calls` counts backend invocations;
token counters retain their backend's semantics. Usage comes only from existing
runtime event logs; if a call lacks counters, the aggregate is omitted.

## Backends

| Backend | Launcher contract |
| --- | --- |
| Codex | Separate persisted `exec` process; read-only sandbox, approvals never, isolated config, effective session verification |
| OpenCode | Fresh isolated HOME/XDG/config, canonical provider identity check, deny by default, bounded read/list/grep only |
| Claude | Canonical reviewer prompt, isolated config, only Read/Grep/Glob, no MCP or hooks, effective tool catalog verification |
| AGY | Canonical custom-agent contracts preserved; launcher returns BLOCKED until independent execution can be verified |
| Crush | Parent skill discovery supported; reviewer backend returns BLOCKED because no verified custom reviewer isolation is available |

New reviews select the backend by explicit `--backend`, then local `backend`,
then `auto`. Explicit `--backend auto` uses the first installed CLI in
**Codex → OpenCode → Claude** order, regardless of the local preference. It
never falls back after a runtime/isolation/authentication failure. A selected
but unavailable backend is BLOCKED; no `general` or `explore` agent substitutes.

Local preferences live outside this repository:

```toml
# ~/.config/lean-code-review/config.toml
backend = "opencode"

[opencode]
model = "provider/model"

# Optional per-depth override:
# [opencode.strict]
# model = "other-provider/other-model"
```

Model precedence is `--model` → `[backend.depth].model` → `[backend].model` →
canonical/default model. Existing per-depth overrides still work. OpenCode has
no canonical model: it requires an explicit `provider/model` from CLI or local
settings instead of silently using a last-used/default model. Codex and Claude
keep their existing defaults. Unknown settings, invalid types and empty models
are BLOCKED; only backend/model selection is configurable, never permissions,
prompts or reasoning. Both depths may use one model with their distinct canonical
contracts and effort: OpenCode low/high, Codex medium/high; Claude has no explicit
effort setting here. Specifying a model does not configure a custom provider.

The existing `session.json` and result record the selected `backend`, `model`
and configured `reasoning_effort`. `observed.model` and
`observed.reasoning_effort` contain CLI-reported metadata when available, otherwise
`null`; a requested model is not proof of the provider's underlying weights.
OpenCode's current parsed events do not provide that observation. Mutable model
aliases may change upstream even while the requested identifier is pinned.

A resume uses only its saved selection: omitted backend or `auto` retains the
session's backend. New defaults affect only new sessions. Switching backend/model
requires a new independent session and does not dismiss previous findings.
Canonical prompts, tool restrictions and artifact/session checks remain unchanged.
For OpenCode, an available selected provider definition is copied only as the
allowlisted HTTPS transport/model data needed by the isolated runtime; secrets,
plugins, MCP and project configuration are not imported.

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
