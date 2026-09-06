---
name: lean-code-review
description: Automatically choose the smallest sufficient independent read-only review for behavior-affecting repository changes. Use for concrete code, configuration, test, deployment, rollout, or bounded diff-review tasks; skip pure explanations and non-behavioral edits.
---

# Lean Code Review

Minimize reviewer calls. Review compatible changes together under one clear
contract and depth. Split only when combining changes prevents correct depth
selection or makes the contract ambiguous. Diff size, file count, and number of
risk domains alone are not reasons to split.

Choose by behavioral effect:

- `skip`: no meaningful behavior change.
- `lite` / `spec-reviewer-lite`: bounded, reversible changes without sensitive effects.
- `strict` / `spec-reviewer-strict`: high-impact or hard-to-reverse changes involving
  security, privacy, money, persistent state, concurrency, destructive actions,
  production side effects, or wide shared contracts.

Use strict preflight only when an unresolved contract risks costly or unsafe rework.
The main agent owns implementation, tests, fixes, publication, deployment, and live
verification. The independent reviewer is read-only and follows its configured profile.

Give the reviewer the exact diff, SHA-256, immutable base/target, contract, and
relevant evidence. Use a Git range only if the reviewer can read the complete
range; otherwise materialize an immutable artifact including new files. Use
`target:worktree` for exact uncommitted bytes. Do not send the full conversation
or unrelated logs. Input examples and isolation details: `references/platform-adapters.md`.

`PASS` covers only inspected bytes. Incomplete input requires `NEEDS_EVIDENCE`;
changed review bytes require review again. Accept material `Critical`/`Important`
findings, not style preferences or unrelated scope expansion. Resume the same
session only to fix its findings, with the fix diff and affected evidence.

Read `HISTORY.md` only when changing this skill or investigating its rationale.
