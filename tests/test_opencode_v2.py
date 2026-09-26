import copy
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
import hashlib
import subprocess

import pytest

from adapters.opencode_v2 import V2MetadataError, safe_metadata, v2_provider_config
from adapters import runtime as launch


def packet(provider='current', model='model-a'):
    return {
        'provider': {
            'id': provider,
            'package': '@opencode/ai/providers/openai-compatible',
            'settings': {
                'baseURL': 'https://provider.example/v1',
                'provider': provider,
                'transport': 'http',
            },
        },
        'model': {
            'id': model,
            'providerID': provider,
            'modelID': 'upstream/model-a',
            'name': 'Model A',
            'capabilities': {'tools': True, 'input': ['text'], 'output': ['text']},
            'limit': {'context': 100000, 'output': 16000},
            'variants': [{'id': 'high', 'settings': {'reasoningEffort': 'high'}}],
        },
    }


def test_v2_metadata_matches_session_and_emits_native_provider_config():
    safe = safe_metadata(packet(), 'current/model-a')

    assert safe['provider'] == {
        'id': 'current',
        'package': '@opencode/ai/providers/openai-compatible',
        'settings': {'baseURL': 'https://provider.example/v1', 'provider': 'current', 'transport': 'http'},
    }
    assert 'headers' not in safe['provider']
    assert 'headers' not in safe['model']
    assert 'apiKey' not in str(safe)
    assert v2_provider_config(safe) == {
        'model': 'current/model-a',
        'providers': {
            'current': {
                'package': '@opencode/ai/providers/openai-compatible',
                'settings': {'baseURL': 'https://provider.example/v1', 'provider': 'current', 'transport': 'http'},
                'models': {'model-a': {
                    'modelID': 'upstream/model-a',
                    'name': 'Model A',
                    'capabilities': {'tools': True, 'input': ['text'], 'output': ['text']},
                    'limit': {'context': 100000, 'output': 16000},
                    'variants': [{'id': 'high', 'settings': {'reasoningEffort': 'high'}}],
                }},
            },
        },
    }


def test_v2_metadata_accepts_bounded_openai_variant_settings():
    value = packet('openai', 'gpt-6-luna')
    value['provider']['package'] = '@opencode/ai/providers/openai'
    value['provider']['settings'] = {
        'baseURL': 'https://provider.example/v1', 'transport': 'websocket',
    }
    value['model']['variants'] = [
        {'id': 'low', 'settings': {
            'reasoningEffort': 'low', 'reasoningSummary': 'auto',
            'include': ['reasoning.encrypted_content'],
        }},
        {'id': 'high', 'settings': {'reasoningEffort': 'high'}},
    ]

    safe = safe_metadata(value, 'openai/gpt-6-luna')

    assert safe['model']['variants'] == value['model']['variants']
    assert v2_provider_config(safe)['providers']['openai']['models']['gpt-6-luna']['variants'] == value[
        'model'
    ]['variants']


@pytest.mark.parametrize('mutate', [
    lambda data: data.update(extra='ambiguous'),
    lambda data: data['provider'].update(package='unknown-provider'),
    lambda data: data['provider']['settings'].update(baseURL='https://u:secret@provider.example/v1'),
    lambda data: data['provider']['settings'].update(baseURL='https://provider.example/v1?token=secret'),
    lambda data: data['model'].update(id='other-model'),
    lambda data: data['model'].update(headers={'x-api-key': 'secret'}),
    lambda data: data['model']['limit'].update(context=float('inf')),
    lambda data: data['model']['variants'][0].update(settings={'apiKey': 'secret'}),
    lambda data: data['model']['variants'][0].update(settings={'headers': {'authorization': 'secret'}}),
    lambda data: data['model']['variants'][0].update(settings={'reasoningSummary': 'concise'}),
    lambda data: data['model']['variants'][0].update(settings={'include': ['reasoning.encrypted_content', 'other']}),
    lambda data: data['model']['variants'][0].update(settings={'include': ['other']}),
    lambda data: data['model']['variants'][0].update(settings={'textVerbosity': 'low'}),
    lambda data: data['provider'].update(package=[]),
])
def test_v2_metadata_rejects_ambiguous_or_unsafe_fields(mutate):
    value = packet()
    mutate(value)
    with pytest.raises(V2MetadataError):
        safe_metadata(value, 'current/model-a')


@pytest.mark.parametrize('mutate', [
    lambda data: data['provider'].update(headers={'Authorization': 'secret'}),
    lambda data: data['provider']['settings'].update(apiKey='secret'),
])
def test_v2_metadata_rejects_provider_credentials_and_headers(mutate):
    value = packet()
    mutate(value)
    with pytest.raises(V2MetadataError):
        safe_metadata(value, 'current/model-a')


def test_v2_metadata_rejects_model_headers():
    value = packet()
    value['model']['headers'] = {'Authorization': 'secret'}
    with pytest.raises(V2MetadataError):
        safe_metadata(value, 'current/model-a')


def test_v2_metadata_size_is_bounded():
    with pytest.raises(V2MetadataError, match='size limit'):
        safe_metadata(' ' * 65537, 'current/model-a')


def test_two_session_metadata_has_no_cross_session_state():
    first, second = packet('provider-a', 'model-a'), packet('provider-b', 'model-b')
    with ThreadPoolExecutor(max_workers=2) as pool:
        a = pool.submit(safe_metadata, copy.deepcopy(first), 'provider-a/model-a')
        b = pool.submit(safe_metadata, copy.deepcopy(second), 'provider-b/model-b')

    assert a.result()['provider']['id'] == 'provider-a'
    assert a.result()['model']['id'] == 'model-a'
    assert b.result()['provider']['id'] == 'provider-b'
    assert b.result()['model']['id'] == 'model-b'


def test_v2_parent_service_freezes_artifact_and_rechecks_it_on_finish(tmp_path, monkeypatch):
    repo = tmp_path / 'repo'
    subprocess.run(['git', 'init', '-q', str(repo)], check=True)
    artifact = repo / 'diff.patch'
    artifact.write_text('small immutable diff')
    monkeypatch.setattr(Path, 'home', lambda: tmp_path)
    monkeypatch.setenv('LEAN_REVIEW_RUNTIME_ADAPTER', 'opencode')
    monkeypatch.setenv('LEAN_REVIEW_CURRENT_MODEL', 'openai/model-a')
    args = SimpleNamespace(repo=repo, artifact=artifact, sha256=hashlib.sha256(artifact.read_bytes()).hexdigest(),
                           base='0' * 40, target='worktree', model=None, resume=None, depth='strict',
                           goal='review', requirements='preserve', task_paths='diff.patch', evidence='focused')
    frozen = launch.v2_prepare(args)
    assert Path(frozen['artifact']).read_bytes() == artifact.read_bytes()
    assert f'sha256:{args.sha256}' in frozen['packet']
    assert 'base:' + args.base in frozen['packet']
    assert 'Target repository for nearby context: ' + str(repo) in frozen['packet']
    with pytest.raises(launch.Blocked, match='valid final verdict'):
        launch.v2_finish(Path(frozen['runtime']), {'session': 'ses-reviewer', 'verdict': 'unknown'})
    artifact.write_text('changed after reviewer request')
    with pytest.raises(launch.Blocked, match='review bytes'):
        launch.v2_finish(Path(frozen['runtime']), {'session': 'ses-reviewer', 'verdict': 'PASS'})
    artifact.write_text('small immutable diff')
    result = launch.v2_finish(Path(frozen['runtime']), {'session': 'ses-reviewer', 'verdict': 'PASS',
                                                       'variant': 'medium'})
    assert result['session'] == 'ses-reviewer'
    assert result['model'] == 'openai/model-a'
    assert result['verdict'] == 'PASS'


def test_v2_version_is_bound_to_the_host_executable(tmp_path, monkeypatch):
    executable = tmp_path / 'opencode'
    executable.write_text('#!/bin/sh\nprintf "opencode v2.0.14\\n"\n')
    executable.chmod(0o700)
    monkeypatch.setenv('LEAN_REVIEW_OPENCODE_CLI', str(executable))
    monkeypatch.setenv('LEAN_REVIEW_OPENCODE_VERSION', '2.0.14')

    assert launch.opencode_major_version() == 2
    monkeypatch.setenv('LEAN_REVIEW_OPENCODE_VERSION', '2.0.15')
    with pytest.raises(launch.Blocked, match='differs from the bound caller host'):
        launch.opencode_major_version()


def test_dual_install_uses_caller_bound_v1_cli_not_default_v2(tmp_path, monkeypatch):
    default_v2 = tmp_path / 'opencode'
    default_v2.write_text('#!/bin/sh\nprintf "opencode v2.0.14\\n"\n')
    default_v2.chmod(0o700)
    explicit_v1 = tmp_path / 'opencode-v1'
    explicit_v1.write_text('#!/bin/sh\nprintf "opencode v1.18.32\\n"\n')
    explicit_v1.chmod(0o700)
    monkeypatch.setenv('PATH', f'{tmp_path}:{os.environ["PATH"]}')
    monkeypatch.setenv('LEAN_REVIEW_OPENCODE_CLI', str(explicit_v1))
    monkeypatch.setenv('LEAN_REVIEW_OPENCODE_VERSION', '1.18.32')

    assert launch.shutil.which('opencode') == str(default_v2)
    assert launch.opencode_major_version() == 1
