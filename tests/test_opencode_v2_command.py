from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]


def test_opencode_v2_command_reports_results_and_bounded_failures(tmp_path: Path) -> None:
    node = shutil.which("node")
    if not node:
        pytest.skip("Node 24+ is unavailable")

    source = (ROOT / "assets/platforms/opencode-v2/index.ts").read_text(encoding="utf-8")
    source = source.replace(
        'import { Plugin } from "@opencode/plugin"',
        "const Plugin = { define: value => value }",
    ).replace("function runReview(", "export function runReview(")
    source = source.replace("const MAX_OUTPUT = 1024 * 1024", "const MAX_OUTPUT = 128")
    source = source.replace("const TIMEOUT_MS = 900_000", "const TIMEOUT_MS = 25")
    (tmp_path / "index.ts").write_text(source, encoding="utf-8")
    (tmp_path / "binding.mjs").write_text(
        (ROOT / "assets/platforms/opencode-v2/binding.mjs").read_text(encoding="utf-8"),
        encoding="utf-8",
    )

    runner = tmp_path / "runner.mjs"
    runner.write_text(
        '''import assert from "node:assert/strict"
import { runReview } from "./index.ts"
import { chmod, mkdir, writeFile } from "node:fs/promises"
import { join } from "node:path"

const bin = join(process.argv[2], "bin")
await mkdir(bin)
async function command(body, searchPath = `${bin}:/usr/bin:/bin`) {
  const executable = join(bin, "lean-review")
  await writeFile(executable, `#!/bin/sh\\n${body}\\n`)
  await chmod(executable, 0o700)
  return runReview([], { PATH: searchPath }, bin)
}

assert.equal(await command("printf 'plain output'"), "plain output")
assert.equal(await command(`printf '%s' '{"verdict":"PASS","summary":"ok"}'`),
  '{"verdict":"PASS","summary":"ok"}')
assert.equal(await command(`printf '%s' '{"verdict":"BLOCKED","reason":"preflight","apiKey":"private-value"}'; exit 1`),
  '{"verdict":"BLOCKED","reason":"preflight","apiKey":"[REDACTED]"}')
assert.equal(await command(`printf '%s' '{"verdict":"NEEDS_EVIDENCE","reason":"F1"}'; exit 2`),
  '{"verdict":"NEEDS_EVIDENCE","reason":"F1"}')
const usage = await command(`echo 'usage: lean-review --token private-value' >&2; echo 'error: bad option' >&2; exit 2`)
assert.match(usage, /usage: lean-review --token \\[REDACTED\\]/)
assert.match(usage, /bad option/)
assert.doesNotMatch(usage, /private-value/)
assert.equal(await command("sleep 2"), "lean-review OpenCode V2: timed out")
assert.equal(await command("head -c 256 /dev/zero | tr '\\\\000' x"),
  "lean-review OpenCode V2: output limit exceeded")
assert.equal(await command("kill -TERM $$"), "lean-review exited with SIGTERM")
assert.equal(await runReview([], { PATH: join(bin, "missing") }, bin),
  "lean-review could not start: ENOENT")
''',
        encoding="utf-8",
    )
    result = subprocess.run(
        [node, str(runner), str(tmp_path)], capture_output=True, text=True, timeout=10, check=False
    )
    assert result.returncode == 0, result.stderr
