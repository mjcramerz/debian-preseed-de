"""Explicit installed-default view for legacy appearance/launcher fixtures.

No Path methods, production imports, files or global environments are patched.
The new test_themes suite separately exercises the actual shell/AWK publisher.
"""
from functools import lru_cache
from pathlib import Path
import runpy
from payload_fixture import logging_text


@lru_cache(maxsize=1)
def _renderer():
    tools = Path(__file__).resolve().parents[3] / 'tools'
    module = runpy.run_path(str(tools / 'check_themes.py'))
    return module['render_text'], module['load_themes']()


def render_theme_defaults(text: str, overrides=None) -> str:
    text = logging_text(text)
    if '__THEME_' not in text:
        return text
    render, values = _renderer()
    return render(text, {**values, **(overrides or {})})


def render_theme_bytes(data: bytes) -> bytes:
    if (b'__THEME_' not in data and b'__INSTALLER_LOG_' not in data) or b'\0' in data:
        return data
    return render_theme_defaults(data.decode('utf-8')).encode('utf-8')


def theme_values() -> dict[str, str]:
    return dict(_renderer()[1])


def render_theme_tree(root: Path) -> None:
    """Render only regular copied fixture files, never follow a symlink."""
    for path in list(root.rglob('*')):
        if path.is_file() and not path.is_symlink():
            data = path.read_bytes()
            if (b'__THEME_' in data or b'__INSTALLER_LOG_' in data) and b'\0' not in data:
                path.write_bytes(render_theme_bytes(data))

            if path.name.endswith('.tmpl'):
                destination = path.with_name(path.name[:-5])
                if destination.exists():
                    raise ValueError(f'ambiguous fixture template: {path}')
                path.rename(destination)
