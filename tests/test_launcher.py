import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from adapters import runtime as launch
from scripts import install
from scripts.check_opencode_lean_review import ALLOWED, CheckError, check

ROOT = Path(__file__).resolve().parents[1]


def test_neutral_workflow():
    text = (ROOT / 'SKILL.md').read_text()
    for literal in ('OpenCode', 'Codex', 'AGY', 'Crush', 'Claude', '~/', '.opencode', '.agents'):
        assert literal not in text
    assert '`spec-reviewer-lite`' in text and '`spec-reviewer-strict`' in text


def test_install_collision_idempotence_and_address_only_uninstall(tmp_path, monkeypatch):
    home = tmp_path / 'home'
    monkeypatch.setenv('PATH', f'{home}/.local/bin')
    install.install(ROOT, home, [])
    install.install(ROOT, home, [])
    assert install.doctor(ROOT, home, [tmp_path])['ok']
    launcher = home / '.local/bin/lean-review'
    launcher.unlink()
    launcher.write_text('foreign')
    assert not install.doctor(ROOT, home, [tmp_path])['ok']
    with pytest.raises(ValueError, match='collision'):
        install.install(ROOT, home, [])
    install.uninstall(ROOT, home)
    assert launcher.read_text() == 'foreign'
    assert not (home / '.agents/skills/lean-code-review').exists()
    install.uninstall(ROOT, home)


def test_install_preflights_all_links_before_writing(tmp_path):
    path = tmp_path / '.local/bin/lean-review'
    path.parent.mkdir(parents=True)
    path.symlink_to(tmp_path / 'missing')
    with pytest.raises(ValueError, match='collision'):
        install.install(ROOT, tmp_path, [])
    assert not (tmp_path / '.agents').exists()
    assert not install.doctor(ROOT, tmp_path, [])['ok']


def test_doctor_reports_project_copy(tmp_path, monkeypatch):
    home = tmp_path / 'home'
    install.install(ROOT, home, [])
    monkeypatch.setenv('PATH', f'{home}/.local/bin')
    repo = tmp_path / 'repo'
    path = repo / '.opencode/tools/lean_review.ts'
    path.parent.mkdir(parents=True)
    path.write_text('foreign tool')
    assert any('project-local duplicate' in e for e in install.doctor(ROOT, home, [repo])['errors'])
    assert path.read_text() == 'foreign tool'


def test_codex_override_is_local_and_read_only():
    original = (ROOT / 'assets/platforms/codex/spec-reviewer-strict.toml').read_bytes()
    config = {'codex': {'strict': {'model': 'local-model'}}}
    selection = launch.resolve_selection(ROOT, 'strict', 'codex', None, config)
    assert selection['model'] == 'local-model'
    assert (ROOT / 'assets/platforms/codex/spec-reviewer-strict.toml').read_bytes() == original
    for session in (None, 'existing-thread'):
        command = launch.codex_command(ROOT, ROOT, 'strict', selection, session)
        assert 'sandbox_mode="read-only"' in command and 'approval_policy="never"' in command
        assert '--ignore-user-config' in command and '--ignore-rules' in command
        assert 'model="local-model"' in command and 'model_reasoning_effort="high"' in command
        assert ('resume' in command) == bool(session)


def isolated(tmp_path, model=None):
    runtime = tmp_path / 'runtime'
    runtime.mkdir(mode=0o700)
    target = tmp_path / 'target'
    target.mkdir()
    env = launch.environment(runtime, target)
    launch.opencode_prepare(ROOT, runtime, 'strict', model)
    permissions = [{'permission': '*', 'pattern': '*', 'action': 'deny'}]
    permissions += [{'permission': name, 'pattern': '*', 'action': 'allow'} for name in ALLOWED]
    agent = {'tools': dict.fromkeys(ALLOWED, True), 'permission': permissions}
    return runtime, target, env, agent


def test_opencode_runtime_has_no_target_configuration_dependency(tmp_path):
    runtime, target, env, agent = isolated(tmp_path)
    assert not (target / '.opencode').exists()
    assert check(ROOT, runtime, env, {}, agent, 'strict')['ok']
    assert env['LEAN_REVIEW_TARGET_REPO'] == str(target)
    # A malicious project plugin is never a runtime provider.
    bad = target / '.opencode/plugins/evil.ts'
    bad.parent.mkdir(parents=True)
    bad.write_text('throw new Error("must not load")')
    assert check(ROOT, runtime, env, {}, agent, 'strict')['ok']
    for config in ({'mcp': {'evil': {}}}, {'plugin_origins': ['evil']}, {'plugin': ['evil']}):
        with pytest.raises(CheckError):
            check(ROOT, runtime, env, config, agent, 'strict')
    agent['tools']['bash'] = True
    with pytest.raises(CheckError, match='isolation mismatch'):
        check(ROOT, runtime, env, {}, agent, 'strict')


def test_opencode_selected_transport_is_allowlisted(tmp_path, monkeypatch):
    import subprocess
    runtime = tmp_path / 'runtime'
    runtime.mkdir(mode=0o700)
    target = tmp_path / 'target'
    target.mkdir()
    env = launch.environment(runtime, target)
    permissions = [{'permission': '*', 'pattern': '*', 'action': 'deny'}]
    permissions += [{'permission': name, 'pattern': '*', 'action': 'allow'} for name in ALLOWED]
    agent = {'tools': dict.fromkeys(ALLOWED, True), 'permission': permissions}
    original_run = subprocess.run
    source_base_url = ['https://provider.example/v1']

    def source_config(argv, *args, **kwargs):
        if argv[:3] == ['opencode', 'debug', 'config']:
            payload = {
                'provider': {
                    'vendor': {
                        'npm': '@ai-sdk/openai-compatible',
                        'options': {'baseURL': source_base_url[0]},
                        'models': {
                            'model': {
                                'name': 'GPT-5.6 Luna', 'reasoning': True,
                                'limit': {'context': 272000, 'output': 128000, 'foreign': 'drop'},
                                'variants': {
                                    'low': {'reasoningEffort': 'low'},
                                    'medium': {'reasoningEffort': 'medium'},
                                    'high': {'reasoningEffort': 'high', 'apiKey': 'drop'},
                                    'xhigh': {'reasoningEffort': 'xhigh'},
                                    'max': {'reasoningEffort': 'max'},
                                },
                            },
                        },
                    },
                },
            }
            return SimpleNamespace(stdout=json.dumps(payload))
        return original_run(argv, *args, **kwargs)

    monkeypatch.setattr(launch.subprocess, 'run', source_config)
    launch.opencode_prepare(ROOT, runtime, 'strict', 'vendor/model')
    assert check(ROOT, runtime, env, {}, agent, 'strict', 'vendor/model')['ok']
    config = json.loads((runtime / 'config/opencode/opencode.json').read_text())
    assert config['provider'] == {'vendor': {
        'npm': '@ai-sdk/openai-compatible',
        'options': {'baseURL': 'https://provider.example/v1'},
        'models': {'model': {
            'name': 'GPT-5.6 Luna', 'reasoning': True,
            'limit': {'context': 272000, 'output': 128000},
            'variants': {
                'low': {'reasoningEffort': 'low'},
                'medium': {'reasoningEffort': 'medium'},
                'high': {'reasoningEffort': 'high'},
                'xhigh': {'reasoningEffort': 'xhigh'},
                'max': {'reasoningEffort': 'max'}}}}}}
    assert not (target / '.opencode').exists()
    for index, bad_url in enumerate(('https://user:secret@provider.example/v1',
                                     'https://provider.example/v1?api_key=secret')):
        source_base_url[0] = bad_url
        bad_runtime = tmp_path / f'bad-{index}'
        bad_runtime.mkdir(mode=0o700)
        launch.environment(bad_runtime, target)
        with pytest.raises(launch.Blocked, match='provider/model metadata'):
            launch.opencode_prepare(ROOT, bad_runtime, 'strict', 'vendor/model')
    source_base_url[0] = 'https://provider.example/v1'
    config['provider']['vendor']['options']['apiKey'] = 'must-reject'
    (runtime / 'config/opencode/opencode.json').write_text(json.dumps(config))
    with pytest.raises(CheckError, match='noncanonical'):
        check(ROOT, runtime, env, {}, agent, 'strict', 'vendor/model')
    config['provider']['vendor']['options'].pop('apiKey')
    for bad_url in ('https://user:secret@provider.example/v1',
                    'https://provider.example/v1?api_key=secret'):
        config['provider']['vendor']['options']['baseURL'] = bad_url
        (runtime / 'config/opencode/opencode.json').write_text(json.dumps(config))
        with pytest.raises(CheckError, match='noncanonical'):
            check(ROOT, runtime, env, {}, agent, 'strict', 'vendor/model')
    config['provider']['vendor']['options']['baseURL'] = 'https://provider.example/v1'
    config['provider']['vendor']['models']['model']['variants']['high']['apiKey'] = 'must-reject'
    (runtime / 'config/opencode/opencode.json').write_text(json.dumps(config))
    with pytest.raises(CheckError, match='variants'):
        check(ROOT, runtime, env, {}, agent, 'strict', 'vendor/model')
    config['permission'] = {'*': 'allow'}
    (runtime / 'config/opencode/opencode.json').write_text(json.dumps(config))
    with pytest.raises(CheckError, match='noncanonical'):
        check(ROOT, runtime, env, {}, agent, 'strict', 'vendor/model')


def test_runtime_bytes_mismatch_blocks_before_provider_execution(tmp_path):
    runtime, _, env, agent = isolated(tmp_path)
    tool = runtime / 'config/opencode/tools/lean_review.ts'
    tool.write_text('foreign')
    with pytest.raises(CheckError, match='runtime bytes'):
        check(ROOT, runtime, env, {}, agent, 'strict')


def test_opencode_deny_by_default():
    for depth in ('lite', 'strict'):
        front = yaml.safe_load((ROOT / f'assets/platforms/opencode/spec-reviewer-{depth}.md').read_text().split('---')[1])
        permissions = front['permission']
        assert permissions['*'] == 'deny'
        assert all(permissions[k] == 'allow' for k in ALLOWED)
        assert all(permissions[k] == 'deny' for k in ('read', 'glob', 'grep', 'bash', 'task', 'edit', 'webfetch', 'websearch'))
        assert permissions['external_directory']['*'] == 'deny'


def test_artifact_mismatch_and_unsupported_backends_fail_closed(tmp_path):
    import subprocess
    subprocess.run(['git', 'init', '-q', str(tmp_path)], check=True)
    artifact = tmp_path / 'diff.patch'
    artifact.write_text('exact diff')
    args = SimpleNamespace(repo=tmp_path, artifact=artifact, sha256='0' * 64,
                           base='0' * 40, target='worktree', backend='crush', depth='lite', model=None, resume=None)
    with pytest.raises(launch.Blocked, match='SHA-256 mismatch'):
        launch.review(args)
    args.sha256 = hashlib.sha256(artifact.read_bytes()).hexdigest()
    with pytest.raises(launch.Blocked, match='independent read-only'):
        launch.review(args)
    assert artifact.read_text() == 'exact diff'


def test_codex_effective_writable_session_rejected(tmp_path):
    path = tmp_path / 'codex/sessions/run.jsonl'
    path.parent.mkdir(parents=True)
    events = [{'type': 'thread.started', 'thread_id': 'id'},
              {'type': 'item.completed', 'item': {'type': 'agent_message', 'text': 'PASS'}}]
    path.write_text(json.dumps({'type': 'turn_context', 'payload': {
        'sandbox_policy': {'type': 'danger-full-access'}, 'approval_policy': 'never'}}))
    with pytest.raises(launch.Blocked, match='effective session'):
        launch.codex_result(events, tmp_path)


def test_opencode_trailing_external_allow_is_rejected(tmp_path):
    runtime, _, env, agent = isolated(tmp_path)
    agent['permission'].append({'permission': 'external_directory', 'pattern': '/cache/*', 'action': 'allow'})
    with pytest.raises(CheckError, match='external-directory'):
        check(ROOT, runtime, env, {}, agent, 'strict')


def test_installer_cannot_write_into_project_through_global_parent_link(tmp_path):
    home = tmp_path / 'home'
    project = tmp_path / 'project'
    home.mkdir()
    project.mkdir()
    (home / '.agents').symlink_to(project)
    with pytest.raises(ValueError, match='symlinked config parent'):
        install.install(ROOT, home, [])
    assert list(project.iterdir()) == []
    assert not install.doctor(ROOT, home, [])['ok']


def test_uninstall_preflights_parents_and_preserves_matching_project_links(tmp_path):
    home = tmp_path / 'home'
    project = tmp_path / 'project'
    install.install(ROOT, home, [])
    skill = home / '.agents/skills/lean-code-review'
    skill.unlink()
    (home / '.agents/skills').rmdir()
    (home / '.agents').rmdir()
    (project / 'skills').mkdir(parents=True)
    (home / '.agents').symlink_to(project)
    matching = project / 'skills/lean-code-review'
    matching.symlink_to(ROOT)
    with pytest.raises(ValueError, match='symlinked config parent'):
        install.uninstall(ROOT, home)
    assert matching.is_symlink()
    assert (home / '.local/bin/lean-review').is_symlink()


def test_backend_usage_passthrough_and_session_aggregation(tmp_path, monkeypatch):
    import subprocess
    # Counter shapes captured from actual CLI events, without prompts or payloads.
    codex = {'type': 'turn.completed', 'usage': {
        'input_tokens': 161537, 'cached_input_tokens': 114176, 'output_tokens': 3676}}
    log = tmp_path / 'review-1.jsonl'
    for backend, event, expected in (
        ('codex', codex, (161537, 114176, 3676)),
        ('opencode', {'type': 'step_finish', 'part': {'tokens': {
            'input': 1187, 'output': 202, 'reasoning': 60,
            'cache': {'write': 0, 'read': 0}}}}, (1187, 0, 202)),
        ('claude', {'type': 'result', 'usage': {
            'input_tokens': 0, 'cache_read_input_tokens': 0, 'output_tokens': 0}}, (0, 0, 0)),
    ):
        log.write_text(json.dumps(event) + '\n')
        assert launch.session_usage(tmp_path, backend) == dict(
            zip(('calls', 'input_tokens', 'cached_input_tokens', 'output_tokens'), (1, *expected)))
    log.unlink()

    repo = tmp_path / 'repo'
    subprocess.run(['git', 'init', '-q', str(repo)], check=True)
    artifact = repo / 'diff.patch'
    artifact.write_text('exact reviewed bytes')
    monkeypatch.setattr(Path, 'home', lambda: tmp_path)
    monkeypatch.setattr(launch.shutil, 'which', lambda _: '/mock/codex')
    events = [{'type': 'thread.started', 'thread_id': 'same-session'},
              {'type': 'item.completed', 'item': {'type': 'agent_message', 'text': 'PASS'}}, codex]

    observation = {}

    def run(argv, runtime, env, prompt, stem):
        assert 'model="gpt-5.6-terra"' in argv
        assert 'sandbox_mode="read-only"' in argv and 'approval_policy="never"' in argv
        context = runtime / 'codex/sessions/run.jsonl'
        context.parent.mkdir(parents=True, exist_ok=True)
        context.write_text(json.dumps({'type': 'turn_context', 'payload': {
            'sandbox_policy': {'type': 'read-only'}, 'approval_policy': 'never', **observation}}))
        (runtime / f'{stem}.jsonl').write_text('\n'.join(map(json.dumps, events)))
        return events

    monkeypatch.setattr(launch, 'run_process', run)
    args = SimpleNamespace(repo=repo, artifact=artifact,
                           sha256=hashlib.sha256(artifact.read_bytes()).hexdigest(),
                           base='0' * 40, target='worktree', backend='codex', depth='lite', model=None,
                           resume=None, goal='test', requirements='test', task_paths='diff.patch', evidence='test')
    first = launch.review(args)
    assert first['usage'] == {'calls': 1, **codex['usage']}
    assert first['model'] == 'gpt-5.6-terra' and first['reasoning_effort'] == 'medium'
    assert first['observed'] == {'model': None, 'reasoning_effort': None}
    config = tmp_path / '.config/lean-code-review/config.toml'
    config.parent.mkdir(parents=True)
    config.write_text('backend = "opencode"\n[codex.lite]\nmodel = "changed-default"\n')
    observation.update(model='reported-snapshot', effort='medium')
    args.resume = Path(first['runtime'])
    args.backend = 'auto'
    second = launch.review(args)
    assert second['backend'] == 'codex' and second['model'] == first['model']
    assert second['observed'] == {'model': 'reported-snapshot', 'reasoning_effort': 'medium'}

    assert second['session'] == first['session'] and second['sha256'] == args.sha256
    assert second['usage'] == {key: value * 2 for key, value in first['usage'].items()}
    config.write_text('not valid TOML [')  # Resume does not even parse changed settings.
    events.pop()  # Unknown counters must not turn into zero or a partial session sum.
    assert 'usage' not in launch.review(args)
    config.unlink()
    args.backend = None
    (args.resume / 'review-1.jsonl').write_bytes(b'\xff')
    result = launch.review(args)
    assert result['verdict'] == 'PASS' and 'usage' not in result

    # Invalid resume choices/binding must fail before any additional backend call.
    monkeypatch.setattr(launch, 'run_process', lambda *a: pytest.fail('unexpected backend call'))
    for backend, model in (('opencode', None), (None, 'another-model')):
        args.backend, args.model = backend, model
        with pytest.raises(launch.Blocked, match='retain backend and model'):
            launch.review(args)
    args.backend, args.model = None, None
    state_file = args.resume / 'session.json'
    saved = json.loads(state_file.read_text())
    for key in ('model', 'reasoning_effort'):
        legacy = dict(saved)
        legacy.pop(key)
        state_file.write_text(json.dumps(legacy))
        with pytest.raises(launch.Blocked, match='legacy/incomplete'):
            launch.review(args)
    state_file.write_text(json.dumps({**saved, 'model': None}))
    with pytest.raises(launch.Blocked, match='model must'):
        launch.review(args)
    state_file.write_text(json.dumps({**saved, 'reasoning_effort': 'low'}))
    with pytest.raises(launch.Blocked, match='reasoning effort'):
        launch.review(args)


def test_selection_precedence_and_depth(tmp_path, monkeypatch):
    monkeypatch.setattr(launch.shutil, 'which', lambda b: f'/mock/{b}')
    path = tmp_path / '.config/lean-code-review/config.toml'
    path.parent.mkdir(parents=True)
    path.write_text('backend = "opencode"\n[opencode]\nmodel = "vendor/same-model"\n'
                    '[codex]\nmodel = "backend-model"\n[codex.strict]\nmodel = "depth-model"\n')
    config = launch.settings(tmp_path)
    for depth, effort in (('lite', 'low'), ('strict', 'high')):
        assert launch.resolve_selection(ROOT, depth, None, None, config) == {
            'backend': 'opencode', 'model': 'vendor/same-model', 'reasoning_effort': effort}
    assert launch.resolve_selection(ROOT, 'strict', 'auto', None, config)['backend'] == 'codex'
    for model, depth, overrides, expected in (
        ('cli-model', 'strict', config, 'cli-model'),
        (None, 'strict', config, 'depth-model'),
        (None, 'lite', config, 'backend-model'),
        (None, 'strict', {}, launch.codex_profile(ROOT, 'strict')['model']),
    ):
        assert launch.resolve_selection(ROOT, depth, 'codex', model, overrides)['model'] == expected
    assert launch.resolve_selection(ROOT, 'lite', 'claude', None, {})['model'] == 'haiku'
    assert launch.resolve_selection(ROOT, 'strict', 'claude', None, {}) == {
        'backend': 'claude', 'model': 'sonnet', 'reasoning_effort': None}
    assert launch.resolve_selection(ROOT, 'strict', 'claude', 'other-model', config)['model'] == 'other-model'
    with pytest.raises(launch.Blocked, match='provider/model'):
        launch.resolve_selection(ROOT, 'lite', 'opencode', None, {})
    monkeypatch.setattr(launch.shutil, 'which', lambda b: None)
    with pytest.raises(launch.Blocked, match='unavailable'):
        launch.resolve_selection(ROOT, 'lite', 'auto', None, {})


@pytest.mark.parametrize('text', [
    'backend = "unknown"',
    'model = "invalid-root-setting"',
    'codex = "not-a-table"',
    '[codex]\nmodel = 7',
    '[codex]\nstrict = 1',
    '[codex.strict]\nsandbox_mode = "danger-full-access"',
    '[opencode]\nplugin = ["foreign"]',
    '[opencode]\nmodel = ""',
    '[opencode]\nmodel = "bare-model"',
    '[opencode.strict]\nmodel = "provider/"',
])
def test_invalid_settings_fail_closed(tmp_path, text):
    path = tmp_path / '.config/lean-code-review/config.toml'
    path.parent.mkdir(parents=True)
    path.write_text(text)
    with pytest.raises(launch.Blocked):
        launch.settings(tmp_path)


def test_opencode_model_is_pinned_with_existing_isolation(tmp_path, monkeypatch):
    import subprocess
    _, repo, _, agent = isolated(tmp_path)
    subprocess.run(['git', 'init', '-q', str(repo)], check=True)
    artifact = repo / 'diff.patch'
    artifact.write_text('exact reviewed bytes')
    monkeypatch.setattr(Path, 'home', lambda: tmp_path)
    monkeypatch.setattr(launch.shutil, 'which', lambda b: f'/mock/{b}')
    original_run = subprocess.run

    def source_config(argv, *args, **kwargs):
        if argv[:3] == ['opencode', 'debug', 'config']:
            return SimpleNamespace(stdout=json.dumps({'provider': {
                'vendor': {'npm': '@ai-sdk/openai-compatible',
                           'options': {'baseURL': 'https://provider.example/v1'},
                           'models': {'model': {'name': 'Model'}}}}}))
        return original_run(argv, *args, **kwargs)

    monkeypatch.setattr(launch.subprocess, 'run', source_config)
    # Only the external CLI debug response is substituted; the real checker runs.
    monkeypatch.setattr(launch, 'check', lambda root, runtime, env, depth, model=None:
                        check(root, runtime, env, {}, agent, depth, model))
    calls = []

    def run(argv, runtime, env, prompt, stem):
        assert argv[argv.index('--model') + 1] == 'vendor/model'
        assert argv[argv.index('--agent') + 1] == 'spec-reviewer-strict'
        assert '--pure' in argv and env['HOME'] == str(runtime / 'home')
        assert ('--session' in argv) == bool(calls)
        calls.append(argv)
        return [{'type': 'text', 'sessionID': 'same-session', 'part': {'text': 'PASS'}}]

    monkeypatch.setattr(launch, 'run_process', run)
    args = SimpleNamespace(repo=repo, artifact=artifact,
                           sha256=hashlib.sha256(artifact.read_bytes()).hexdigest(),
                           base='0' * 40, target='worktree', backend='opencode', model='vendor/model',
                           depth='strict', resume=None, goal='test', requirements='test',
                           task_paths='diff.patch', evidence='test')
    first = launch.review(args)
    config = tmp_path / '.config/lean-code-review/config.toml'
    config.parent.mkdir(parents=True)
    config.write_text('backend = "codex"\n[opencode]\nmodel = "other/model"\n')
    args.resume, args.backend, args.model = Path(first['runtime']), 'auto', None
    second = launch.review(args)
    assert len(calls) == 2 and second['session'] == first['session']
    assert second['model'] == first['model'] and second['reasoning_effort'] == 'high'
    assert second['observed'] == {'model': None, 'reasoning_effort': None}
