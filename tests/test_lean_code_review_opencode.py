from pathlib import Path
import shutil
import subprocess
import pytest
import yaml
REPO_ROOT = Path(__file__).resolve().parents[1]
ASSET_ROOT = REPO_ROOT / "assets/platforms"

PROFILE_NAMES = ("spec-reviewer-lite", "spec-reviewer-strict")

LITE_REVIEW_CONTRACT = (
    "Treat MUST invariants as properties to falsify, not implementation recipes;",
    "check boundary/config override cases when they can violate the stated invariant.",
    "When changed code owns or receives a transaction/resource context, inspect the",
    "immediate lifecycle helper to detect duplicate commit/close/rollback ownership.",
)

STRICT_PREFLIGHT_CONTRACT = (
    "For preflight, inspect only the unresolved contract or seam. Persistent-state "
    "mutation: only target identity, allowed writes, preserved truth, and "
    "ambiguous/no-match behavior. Architecture risk: only canonical source of truth, "
    "responsibility owner, established dependency direction, and nearest existing "
    "mechanism. Return CONTRACT_PASS unless a concrete missing decision risks "
    "material rework; otherwise report at most three material missing decisions."
)

def test_lite_reviewers_cover_invariant_and_resource_ownership() -> None:
    profiles = (("agy", "md"), ("claude", "md"), ("codex", "toml"), ("opencode", "md"))
    for platform, suffix in profiles:
        profile = (ASSET_ROOT / platform / f"spec-reviewer-lite.{suffix}").read_text(
            encoding="utf-8"
        )
        for requirement in LITE_REVIEW_CONTRACT:
            assert requirement in profile

def test_strict_preflight_is_exceptional_and_contract_bounded() -> None:
    skill = " ".join(
        (REPO_ROOT / "SKILL.md").read_text(encoding="utf-8").split()
    )
    assert "`strict` gets one final review by default." in skill
    assert (
        "persistent-state mutation with unclear target identity, allowed writes, "
        "preserved truth, or ambiguous/no-match behavior. Otherwise skip it."
    ) in skill
    assert "a new source of truth or shared mechanism with unclear ownership" in skill
    assert "Review only the unresolved contract or seam" in skill

    for profile in sorted(ASSET_ROOT.glob("*/spec-reviewer-strict.*")):
        compact = " ".join(profile.read_text(encoding="utf-8").split())
        assert STRICT_PREFLIGHT_CONTRACT in compact
        assert "For final review, return exactly PASS" in compact

def _profile(name: str) -> tuple[dict[str, object], str]:
    text = (ASSET_ROOT / "opencode" / f"{name}.md").read_text(encoding="utf-8")
    start, frontmatter, body = text.split("---", 2)
    assert not start
    return yaml.safe_load(frontmatter), body

def test_opencode_grep_runtime_bounds_empty_trees_and_oversized_files(tmp_path: Path) -> None:
    node = shutil.which("node")
    if not node:
        pytest.skip("Node 24+ is unavailable")

    source = (REPO_ROOT / "assets/platforms/opencode/lean_review.ts").read_text(encoding="utf-8")
    source = source.replace(
        'import { tool, type ToolContext } from "@opencode-ai/plugin"',
        """type ToolContext = { worktree: string }
const chain: any = { min() { return this }, max() { return this }, int() { return this }, describe() { return this }, default() { return this } }
const tool: any = Object.assign((value: any) => value, { schema: { string: () => chain, number: () => chain, boolean: () => chain } })""",
    )
    module = tmp_path / "lean_review.ts"
    module.write_text(source, encoding="utf-8")
    runner = tmp_path / "runner.mjs"
    runner.write_text(
        """import * as tools from './lean_review.ts'
const grep = tools.grep ?? tools.default.grep
const [root, target] = process.argv.slice(2)
try {
  console.log(await grep.execute({ path: target, query: 'needle', case_sensitive: true }, { worktree: root }))
} catch (error) {
  console.error(String(error))
  process.exit(7)
}
""",
        encoding="utf-8",
    )

    worktree = tmp_path / "worktree"
    empty_tree = worktree / "empty-tree"
    empty_tree.mkdir(parents=True)
    for index in range(513):
        (empty_tree / f"d{index:03d}").mkdir()
    overflow = subprocess.run(
        (str(node), str(runner), str(worktree), "empty-tree"),
        check=False,
        capture_output=True,
        text=True,
    )
    assert overflow.returncode == 7
    assert "search exceeds 512 entries" in overflow.stderr

    oversized = worktree / "oversized.txt"
    oversized.write_bytes(b"x" * (1024 * 1024 + 1))
    direct = subprocess.run(
        (str(node), str(runner), str(worktree), "oversized.txt"),
        check=False,
        capture_output=True,
        text=True,
    )
    assert direct.returncode == 7
    assert "grep target was not searched: oversized" in direct.stderr

    recursive = worktree / "recursive"
    recursive.mkdir()
    (recursive / "small.txt").write_text("no match\n", encoding="utf-8")
    (recursive / "oversized.txt").write_bytes(oversized.read_bytes())
    bounded = subprocess.run(
        (str(node), str(runner), str(worktree), "recursive"),
        check=True,
        capture_output=True,
        text=True,
    )
    assert "files=1 matches=0 omitted=1 truncated=false" in bounded.stdout

def test_all_reviewer_profiles_bind_pass_to_exact_review_input() -> None:
    profiles = sorted(ASSET_ROOT.glob("*/spec-reviewer-*"))
    assert len(profiles) == 8
    for profile in profiles:
        text = profile.read_text(encoding="utf-8")
        assert "Bind PASS only to the exact REVIEW INPUT supplied by the parent" in text
        assert "exact diff artifact identified by SHA-256, base commit, and" in text
        assert "target (`commit:<HEAD>` or `worktree`)" in text
        assert "actual SHA-256 against the packet" in text
        assert "bind PASS to the declared digest" in text
        assert "BASE/REVIEW_HEAD pair" not in text


def test_bounded_tools_deny_secrets_outside_and_symlinks(tmp_path):
    node = shutil.which('node')
    if not node:
        pytest.skip('Node 24+ required')
    source = (ASSET_ROOT / 'opencode/lean_review.ts').read_text()
    source = source.replace('import { tool, type ToolContext } from "@opencode-ai/plugin"', '''type ToolContext = {worktree: string}
const chain: any = new Proxy({}, {get: () => () => chain})
const tool: any = Object.assign((v: any) => v, {schema: new Proxy({}, {get: () => () => chain})})''')
    (tmp_path / 'tool.ts').write_text(source)
    (tmp_path / 'runner.mjs').write_text('''import * as tool from './tool.ts';
const [root, operation, path] = process.argv.slice(2);
try { console.log(await tool[operation].execute({path,query:'needle'}, {worktree:root})); }
catch(e) { console.error(String(e)); process.exit(7); }
''')
    root = tmp_path / 'repo'
    root.mkdir()
    (root / 'ok.txt').write_text('needle')
    (root / '.env').write_text('needle')
    (root / 'credentials').mkdir()
    (root / 'credentials/secret').write_text('needle')
    (root / 'link').symlink_to(root / 'ok.txt')
    (tmp_path / 'outside').write_text('needle')
    for operation in ('read', 'grep'):
        for path in ('.env', 'credentials/secret', '../outside', str(tmp_path / 'outside'), 'link'):
            p = subprocess.run([node, str(tmp_path/'runner.mjs'),str(root),operation,path], capture_output=True, text=True, check=False)
            assert p.returncode == 7, (operation, path, p.stdout, p.stderr)
        p = subprocess.run([node,str(tmp_path/'runner.mjs'),str(root),operation,'ok.txt'], capture_output=True, text=True, check=True)
        assert 'needle' in p.stdout
