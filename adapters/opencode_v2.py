"""Validate the small, secret-safe metadata packet supplied by an OpenCode V2 session."""
from __future__ import annotations

import json
import math
import re
from urllib.parse import urlsplit


class V2MetadataError(ValueError):
    pass


_PROVIDER_PACKAGES = {
    '@opencode/ai/providers/openai-compatible',
    '@opencode/ai/providers/openai',
}
_TOP_LEVEL = {'provider', 'model'}
_MODEL_FIELDS = {'id', 'modelID', 'providerID', 'name', 'capabilities', 'limit', 'variants'}
_LIMIT_FIELDS = {'context', 'input', 'output'}


def _identifier(value: object) -> bool:
    return isinstance(value, str) and 0 < len(value) <= 512 and not re.search(r'[\s\x00]', value)


def _https_endpoint(value: object) -> bool:
    if not isinstance(value, str) or len(value) > 2048:
        return False
    try:
        parsed = urlsplit(value)
        parsed.port
    except ValueError:
        return False
    return (parsed.scheme == 'https' and bool(parsed.hostname)
            and parsed.username is None and parsed.password is None
            and '?' not in value and '#' not in value)


def _number(value: object) -> bool:
    return type(value) in (int, float) and math.isfinite(value)


def safe_metadata(raw: str | dict, current_model: str) -> dict:
    """Return only the selected V2 provider/model fields needed by the isolated runtime."""
    try:
        if isinstance(raw, str) and len(raw.encode('utf-8')) > 65536:
            raise V2MetadataError('OpenCode V2 provider/model metadata exceeds the size limit')
        value = json.loads(raw) if isinstance(raw, str) else raw
    except V2MetadataError:
        raise
    except (TypeError, ValueError) as exc:
        raise V2MetadataError('OpenCode V2 provider/model metadata is malformed') from exc
    if not isinstance(value, dict) or set(value) != _TOP_LEVEL:
        raise V2MetadataError('OpenCode V2 provider/model metadata is ambiguous')

    provider, model = value['provider'], value['model']
    if not isinstance(provider, dict) or not isinstance(model, dict):
        raise V2MetadataError('OpenCode V2 provider/model metadata is malformed')
    if set(provider) - {'id', 'package', 'settings'}:
        raise V2MetadataError('OpenCode V2 provider metadata contains unsupported fields')
    provider_id = provider.get('id')
    if not _identifier(provider_id) or not _identifier(current_model):
        raise V2MetadataError('OpenCode V2 provider/model identity is missing')
    expected_provider, separator, expected_model = current_model.partition('/')
    if not separator or expected_provider != provider_id:
        raise V2MetadataError('OpenCode V2 provider/model identity does not match the session')

    if (model.get('providerID') != provider_id or model.get('id') != expected_model
            or not _identifier(model.get('id'))):
        raise V2MetadataError('OpenCode V2 model does not match the current session')
    if set(model) - _MODEL_FIELDS:
        raise V2MetadataError('OpenCode V2 model metadata contains unsupported fields')
    model_id = model.get('modelID', model['id'])
    if not _identifier(model_id):
        raise V2MetadataError('OpenCode V2 model identifier is malformed')

    package = provider.get('package')
    settings = provider.get('settings')
    if (not isinstance(package, str) or package not in _PROVIDER_PACKAGES or not isinstance(settings, dict)
            or set(settings) - {'baseURL', 'provider', 'transport'}):
        raise V2MetadataError('OpenCode V2 provider package is unsupported')
    base_url = settings.get('baseURL')
    compatible = package == '@opencode/ai/providers/openai-compatible'
    if (compatible and not _https_endpoint(base_url)) or (base_url is not None and not _https_endpoint(base_url)):
        raise V2MetadataError('OpenCode V2 provider endpoint is malformed or unsafe')
    safe_settings = {'baseURL': base_url} if base_url else {}
    if 'provider' in settings:
        if not _identifier(settings['provider']):
            raise V2MetadataError('OpenCode V2 provider settings are malformed')
        safe_settings['provider'] = settings['provider']
    if 'transport' in settings:
        if not isinstance(settings['transport'], str) or settings['transport'] not in {'http', 'websocket'}:
            raise V2MetadataError('OpenCode V2 provider transport is unsupported')
        safe_settings['transport'] = settings['transport']

    safe_model = {'id': model['id'], 'providerID': provider_id, 'modelID': model_id}
    if 'name' in model:
        if not isinstance(model['name'], str) or not model['name'] or len(model['name']) > 256:
            raise V2MetadataError('OpenCode V2 model name is malformed')
        safe_model['name'] = model['name']
    if 'capabilities' in model:
        capabilities = model['capabilities']
        if (not isinstance(capabilities, dict) or set(capabilities) - {'tools', 'input', 'output'}
                or ('tools' in capabilities and type(capabilities['tools']) is not bool)
                or any(key in capabilities and (not isinstance(capabilities[key], list)
                    or len(capabilities[key]) > 16
                    or any(not _identifier(item) for item in capabilities[key]))
                       for key in ('input', 'output'))):
            raise V2MetadataError('OpenCode V2 model capabilities are malformed')
        safe_model['capabilities'] = capabilities
    if 'limit' in model:
        limit = model['limit']
        if (not isinstance(limit, dict) or set(limit) - _LIMIT_FIELDS
                or any(not _number(number) or number < 0 for number in limit.values())):
            raise V2MetadataError('OpenCode V2 model limits are malformed')
        safe_model['limit'] = limit
    if 'variants' in model:
        variants = model['variants']
        if not isinstance(variants, list) or len(variants) > 32:
            raise V2MetadataError('OpenCode V2 model variants are malformed')
        safe_variants = []
        for variant in variants:
            if (not isinstance(variant, dict) or set(variant) - {'id', 'settings'}
                    or not _identifier(variant.get('id'))):
                raise V2MetadataError('OpenCode V2 model variant is malformed')
            variant_settings = variant.get('settings', {})
            if not isinstance(variant_settings, dict) or set(variant_settings) - {'reasoningEffort', 'reasoning'}:
                raise V2MetadataError('OpenCode V2 model variant settings are unsafe')
            if 'reasoningEffort' in variant_settings and not _identifier(variant_settings['reasoningEffort']):
                raise V2MetadataError('OpenCode V2 model reasoning metadata is malformed')
            reasoning = variant_settings.get('reasoning')
            if reasoning is not None and (not isinstance(reasoning, dict)
                    or set(reasoning) - {'enabled', 'effort'}
                    or ('enabled' in reasoning and type(reasoning['enabled']) is not bool)
                    or ('effort' in reasoning and not _identifier(reasoning['effort']))):
                raise V2MetadataError('OpenCode V2 model reasoning metadata is malformed')
            safe_variants.append({'id': variant['id'], **({'settings': variant_settings} if variant_settings else {})})
        safe_model['variants'] = safe_variants

    return {
        'provider': {'id': provider_id, 'package': package, 'settings': safe_settings},
        'model': safe_model,
    }


def v2_provider_config(metadata: dict) -> dict:
    """Build a native V2 provider config from the sanitized session packet."""
    provider_id = metadata['provider']['id']
    catalog_id = metadata['model']['id']
    model = {key: value for key, value in metadata['model'].items()
             if key not in {'id', 'providerID'}}
    return {
        'model': f'{provider_id}/{catalog_id}',
        'providers': {
            provider_id: {
                'package': metadata['provider']['package'],
                'settings': metadata['provider']['settings'],
                'models': {catalog_id: model},
            },
        },
    }
