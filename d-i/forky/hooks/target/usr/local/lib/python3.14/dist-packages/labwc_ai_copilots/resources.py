"""Per-user memory arbitration, with kernel leases surviving exec and SIGKILL.

The launcher execs the real binary with a shared flock descriptor. A separate
user service restores Whisper only after it can take the exclusive lease and
NVIDIA no longer reports any of the departed Llama PIDs. No supervisor changes
terminal I/O, job control, signals, or the Llama exit status.
"""
from __future__ import annotations

from contextlib import contextmanager
import csv
import fcntl
import io
import json
import os
from pathlib import Path
import select
import stat
import subprocess
import sys
import tempfile
import time

from .gguf import inspect_gguf_for_resources

MIB = 1024 * 1024
WHISPER = 'whisper-server.service'
GUARD = 'llama-whisper-guard.service'
COMMAND_ENV = {'PATH': '/usr/bin:/bin', 'LANG': 'C', 'LC_ALL': 'C'}


def log(event: str, **fields: str) -> None:
    record = {'component': 'llama-whisper', 'event': event, **fields}
    print(json.dumps(record, ensure_ascii=True), file=sys.stderr, flush=True)


def capture(arguments: list[str], timeout: float = 10) -> str:
    """Private bounded output; never log arguments (which may contain prompts)."""
    environment = dict(COMMAND_ENV, XDG_RUNTIME_DIR=f'/run/user/{os.getuid()}')
    with tempfile.TemporaryFile(dir=f'/run/user/{os.getuid()}/llama-whisper') as output:
        result = subprocess.run(arguments, stdin=subprocess.DEVNULL, stdout=output,
                                stderr=subprocess.DEVNULL, timeout=timeout, env=environment,
                                check=False)
        if result.returncode:
            raise ValueError(f'{Path(arguments[0]).name} failed (status {result.returncode})')
        if output.tell() > 65536:
            raise ValueError('command output exceeds 65536 bytes')
        output.seek(0)
        return output.read(65537).decode('utf-8', errors='strict').strip()


def systemctl(*arguments: str, timeout: float = 10) -> str:
    return capture(['/usr/bin/systemctl', '--user', '--no-pager', *arguments], timeout)


def whisper_status() -> dict[str, str]:
    content = systemctl('show', '--property=LoadState,ActiveState,MainPID', WHISPER)
    result = dict(line.split('=', 1) for line in content.splitlines() if '=' in line)
    if not {'LoadState', 'ActiveState', 'MainPID'} <= result.keys():
        raise ValueError('incomplete Whisper service state')
    return result


def gpu_rows(query: str) -> list[list[str]]:
    content = capture(['/usr/bin/nvidia-smi', query, '--format=csv,noheader,nounits'], 5)
    return [[value.strip() for value in row] for row in csv.reader(io.StringIO(content))]


def gpu_pids() -> set[int]:
    rows = gpu_rows('--query-compute-apps=pid')
    if any(len(row) != 1 or not row[0].isascii() or not row[0].isdigit() for row in rows):
        raise ValueError('invalid NVIDIA compute process telemetry')
    return {int(row[0]) for row in rows}


def wait_gpu_release(pids: list[int], cuda: bool) -> None:
    if not cuda:
        return
    deadline = time.monotonic() + 20
    clear = 0
    while time.monotonic() < deadline:
        clear = clear + 1 if not gpu_pids().intersection(pids) else 0
        if clear == 2:
            return
        time.sleep(0.25)
    raise ValueError('GPU contexts did not disappear within 20 seconds')


def processes_exited(pids: list[int]) -> bool:
    """A binary closing inherited FDs early must not permit early restoration."""
    for pid in pids:
        try:
            descriptor = os.pidfd_open(pid)
        except ProcessLookupError:
            continue
        try:
            poller = select.poll()
            poller.register(descriptor, select.POLLIN)
            if not poller.poll(0):
                return False
        finally:
            os.close(descriptor)
    return True


def acquire_lock(descriptor: int, mode: int, seconds: float) -> None:
    deadline = time.monotonic() + seconds
    while True:
        try:
            fcntl.flock(descriptor, mode | fcntl.LOCK_NB)
            return
        except BlockingIOError:
            if time.monotonic() >= deadline:
                raise ValueError('timed out waiting for memory coordination')
            time.sleep(0.1)


def memory_budget(arguments: list[str]) -> tuple[int, int]:
    """Conservative weight/KV estimates; overrides use the same argv as Llama."""
    values = {key: os.environ.get(key, '') for key in (
        'LLAMA_ARG_MODEL', 'LLAMA_ARG_CTX_SIZE', 'LLAMA_ARG_N_GPU_LAYERS',
        'LLAMA_ARG_KV_OFFLOAD',
    )}
    options = {
        '-m': 'LLAMA_ARG_MODEL', '--model': 'LLAMA_ARG_MODEL',
        '-c': 'LLAMA_ARG_CTX_SIZE', '--ctx-size': 'LLAMA_ARG_CTX_SIZE',
        '-ngl': 'LLAMA_ARG_N_GPU_LAYERS', '--gpu-layers': 'LLAMA_ARG_N_GPU_LAYERS',
        '--n-gpu-layers': 'LLAMA_ARG_N_GPU_LAYERS',
    }
    # These string operands can themselves look like resource flags. Preserve
    # them as data, just as Llama's argument parser does.
    text_options = {
        '-p', '--prompt', '-f', '--file', '-bf', '--binary-file',
        '-sp', '--system-prompt', '--system-prompt-file', '--chat-template',
        '--chat-template-file', '--grammar', '--grammar-file', '--json-schema',
        '--json-schema-file', '--log-file', '--log-prefix',
    }
    index = 0
    cpu_only = os.environ.get('CUDA_VISIBLE_DEVICES') in ('', '-1')
    while index < len(arguments):
        option, equals, value = arguments[index].partition('=')
        if option in text_options:
            if not equals:
                index += 1
        elif option in options:
            if not equals:
                index += 1
                if index == len(arguments):
                    raise ValueError('missing Llama resource option value')
                value = arguments[index]
            values[options[option]] = value
        elif option in ('-nkvo', '--no-kv-offload'):
            values['LLAMA_ARG_KV_OFFLOAD'] = '0'
        elif option == '--device':
            if not equals and index + 1 < len(arguments):
                index += 1
                value = arguments[index]
            cpu_only = value == 'none'
        index += 1
    model = inspect_gguf_for_resources(values['LLAMA_ARG_MODEL'])
    architecture = model.architecture

    def number(suffix: str, default: int) -> int:
        value = model.metadata.get(f'{architecture}.{suffix}', default)
        if type(value) is not int or not 1 <= value <= 1048576:
            raise ValueError('unsupported model memory metadata')
        return value

    blocks = number('block_count', 1)
    embedding = number('embedding_length', 8192)
    heads = number('attention.head_count', 1)
    kv_heads = number('attention.head_count_kv', heads)
    key = number('attention.key_length', max(1, embedding // heads))
    value = number('attention.value_length', key)
    context = int(values['LLAMA_ARG_CTX_SIZE'])
    if context == 0:
        context = model.context_length or 131072
    layers_text = values['LLAMA_ARG_N_GPU_LAYERS']
    layers = blocks + 1 if layers_text in ('-1', 'all', 'auto') else int(layers_text)
    if not 1 <= context <= 1048576 or not 0 <= layers <= 1048576:
        raise ValueError('unsupported Llama resource settings')
    # f16 K and V; all KV stays in RAM when offload is disabled. Weight
    # accounting retains a full RAM copy plus 1 GiB for the OS/compute buffers.
    kv = 2 * (key + value) * kv_heads * blocks * context
    ram = model.size_bytes + kv + 1024 * MIB
    vram = 0
    if layers and not cpu_only:
        vram = model.size_bytes * min(layers, blocks) // blocks + 256 * MIB
        if values['LLAMA_ARG_KV_OFFLOAD'] != '0':
            vram += kv * min(layers, blocks) // blocks
    return ram, vram


def constrained(ram: int, vram: int) -> bool:
    with Path('/proc/meminfo').open(encoding='ascii') as stream:
        content = stream.read(16385)
    if len(content) > 16384:
        raise ValueError('memory telemetry exceeds its bound')
    available = None
    for line in content.splitlines():
        fields = line.split()
        if fields[:1] == ['MemAvailable:'] and len(fields) == 3 and fields[2] == 'kB':
            available = int(fields[1]) * 1024
    if available is None or available < 0:
        raise ValueError('MemAvailable telemetry is unavailable')
    low = available < ram
    if vram:
        rows = gpu_rows('--query-gpu=memory.free')
        if not rows or any(len(row) != 1 or not row[0].isascii()
                           or not row[0].isdigit() for row in rows):
            raise ValueError('NVIDIA free-memory telemetry is unavailable')
        # Check every GPU conservatively; never sum memory across devices.
        low = low or any(int(row[0]) * MIB < vram for row in rows)
    return low


class Coordinator:
    def __init__(self) -> None:
        uid = os.getuid()
        runtime = Path(f'/run/user/{uid}')
        if uid == 0 or os.environ.get('XDG_RUNTIME_DIR') != str(runtime):
            raise ValueError('a regular user and its canonical XDG_RUNTIME_DIR are required')
        self.directory = runtime / 'llama-whisper'
        metadata = runtime.lstat()
        if (not stat.S_ISDIR(metadata.st_mode) or metadata.st_uid != uid
                or stat.S_IMODE(metadata.st_mode) != 0o700 or runtime.resolve() != runtime):
            raise ValueError('unsafe user runtime directory')
        self.directory.mkdir(mode=0o700, exist_ok=True)
        metadata = self.directory.lstat()
        if (not stat.S_ISDIR(metadata.st_mode) or metadata.st_uid != uid
                or stat.S_IMODE(metadata.st_mode) != 0o700):
            raise ValueError('unsafe memory coordination directory')
        if self.directory.resolve() != self.directory:
            raise ValueError('runtime directory must not contain symlinks')

    def open_file(self, name: str) -> int:
        fd = os.open(self.directory / name, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW
                     | os.O_NONBLOCK | os.O_CLOEXEC, 0o600)
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or stat.S_IMODE(info.st_mode) != 0o600 or info.st_nlink != 1):
            os.close(fd)
            raise ValueError('unsafe runtime file')
        return fd

    @contextmanager
    def admission(self):
        fd = self.open_file('admission.lock')
        try:
            acquire_lock(fd, fcntl.LOCK_EX, 180)
            yield
        finally:
            os.close(fd)

    def read_state(self) -> dict:
        fd = self.open_file('state.json')
        with os.fdopen(fd, 'r', encoding='ascii') as stream:
            content = stream.read(65537)
        if not content:
            return {'pids': [], 'cuda': False, 'restore': False}
        state = json.loads(content)
        if (len(content) > 65536 or not isinstance(state, dict)
                or set(state) != {'pids', 'cuda', 'restore'}
                or type(state['cuda']) is not bool or type(state['restore']) is not bool
                or not isinstance(state['pids'], list) or len(state['pids']) > 4096
                or any(type(pid) is not int or not 1 <= pid <= 4194304 for pid in state['pids'])):
            raise ValueError('invalid memory coordination state')
        return state

    def write_state(self, state: dict) -> None:
        fd, name = tempfile.mkstemp(prefix='.state-', dir=self.directory)
        try:
            with os.fdopen(fd, 'w', encoding='ascii') as stream:
                json.dump(state, stream)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(name, self.directory / 'state.json')
        finally:
            Path(name).unlink(missing_ok=True)

    def run(self, binary: str, arguments: list[str]) -> None:
        if binary not in ('/data/llama/bin/llama-cli', '/data/llama/bin/llama-server'):
            raise ValueError('unsupported managed Llama binary')
        # Informational invocations allocate no model and must not evict Whisper.
        diagnostic = arguments
        if len(arguments) == 3 and arguments[0] in ('-tb', '--threads-batch', '--threads_batch'):
            diagnostic = arguments[2:]
        if diagnostic in (['-h'], ['--help'], ['--version']):
            os.execv(binary, [binary, *arguments])
        ram, vram = memory_budget(arguments)
        lease = self.open_file('leases.lock')
        try:
            with self.admission():
                acquire_lock(lease, fcntl.LOCK_SH, 30)
                # Start before any service mutation. Restart=always recovers
                # the guard independently of the caller, including SIGKILL.
                systemctl('start', GUARD)
                state = self.read_state()
                state['pids'] = list(dict.fromkeys([*state['pids'], os.getpid()]))
                if len(state['pids']) > 4095:
                    raise ValueError('too many outstanding Llama process records')
                state['cuda'] = state['cuda'] or bool(vram)
                status = whisper_status()
                active = status['ActiveState'] in ('active', 'activating', 'reloading')
                if active and (state['restore'] or constrained(ram, vram)):
                    pid = int(status['MainPID'])
                    if pid and pid not in state['pids']:
                        state['pids'].append(pid)
                    state['restore'] = True
                    # Commit recovery intent before stop, even if this caller
                    # dies while systemd is completing the stop job.
                    self.write_state(state)
                    log('suspend-whisper', reason='memory-pressure')
                    systemctl('stop', WHISPER, timeout=15)
                    stopped = whisper_status()
                    if stopped['ActiveState'] not in ('inactive', 'failed') or stopped['MainPID'] != '0':
                        raise ValueError('Whisper teardown did not complete')
                    wait_gpu_release([pid] if pid else [], bool(vram))
                self.write_state(state)
                if constrained(ram, vram):
                    raise ValueError('insufficient available memory for the selected Llama settings')
                os.set_inheritable(lease, True)
            os.execv(binary, [binary, *arguments])
        finally:
            os.close(lease)

    def allowed(self) -> bool:
        state = self.read_state()
        if not state['restore']:
            return True
        fd = self.open_file('leases.lock')
        try:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                if not processes_exited(state['pids']):
                    return False
                wait_gpu_release(state['pids'], state['cuda'])
                return True
            except BlockingIOError:
                log('whisper-deferred', reason='llama-active')
                return False
        finally:
            os.close(fd)

    def restore_once(self) -> None:
        with self.admission():
            lease = self.open_file('leases.lock')
            try:
                try:
                    fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    return
                state = self.read_state()
                if not state['pids'] and not state['restore']:
                    return
                live = state['pids']
                if state['restore']:
                    whisper_pid = int(whisper_status()['MainPID'])
                    live = [pid for pid in live if pid != whisper_pid]
                if not processes_exited(live):
                    return
                if state['restore']:
                    if systemctl('show', '--property=ActiveState', '--value',
                                 'labwc-session.target') != 'active':
                        return
                    # A caller may have died between recording recovery intent
                    # and completing stop. Finish teardown before GPU polling.
                    systemctl('stop', WHISPER, timeout=15)
                    stopped = whisper_status()
                    if stopped['ActiveState'] not in ('inactive', 'failed') or stopped['MainPID'] != '0':
                        raise ValueError('Whisper teardown did not complete')
                if state['pids']:
                    wait_gpu_release(state['pids'], state['cuda'])
                # ExecCondition also takes the exclusive lease to distinguish
                # restoration from a competing start while Llama still runs.
                fcntl.flock(lease, fcntl.LOCK_UN)
                if state['restore']:
                    systemctl('start', WHISPER, timeout=130)
                    if whisper_status()['ActiveState'] != 'active':
                        raise ValueError('Whisper did not resume (check its user journal)')
                    log('resume-whisper', result='active')
                self.write_state({'pids': [], 'cuda': False, 'restore': False})
            finally:
                os.close(lease)

    def watch(self) -> None:
        while True:
            try:
                self.restore_once()
            except (OSError, ValueError, subprocess.SubprocessError) as error:
                log('restore-deferred', error=str(error)[:512])
                time.sleep(9)
            time.sleep(1)


def main() -> int:
    try:
        coordinator = Coordinator()
        if sys.argv[1:] == ['watch']:
            coordinator.watch()
        elif sys.argv[1:] == ['whisper-allowed']:
            return 0 if coordinator.allowed() else 1
        elif len(sys.argv) >= 3 and sys.argv[1] == 'run':
            coordinator.run(sys.argv[2], sys.argv[3:])
        else:
            raise ValueError('expected run BINARY [ARG...], watch, or whisper-allowed')
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        log('failed', error=str(error)[:512])
        return 255
    return 0
