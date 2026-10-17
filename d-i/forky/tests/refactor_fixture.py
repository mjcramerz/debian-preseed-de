"""Exact reviewed upload reversions, never a replacement workload baseline."""

# Refuse host execution before importing runtime helpers or creating fixtures.
from pathlib import Path as _IsolationPath
import sys as _isolation_sys
_isolation_sys.path.insert(0, str(_IsolationPath(__file__).resolve().parents[3] / 'tools'))
# Copied checker/GUI fixtures still use the verified private checkout gate.
_isolation_sys.path.insert(0, '/workspace/repository/tools')
from isolation import require_test_isolation as _require_test_isolation
_isolation_sys.path.pop(0)
_require_test_isolation()

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


@lru_cache(maxsize=1)
def _security_review():
    return json.loads((Path(__file__).parent / 'fixtures/security-20260924-reversions.json').read_text())['files']


def current_path(relative):
    return _source_layout().get(relative, {}).get('current_path',
        _followup().get(relative, {}).get('current_path',
        _review().get(relative, {}).get('current_path', relative)))


def uploaded_bytes(relative, data):
    # October 17 drive ordering keeps these mount backends in session.slice.
    # Reverse only the exact additions before the older layered hash checks;
    # never replace their historical baselines or ignore unrelated bytes.
    mount_context_additions = {
        'd-i/forky/hooks/target/etc/systemd/user/gvfs-daemon.service.d/10-labwc-session.conf':
            b'# Keep the mount/session backend alive while app.slice stops before drive removal.\nSlice=session.slice\n',
        'd-i/forky/hooks/target/etc/systemd/user/gvfs-udisks2-volume-monitor.service.d/10-labwc-session.conf':
            b'\n[Service]\n# Removal runs after apps exit and before this user\'s mount context is torn down.\nSlice=session.slice\n',
    }
    addition = mount_context_additions.get(relative)
    if addition is not None:
        if data.count(addition) != 1:
            raise AssertionError(f'{relative}: reviewed mount-context addition changed or is ambiguous')
        data = data.replace(addition, b'', 1)
    security = _security_review().get(relative)
    if security is not None:
        text = data.decode()
        for hunk in security['hunks']:
            if text.count(hunk['current']) != 1:
                raise AssertionError(f'{relative}: reviewed security hunk changed or is ambiguous')
            text = text.replace(hunk['current'], hunk['previous'], 1)
        data = text.encode()
        if hashlib.sha256(data).hexdigest() != security['previous_sha256']:
            raise AssertionError(f'{relative}: unreviewed change outside security repair')
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
