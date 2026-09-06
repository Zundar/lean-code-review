---
name: lean-code-review
description: Automatically choose the smallest sufficient independent read-only review for behavior-affecting repository changes. Use for concrete code, configuration, test, deployment, rollout, or bounded diff-review tasks; skip pure explanations and non-behavioral edits.
---

# Lean Code Review

The main agent owns implementation. The reviewer only verifies the task and
never implements or edits it. Review depth is automatic.

## Review depth

Choose by material effect and blast radius, not directory or filename.

- `skip`: no meaningful behavioral effect: docs-only, formatting, comments,
  generated metadata, or an obviously mechanical edit.
- `lite`: default for bounded, reversible fixes, small features, CI/config
  changes, and shared contracts with limited blast radius and no sensitive
  effects.
- `strict`: high-impact or hard-to-reverse changes involving security/auth/
  privacy, money/trust, persistent state or schema/migrations, concurrency,
  destructive actions, production side effects, or a wide public/shared
  contract.

Repository risk tiers are supporting evidence, not policy to duplicate here.

## Strict preflight is exceptional

`strict` gets one final review by default. Preflight only when a missing decision
could cause costly or unsafe rework: ambiguous acceptance; destructive or
irreversible behavior; migration ambiguity; unclear security/auth/financial
transitions; a new source of truth or shared mechanism with unclear ownership;
or persistent-state mutation with unclear target identity, allowed writes,
preserved truth, or ambiguous/no-match behavior. Otherwise skip it.

Review only the unresolved contract or seam; reuse the same reviewer for final
review when supported.

## Implement and gather evidence

Follow repository instructions, preserve unrelated changes, implement the
smallest change, and run only relevant repository-required evidence. Testing
breadth, CI, publication, deployment, rollback, and live verification remain
repository/task responsibilities, not this skill's workflow.

## Small review packet

Bind review to the exact bytes actually inspected.

- Use an immutable Git commit range only when the reviewer has an effective
  read-only tool capable of inspecting the complete range.
- Otherwise the parent must materialize the complete task-owned diff, including
  new files, save it as an immutable artifact, calculate its SHA-256, and pass
  the artifact path, digest, base, and target in REVIEW INPUT. Use
  `target:commit:<HEAD>` for committed bytes and `target:worktree` for exact
  staged, unstaged, and untracked bytes.
- If the reviewer cannot access the complete declared input, it must return
  NEEDS_EVIDENCE and must not return PASS.

```text
GOAL: <1-2 sentences>

MUST / MUST NOT:
- <material requirement or prohibition>

REVIEW INPUT:
- git:<BASE>..<HEAD>
  OR
- artifact:<project-relative path>
  sha256:<digest>
  base:<BASE>
  target:commit:<HEAD>
  OR
  target:worktree

TASK PATHS:
- <task-owned path or symbol>

EVIDENCE:
- <focused relevant check and result>
```

PASS is invalid unless the reviewer actually inspected the complete REVIEW
INPUT. Do not reconstruct a diff from current files or trust the parent's
summary. Do not guess unlinked reference filenames.

Do not copy the full conversation, successful logs, or unrelated context.

## One independent reviewer

Use exactly one configured reviewer:
- `spec-reviewer-lite` for `lite`;
- `spec-reviewer-strict` for `strict`.

The reviewer must be effectively read-only. Use configured isolation; read
`references/platform-adapters.md` only for installation, troubleshooting, or
when isolation cannot be established. Without a credible read-only boundary,
the verdict is not independent review.

The reviewer profile owns the detailed checklist. It must inspect the complete
task-owned diff and only nearby code needed to judge it. Changed predicates or
state transitions need evidence for the changed case and nearest preserved case
when applicable.

Accept only `PASS`, one concrete `NEEDS_EVIDENCE` request, or material
`Critical`/`Important` findings bounded by the reviewer profile. Reject
style-only findings, unrelated refactors, scope expansion, and broad test reruns
without a concrete missing risk.

## Narrow recheck

The main agent owns fixes. Apply the smallest correction, rerun affected
evidence, and use the same reviewer for one recheck. A second strict recheck is
allowed only if the first fix materially changes sensitive behavior or the
original risk surface; otherwise report unresolved findings.

`PASS` applies only to the exact `REVIEW INPUT`. A changed commit range or a
changed diff artifact/hash requires a new final review; unrelated descendants do
not. Review ends at `PASS`; publication, integration, deployment, and live-state
handling belong to the parent agent and repository policy.

Read `HISTORY.md` only when changing this skill or investigating its rationale.
