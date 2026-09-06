from pathlib import Path
from typing import Any
import json
import pytest
REPO_ROOT = Path(__file__).resolve().parents[1]
ASSET_ROOT = REPO_ROOT / "assets/platforms/agy"
PROFILE_NAMES = ("spec-reviewer-lite", "spec-reviewer-strict")

NEEDS_ARTIFACT = (
    "NEEDS_EVIDENCE: provide the exact diff artifact with SHA-256, base, and target"
)

def test_skill_uses_git_range_only_with_effective_read_only_git_capability() -> None:
    skill = (REPO_ROOT / "SKILL.md").read_text(encoding="utf-8")

    assert "Use an immutable Git commit range only when the reviewer has an effective" in skill
    assert "read-only tool capable of inspecting the complete range" in skill
    assert "artifact path, digest, base, and target in REVIEW INPUT" in skill
    assert "`target:commit:<HEAD>`" in skill
    assert "`target:worktree`" in skill
    assert "PASS is invalid unless the reviewer actually inspected the complete REVIEW" in skill

@pytest.mark.parametrize("name", PROFILE_NAMES)
def test_agy_reviewer_fails_closed_when_git_range_is_inaccessible(name: str) -> None:
    profile = (ASSET_ROOT / f"{name}.md").read_text(encoding="utf-8")

    assert "Resolve REVIEW INPUT before reviewing or using any repository content tool." in profile
    assert "For artifact input, read the complete artifact with view_file." in profile
    assert NEEDS_ARTIFACT in profile
    assert "immediately without calling view_file or grep_search" in profile
    assert "Never infer the diff from current working-tree files." in profile
    assert "Never return PASS without\nreading the complete declared review input." in profile

def _artifact_view_result(events: list[dict[str, Any]], artifact: str) -> str:
    content = ""
    waiting_for_result = False
    for event in events:
        calls = event.get("tool_calls") or []
        if calls:
            waiting_for_result = any(
                call.get("name") == "view_file"
                and artifact in json.dumps(call.get("args", {}))
                for call in calls
            )
            continue
        if not waiting_for_result or event.get("type") != "GENERIC":
            continue
        waiting_for_result = False
        result_content = event.get("content", "")
        if artifact in result_content:
            content += result_content
    return content

def test_artifact_view_result_skips_failed_path_attempt() -> None:
    artifact = "tmp/lean-code-review/reviewer/diff.patch"
    events = [
        {"type": "PLANNER_RESPONSE", "tool_calls": [{"name": "view_file", "args": {"path": artifact}}]},
        {"type": "PLANNER_RESPONSE", "tool_calls": [{"name": "view_file", "args": {"path": artifact}}]},
        {"type": "GENERIC", "content": f"File Path: {artifact}\ncalc.py\ntest_calc.py"},
    ]

    assert _artifact_view_result(events, artifact).endswith("calc.py\ntest_calc.py")

def test_artifact_view_result_allows_intermediate_service_events() -> None:
    artifact = "tmp/lean-code-review/reviewer/diff.patch"
    events = [
        {"type": "PLANNER_RESPONSE", "tool_calls": [{"name": "view_file", "args": {"path": artifact}}]},
        {"type": "STEP_UPDATE", "content": "tool running"},
        {"type": "HEARTBEAT"},
        {"type": "GENERIC", "content": f"File Path: {artifact}\ncalc.py\ntest_calc.py"},
    ]

    assert _artifact_view_result(events, artifact).endswith("calc.py\ntest_calc.py")
