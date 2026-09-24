"""Exact reviewed upload reversions, never a replacement workload baseline."""
from functools import lru_cache
import hashlib
import json
from pathlib import Path


@lru_cache(maxsize=1)
def _review():
    return json.loads((Path(__file__).parent / 'fixtures/refactor-20260923-reversions.json').read_text())['files']


@lru_cache(maxsize=1)
def _followup():
    return json.loads((Path(__file__).parent / 'fixtures/layout-followup-20260923-reversions.json').read_text())['files']


@lru_cache(maxsize=1)
def _source_layout():
    return json.loads((Path(__file__).parent / 'fixtures/source-layout-20260923-reversions.json').read_text())['files']


@lru_cache(maxsize=1)
def _native_monitor():
    return json.loads((Path(__file__).parent / 'fixtures/native-monitor-20260924-reversions.json').read_text())['files']


def current_path(relative):
    return _source_layout().get(relative, {}).get('current_path',
        _followup().get(relative, {}).get('current_path',
        _review().get(relative, {}).get('current_path', relative)))


def uploaded_bytes(relative, data):
    native = _native_monitor().get(relative)
    if native is not None:
        text = data.decode()
        for hunk in native['hunks']:
            if text.count(hunk['current']) != 1:
                raise AssertionError(f'{relative}: reviewed native-monitor hunk changed or is ambiguous')
            text = text.replace(hunk['current'], hunk['previous'], 1)
        data = text.encode()
        if hashlib.sha256(data).hexdigest() != native['previous_sha256']:
            raise AssertionError(f'{relative}: unreviewed change outside Waybar/Fuzzel scope')
    layout = _source_layout().get(relative)
    if layout is not None:
        text = data.decode()
        for hunk in layout['hunks']:
            if text.count(hunk['current']) != 1:
                raise AssertionError(f'{relative}: reviewed source-layout hunk changed or is ambiguous')
            text = text.replace(hunk['current'], hunk['previous'], 1)
        data = text.encode()
        if hashlib.sha256(data).hexdigest() != layout['previous_sha256']:
            raise AssertionError(f'{relative}: unreviewed change outside source-layout scope')
    followup = _followup().get(relative)
    if followup is not None:
        text = data.decode()
        for hunk in followup['hunks']:
            if text.count(hunk['current']) != 1:
                raise AssertionError(f'{relative}: reviewed follow-up hunk changed or is ambiguous')
            text = text.replace(hunk['current'], hunk['previous'], 1)
        data = text.encode()
        if hashlib.sha256(data).hexdigest() != followup['previous_sha256']:
            raise AssertionError(f'{relative}: unreviewed change outside the scoped follow-up')
    record = _review().get(relative)
    if record is None:
        return data
    text = data.decode()
    for hunk in record['hunks']:
        if text.count(hunk['current']) != 1:
            raise AssertionError(f'{relative}: reviewed refactor hunk changed or is ambiguous')
        text = text.replace(hunk['current'], hunk['uploaded'], 1)
    original = text.encode()
    if hashlib.sha256(original).hexdigest() != record['uploaded_sha256']:
        raise AssertionError(f'{relative}: unreviewed change outside the scoped refactor')
    return original
