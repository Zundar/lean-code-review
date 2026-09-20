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
~/.local/bin/lean-review-codex -> ~/agent-skills/lean-code-review/scripts/lean-review-codex
```

OpenCode, Codex and Crush use global skill discovery. For Claude's separate
skill discovery, explicitly run `lean-review install --platform claude` to
add one global `~/.claude/skills/lean-code-review` symlink. No installer writes
into a project or replaces an existing foreign path. Reviewers use temporary
runtime profiles, never project-local copies.

## Review

Ask your parent agent to use `lean-code-review`. Its IDE need not match the
reviewer runtime. Prepare an exact immutable diff with SHA-256, base, target,
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
session, repository, depth and resolved runtime adapter/model. A resume ignores
changed caller context; an explicit conflicting model is BLOCKED.
Sessions without saved model/effort binding require a new review, not migration.
Runtime directories and private logs stay under
`~/.cache/lean-code-review/` for rechecks and diagnosis; remove only a completed
review's exact directory when you no longer need it.

When runtime counters are available, the result includes `usage` with `calls`,
`input_tokens`, `cached_input_tokens`, and `output_tokens`, summed across this
reviewer's session, including resumes. `calls` counts runtime invocations;
token counters retain their runtime's semantics. Usage comes only from existing
runtime event logs; if a call lacks counters, the aggregate is omitted.

## Runtime Adapters

| Runtime adapter | Launcher contract |
| --- | --- |
| Codex | Separate persisted `exec` process; read-only sandbox, approvals never, isolated config, effective session verification |
| OpenCode | Fresh isolated HOME/XDG/config, canonical provider identity check, deny by default, bounded read/list/grep only |
| Claude | Canonical reviewer prompt, isolated config, only Read/Grep/Glob, no MCP or hooks, effective tool catalog verification |

The parent integration binds the current executor context before invoking a new
review. The launcher does not expose that runtime adapter/model binding as a
user selector, and does not inspect installed executables, process state,
previous sessions, transcripts or mutable defaults to infer it. `--model` stays
inside the bound runtime adapter and must identify the allowed Luna model; it
never switches the executor. No fallback or adapter iteration occurs.

For Codex callers, use `lean-review-codex`; it binds `runtime_adapter=codex` and
delegates to `lean-review`. Every new or resumed Codex review explicitly pins
`gpt-5.6-luna`; another explicit model or saved model is BLOCKED before launch.

OpenCode preserves the bound provider and pins its model part to
`gpt-5.6-luna`; Codex uses medium/high effort by depth. Claude keeps its current
model contract and has no explicit effort setting here.

The existing `session.json` and result record the resolved `runtime_adapter`, `model`
and configured `reasoning_effort`. For Codex, `model` is the pinned Luna request
and `observed.model` must report the same effective model; missing, ambiguous, or
mismatched observations are BLOCKED. `observed.model` and
`observed.reasoning_effort` contain CLI-reported metadata; a requested model is
not proof of the provider's underlying weights.
OpenCode's current parsed events do not provide that observation. Mutable model
aliases may change upstream even while the requested identifier is pinned.

A resume uses only its saved runtime adapter/model/reasoning/session. A changed
caller executor does not change the resumed session. Switching model requires a
new independent session and does not dismiss previous findings.
Canonical prompts, tool restrictions and artifact/session checks remain unchanged.
For OpenCode, an available current provider definition is copied only as the
allowlisted HTTPS transport/model data needed by the isolated runtime; secrets,
plugins, MCP and project configuration are not imported.

## Check, extend, remove

`lean-review doctor --project /path/to/project` checks discovery links, PATH,
canonical assets and obvious project duplicates. Missing optional CLIs are
reported as unavailable. Runtime availability is separate from authentication
and effective isolation: each actual review must pass its runtime preflight.

To add a runtime adapter, keep its specifics in `adapters/`, canonical profiles
in `assets/platforms/`, and runtime notes in `references/platform-adapters.md`.
Preserve the launcher packet/result contract and require independent read-only
execution plus representative negative tests before exposing it to callers.
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
