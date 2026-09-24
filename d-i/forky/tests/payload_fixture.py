"""Explicit installed-default views for suffixed payload sources.

No global Path/import monkeypatches. Publisher tests use the production shell
renderer instead of these views. Source files are never modified by fixtures.
"""
from __future__ import annotations
import atexit
from functools import lru_cache
from pathlib import Path
import runpy
import os
import shutil
import tempfile
import re
SEED = Path(__file__).resolve().parents[1]
@lru_cache(maxsize=1)
def _logging():
    module = runpy.run_path(str(SEED.parents[1] / 'tools/check_logging.py'))
    return module['render_logging'], module['load_logging']()
@lru_cache(maxsize=1)
def _relocated_sources():
    # Explicit source moves only: no synthesized target files or global Path hooks.
    import json
    return json.loads((SEED.parents[1] / 'd-i/forky/tests/fixtures/contracts/source-paths.json').read_text())['source_moves']
def source_path(path):
    path = Path(path)
    try:
        relative = path.relative_to(SEED).as_posix()
    except ValueError:
        relative = ''
    if relative:
        moved = _relocated_sources().get(relative) or _relocated_sources().get(relative + '.tmpl')
        if moved:
            path = SEED / moved
    alternative = path.with_name(path.name + '.tmpl')
    if os.path.exists(path) and os.path.exists(alternative):
        raise ValueError(f'ambiguous source template: {path}')
    return alternative if os.path.isfile(alternative) else path
def logging_text(text):
    if '__INSTALLER_LOG_' not in text:
        return text
    render, values = _logging()
    return render(text, values)
MODULE_ENTRYPOINTS = {'scripts/common/lib.sh', 'scripts/runtime/common.sh',
                      'scripts/desktop/components.sh', 'scripts/late/devops.sh'}
MODULE_CALL = re.compile(r"^bootstrap_source_module '([^']+)'", re.M)

def is_module_entrypoint(path):
    try:
        return Path(path).relative_to(SEED).as_posix().removesuffix('.tmpl') in MODULE_ENTRYPOINTS
    except ValueError:
        return False

def module_definition_view(path, *, render=True):
    """Definition-only view for isolated legacy function tests, not a loader.

    Every definition is read from its actual module in the explicit entrypoint
    order. Production bootstrap/wiring is exercised separately, with real files,
    in test_modular_installer.py. This view never writes into the repository.
    """
    original = Path(path)
    resolved = source_path(original)
    entry = resolved.read_text()
    parts = ['#!/bin/sh\n']
    if original.name.startswith('devops.sh'):
        parts.append('set -eu\ntarget_root=${1:-/target}\n[ -d "$target_root" ] || exit 0\n')
        parts.append('devops_codex_host_log_dir=__INSTALLER_LOG_CODEX_RUNTIME_DIR__\n')
        if render:
            parts[-1] = logging_text(parts[-1])
    for relative in MODULE_CALL.findall(entry):
        module = source_path(SEED / relative)
        text = module.read_text()
        if render and module.name.endswith('.tmpl'):
            text = logging_text(text)
        parts.append(text)
    if original.name.startswith('devops.sh'):
        parts.append('\ndevops_main "$@"\n')
    return '\n'.join(parts)

def read_text(path, *args, **kwargs):
    original = Path(path)
    if is_module_entrypoint(original):
        return module_definition_view(original, render=not original.name.endswith('.tmpl'))
    resolved = source_path(original)
    text = resolved.read_text(*args, **kwargs)
    return logging_text(text) if resolved != original else text

def read_bytes(path):
    original = Path(path)
    if is_module_entrypoint(original):
        return read_text(original).encode('utf-8')
    resolved = source_path(original)
    data = resolved.read_bytes()
    if resolved != original and b'__INSTALLER_LOG_' in data and b'\0' not in data:
        return logging_text(data.decode('utf-8')).encode('utf-8')
    return data
@lru_cache(maxsize=1)
def _temporary():
    directory = tempfile.TemporaryDirectory(prefix='payload-installed-fixture-')
    atexit.register(directory.cleanup)
    return Path(directory.name)
@lru_cache(maxsize=None)
def installed_script(path):
    original = Path(path); resolved = source_path(original)
    if not is_module_entrypoint(original) and resolved == original and b'__INSTALLER_LOG_' not in resolved.read_bytes():
        return resolved
    destination = _temporary() / original.relative_to(SEED)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(read_bytes(original))
    shutil.copymode(resolved, destination)
    return destination
@lru_cache(maxsize=None)
def python_library(path):
    path = Path(path); destination = _temporary() / 'python' / path.name
    shutil.copytree(path, destination, dirs_exist_ok=True, symlinks=True,
                    ignore=shutil.ignore_patterns('__pycache__'))
    for template in destination.rglob('*.py.tmpl'):
        output = template.with_name(template.name[:-5])
        if output.exists():
            raise ValueError(f'ambiguous copied Python template: {template}')
        output.write_text(logging_text(template.read_text()))
        shutil.copymode(template, output)
        template.unlink()
    return destination
def copy2(source, destination, **kwargs):
    original = Path(source); resolved = source_path(original)
    output = shutil.copy2(resolved, destination, **kwargs)
    if resolved != original or is_module_entrypoint(original):
        Path(output).write_bytes(read_bytes(original))
    return output

def copyfile(source, destination, **kwargs):
    original = Path(source); resolved = source_path(original)
    output = shutil.copyfile(resolved, destination, **kwargs)
    if resolved != original or is_module_entrypoint(original):
        Path(output).write_bytes(read_bytes(original))
    return output
def source_stat(path, **kwargs):
    return source_path(path).stat(**kwargs)
def source_is_file(path):
    return source_path(path).is_file()
def source_exists(path):
    return source_path(path).exists()
def shell_sources(code):
    """Resolve only renamed source libraries in fixture shell commands."""
    import shlex
    for relative in ('scripts/common/lib.sh', 'scripts/runtime/common.sh',
                     'scripts/desktop/components.sh', 'scripts/desktop/detect.sh',
                     'scripts/desktop/verify.sh', 'scripts/late/devops.sh',
                     'scripts/late/software.sh', 'scripts/firstboot/04-validation.sh'):
        if relative not in code:
            continue
        installed = str(installed_script(SEED / relative))
        code = code.replace(str(SEED / relative), installed)
        for variable in ('INSTALLER_SOURCE_ROOT', 'FORKY', 'SEED'):
            code = code.replace('"$' + variable + '/' + relative + '"', shlex.quote(installed))
    return code
def installed_argv(arguments):
    if not isinstance(arguments, (list, tuple)):
        return arguments
    result = list(arguments)
    for index, argument in enumerate(result):
        if not isinstance(argument, (str, Path)):
            continue
        text = str(argument)
        if index and result[index - 1] == '-c':
            result[index] = shell_sources(text)
        elif text == str(SEED / 'scripts/desktop'):
            result[index] = str(shell_directory(Path(text)))
        elif text.startswith(str(SEED) + '/') and '\n' not in text:
            path = Path(text)
            if is_module_entrypoint(path) or path.with_name(path.name + '.tmpl').is_file():
                result[index] = str(installed_script(path))
    return result

@lru_cache(maxsize=None)
def shell_directory(path):
    path = Path(path)
    destination = _temporary() / 'shell-tree' / path.relative_to(SEED)
    destination.mkdir(parents=True, exist_ok=True)
    for source in path.iterdir():
        if source.is_file() and not source.is_symlink():
            logical = source.with_name(source.name.removesuffix('.tmpl'))
            output = destination / logical.name
            output.write_bytes(read_bytes(logical))
            shutil.copymode(source, output)
    return destination

def waybar_config_text(directory):
    """Read the single installed native config, including both bar definitions."""
    return read_text(Path(directory) / 'config.tmpl')
