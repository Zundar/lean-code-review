import copy
import json
from concurrent.futures import ThreadPoolExecutor

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


@pytest.mark.parametrize('mutate', [
    lambda data: data.update(extra='ambiguous'),
    lambda data: data['provider'].update(package='unknown-provider'),
    lambda data: data['provider']['settings'].update(baseURL='https://u:secret@provider.example/v1'),
    lambda data: data['provider']['settings'].update(baseURL='https://provider.example/v1?token=secret'),
    lambda data: data['model'].update(id='other-model'),
    lambda data: data['model'].update(headers={'x-api-key': 'secret'}),
    lambda data: data['model']['limit'].update(context=float('inf')),
    lambda data: data['model']['variants'][0].update(settings={'apiKey': 'secret'}),
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


def test_v2_runtime_prepares_native_config_and_fails_closed_on_drift(tmp_path, monkeypatch):
    runtime = tmp_path / 'runtime'
    config = runtime / 'config/opencode'
    config.mkdir(parents=True, mode=0o700)
    safe = safe_metadata(packet(), 'current/model-a')
    monkeypatch.setattr(launch, 'install_opencode_v2_plugin', lambda *_: None)

    prepared = launch.opencode_v2_prepare(launch.ROOT, runtime, 'strict', 'current/model-a', safe, {})
    env = {'OPENCODE_DISABLE_EXTERNAL_SKILLS': '1'}
    launch.check_opencode_v2(launch.ROOT, runtime, env, 'strict', 'current/model-a', prepared)
    data = json.loads((config / 'opencode.json').read_text())
    assert data['model'] == 'current/model-a'
    assert data['agents']['spec-reviewer-strict']['model'] == 'current/model-a#high'
    assert data['plugins'] == ['./plugins/reviewer-tools']
    assert 'apiKey' not in json.dumps(data)
    assert 'Authorization' not in json.dumps(data)

    data['agents']['spec-reviewer-strict']['permissions'] = []
    (config / 'opencode.json').write_text(json.dumps(data))
    with pytest.raises(launch.CheckError, match='isolation config mismatch'):
        launch.check_opencode_v2(launch.ROOT, runtime, env, 'strict', 'current/model-a', prepared)


def test_v2_version_is_bound_to_the_host_executable(tmp_path, monkeypatch):
    executable = tmp_path / 'opencode'
    executable.write_text('#!/bin/sh\nprintf "opencode v2.0.14\\n"\n')
    executable.chmod(0o700)
    monkeypatch.setenv('LEAN_REVIEW_OPENCODE_CLI', str(executable))
    monkeypatch.setenv('LEAN_REVIEW_OPENCODE_VERSION', '2.0.14')

    assert launch.opencode_major_version() == 2
    monkeypatch.setenv('LEAN_REVIEW_OPENCODE_VERSION', '2.0.15')
    with pytest.raises(launch.Blocked, match='differs from the current V2 host'):
        launch.opencode_major_version()
