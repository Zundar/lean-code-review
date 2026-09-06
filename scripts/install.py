#!/usr/bin/env python3
"""Address-specific, global-only skill installation. Python 3.11+."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
BACKENDS = ('opencode', 'codex', 'agy', 'crush', 'claude')
DUPLICATES = ('.agents/skills/lean-code-review', '.opencode/skills/lean-code-review',
              '.opencode/agents/spec-reviewer-*', '.agents/agents/spec-reviewer-*',
              '.opencode/tools/lean_review.ts')


def links(root: Path, home: Path, platforms: list[str]) -> dict[Path, Path]:
    result = {home / '.agents/skills/lean-code-review': root,
              home / '.local/bin/lean-review': root / 'scripts/lean-review'}
    # Claude does not share the universal agents skill discovery path.
    if 'claude' in platforms:
        result[home / '.claude/skills/lean-code-review'] = root
    return result


def owned(path: Path, target: Path) -> bool:
    return path.is_symlink() and path.resolve() == target.resolve()


def collision(path: Path, target: Path) -> bool:
    return os.path.lexists(path) and not owned(path, target)


def check_parents(path: Path, home: Path) -> None:
    for parent in path.parents:
        if parent == home:
            break
        if parent.is_symlink():
            raise ValueError(f'foreign symlinked config parent: {parent}')


def install(root: Path, home: Path, platforms: list[str]) -> None:
    planned = links(root, home, platforms)
    for path, target in planned.items():
        check_parents(path, home)
        if not target.exists():
            raise ValueError(f'missing canonical source: {target}')
        if collision(path, target):
            raise ValueError(f'foreign path collision: {path}')
    for path, target in planned.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        if not owned(path, target):
            path.symlink_to(target, target_is_directory=target.is_dir())


def uninstall(root: Path, home: Path) -> None:
    planned = links(root, home, ['claude'])
    for path in planned:
        check_parents(path, home)
    for path, target in planned.items():
        if owned(path, target):
            path.unlink()


def doctor(root: Path, home: Path, projects: list[Path]) -> dict:
    errors = []
    for path, target in links(root, home, []).items():
        try:
            check_parents(path, home)
        except ValueError as exc:
            errors.append(str(exc))
        if not owned(path, target) or not path.exists():
            errors.append(f'missing, broken or mismatched link: {path}')
    found = shutil.which('lean-review')
    if not found or Path(found).resolve() != root / 'scripts/lean-review':
        errors.append('lean-review on PATH does not resolve to this checkout')
    for platform in ('codex', 'opencode', 'agy', 'claude'):
        suffix = 'toml' if platform == 'codex' else 'md'
        for depth in ('lite', 'strict'):
            path = root / f'assets/platforms/{platform}/spec-reviewer-{depth}.{suffix}'
            if not path.is_file():
                errors.append(f'missing canonical reviewer: {path}')
    for path in ('SKILL.md', 'adapters/runtime.py', 'scripts/check_opencode_lean_review.py'):
        if not (root / path).is_file():
            errors.append(f'missing adapter/skill: {path}')
    for project in projects:
        for pattern in DUPLICATES:
            for path in project.glob(pattern):
                errors.append(f'project-local duplicate: {path}')
    statuses = {}
    for backend in BACKENDS:
        if not shutil.which(backend):
            statuses[backend] = 'unavailable: CLI not installed'
        elif backend in ('agy', 'crush'):
            statuses[backend] = 'BLOCKED: no verified independent read-only launcher boundary'
        else:
            statuses[backend] = 'available: per-review isolation preflight required'
    return {'ok': not errors, 'checkout': str(root), 'errors': errors, 'backends': statuses}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('install', 'doctor', 'uninstall'))
    parser.add_argument('--platform', choices=BACKENDS, action='append', default=[])
    parser.add_argument('--project', type=Path, action='append', default=[])
    args = parser.parse_args(argv)
    try:
        if args.action == 'install':
            install(ROOT, Path.home(), args.platform)
        elif args.action == 'uninstall':
            uninstall(ROOT, Path.home())
        else:
            result = doctor(ROOT, Path.home(), args.project or [Path.cwd()])
            print(json.dumps(result, indent=2))
            return 0 if result['ok'] else 1
    except (OSError, ValueError) as exc:
        print(f'BLOCKED: {exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
