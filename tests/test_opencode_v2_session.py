"""The V2 command must bind a separate reviewer session before model dispatch."""
from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('failure', ['none', 'catalog', 'mcp', 'scoped-allow', 'model-drift'])
def test_v2_session_binding_and_effective_catalog(tmp_path: Path, failure: str) -> None:
    node = shutil.which('node')
    if not node:
        pytest.skip('Node 24+ is unavailable')
    source = (ROOT / 'assets/platforms/opencode-v2/index.ts').read_text()
    source = source.replace('import { Plugin } from "@opencode/plugin"',
                            'const Plugin = { define: value => value }')
    source = source.replace('import { registerReviewerTools } from "./reviewer.ts"',
                            'const registerReviewerTools = async () => {}')
    (tmp_path / 'index.ts').write_text(source)
    (tmp_path / 'binding.mjs').write_bytes((ROOT / 'assets/platforms/opencode-v2/binding.mjs').read_bytes())
    bin_dir = tmp_path / 'bin'
    bin_dir.mkdir()
    executable = bin_dir / 'lean-review'
    executable.write_text('''#!/bin/sh
if [ "$1" = v2-prepare ]; then
  printf '%s' '{"runtime":"/private/review","repo":"/review/repo","model":"openai/model-a","packet":"immutable packet"}'
else
  cat >/dev/null
  printf '%s' '{"verdict":"PASS","session":"ses_reviewer"}'
fi
''')
    executable.chmod(0o700)
    runner = tmp_path / 'runner.mjs'
    runner.write_text('''import assert from "node:assert/strict"
import { LeanReviewV2 } from "./index.ts"

const model = { providerID: "openai", id: "model-a", variant: "medium" }
const rules = [{ action: "*", resource: "*", effect: "deny" },
  ...["execute", "lean_review_read", "lean_review_list", "lean_review_grep"]
    .map(action => ({ action, resource: "*", effect: "allow" }))]
if (process.argv[2] === "scoped-allow") rules.push({ action: "shell", resource: "/tmp/*", effect: "allow" })
let command, hook, created, prompted = false, outcome
const ctx = {
  app: { version: "2.0.14" }, location: { directory: process.argv[3] },
  command: { transform: async fn => fn({ add: definition => { command = definition } }) },
  tool: { list: async () => ({ data: rules.slice(1).map(rule => ({ id: rule.action })) }) },
  agent: { get: async () => ({ data: { id: "spec-reviewer-lite", mode: "primary", permissions: rules } }) },
  provider: { get: async () => ({ data: { id: "openai", package: "@opencode/ai/providers/openai",
    settings: { baseURL: "https://chatgpt.com/backend-api/codex" } } }) },
  model: { list: async () => ({ data: [{ ...model, variants: [{ id: "medium" }] }] }) },
  mcp: { list: async () => ({ data: [{ name: "installed-but-denied" }] }) },
  session: {
    get: async ({ sessionID }) => ({ data: sessionID === "ses_parent"
      ? { id: sessionID, model } : { ...created, id: sessionID } }),
    create: async input => ({ data: created = { ...input, id: "ses_reviewer" } }),
    hook: async (_, callback) => { hook = callback },
    prompt: async () => {
      prompted = true
      hook({ sessionID: "ses_reviewer", agent: "spec-reviewer-lite", model,
        system: [{ text: `# Code Mode\\nThe catalog is complete.\\n## Available tools\\n\\n- lean_review (3 tools)\\n  - tools.lean_review.read()\\n  - tools.lean_review.list()\\n  - tools.lean_review.grep()${process.argv[2] === "catalog" ? "\\n- shell (1 tool)" : ""}${process.argv[2] === "mcp" ? "\\n<mcp_instructions>unexpected</mcp_instructions>" : ""}` }],
        tools: { execute: {} } })
    },
    wait: async () => {},
    context: async () => ({ data: [
      ...(process.argv[2] === "model-drift" ? [{ type: "assistant", finish: "tool-calls",
        model: { ...model, variant: "high" }, tokens: { input: 10, output: 1, cache: { read: 0 } } }] : []),
      { type: "assistant", finish: "stop", model,
        content: [{ type: "text", text: "PASS" }], tokens: { input: 10, output: 1, cache: { read: 0 } } }] }),
    synthetic: async ({ text }) => { outcome = JSON.parse(text) },
  },
}
await LeanReviewV2.setup(ctx)
await command.execute({ sessionID: "ses_parent", prompt: { text: "--depth lite --repo /review/repo" } })
assert.equal(outcome.verdict, process.argv[2] === "none" ? "PASS" : "BLOCKED", outcome.reason)
if (process.argv[2] === "scoped-allow") { assert.equal(created, undefined); assert.equal(prompted, false) }
else { assert.equal(created.agent, "spec-reviewer-lite"); assert.deepEqual(created.model, model) }
if (process.argv[2] === "scoped-allow") process.exit(0)
assert.equal(created.agent, "spec-reviewer-lite")
assert.deepEqual(created.model, model)
assert.deepEqual(created.permissions, rules)
assert.equal(prompted, true)
''')
    result = subprocess.run([node, str(runner), failure, str(tmp_path)],
                            env={'PATH': f'{bin_dir}:/usr/bin:/bin', 'HOME': str(tmp_path)},
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr


def test_v2_bounded_tools_use_session_bound_repo_and_codemode_result(tmp_path: Path) -> None:
    node = shutil.which('node')
    if not node:
        pytest.skip('Node 24+ is unavailable')
    repo = tmp_path / 'repo'
    repo.mkdir()
    (repo / 'safe.txt').write_text('review evidence')
    (repo / '.env').write_text('do not show')
    source = (ROOT / 'assets/platforms/opencode-v2/reviewer.ts').read_text().replace(
        'import { Plugin } from "@opencode/plugin"', 'const Plugin = { define: value => value }')
    (tmp_path / 'reviewer.ts').write_text(source)
    runner = tmp_path / 'tools.mjs'
    runner.write_text('''import assert from "node:assert/strict"
import { registerReviewerTools } from "./reviewer.ts"
const tools = {}
await registerReviewerTools({ tool: { transform: async fn => fn({
  namespace: () => {}, add: tool => { tools[tool.name] = tool },
}) } }, id => id === "ses_review" ? process.argv[2] : undefined)
const context = { sessionID: "ses_review" }
assert.match((await tools.read.execute({path: "safe.txt"}, context)).content, /review evidence/)
assert.match((await tools.list.execute({path: "."}, context)).content, /safe.txt/)
assert.match((await tools.grep.execute({path: "safe.txt", query: "evidence"}, context)).content, /safe.txt:1/)
await assert.rejects(tools.read.execute({path: "safe.txt"}, {sessionID: "ses_other"}), /target repository/)
await assert.rejects(tools.read.execute({path: ".env"}, context), /restricted path/)
await assert.rejects(tools.read.execute({path: "../outside"}, context), /outside the project/)
''')
    result = subprocess.run([node, str(runner), str(repo)], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
