"""Memory handoff regressions; all managers and GPU queries are fixture spies."""
from pathlib import Path as _IsolationPath
import sys as _isolation_sys
_isolation_sys.path.insert(0, str(_IsolationPath(__file__).resolve().parents[3] / 'tools'))
from isolation import require_test_isolation as _require_test_isolation
_require_test_isolation()

from contextlib import ExitStack
import fcntl
import io
import os
from pathlib import Path
import select
import signal
import subprocess
import sys
import tempfile
import types
import unittest
from unittest import mock

TARGET = Path(__file__).resolve().parents[1] / 'hooks/target'
sys.path.insert(0, str(TARGET / 'usr/local/lib/python3.14/dist-packages'))
from labwc_ai_copilots import resources as runtime


class Executed(BaseException):
    """Stand in for a successful exec without starting an installed program."""


class CoordinationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.coordinator = runtime.Coordinator.__new__(runtime.Coordinator)
        self.coordinator.directory = Path(self.temporary.name)
        self.stack = self.enterContext(ExitStack())
        # A missing mock must never reach a manager, GPU, host procfs or model.
        self.command = self.stack.enter_context(mock.patch.object(runtime, 'systemctl', return_value='active'))
        self.capture = self.stack.enter_context(mock.patch.object(runtime, 'capture', side_effect=AssertionError('unmocked command')))
        self.budget = self.stack.enter_context(mock.patch.object(runtime, 'memory_budget', return_value=(6 * runtime.MIB, 2 * runtime.MIB)))
        self.pressure = self.stack.enter_context(mock.patch.object(runtime, 'constrained', return_value=False))
        self.release = self.stack.enter_context(mock.patch.object(runtime, 'wait_gpu_release'))
        self.exited = self.stack.enter_context(mock.patch.object(runtime, 'processes_exited', return_value=True))
        self.status = self.stack.enter_context(mock.patch.object(runtime, 'whisper_status', return_value={
            'LoadState': 'loaded', 'ActiveState': 'active', 'MainPID': '1234'}))
        self.execute = self.stack.enter_context(mock.patch.object(runtime.os, 'execv', side_effect=Executed))

    def launch(self, arguments=None):
        with self.assertRaises(Executed):
            self.coordinator.run('/data/llama/bin/llama-cli', arguments or ['-p', 'fixture'])

    def suspended(self, pids=None):
        self.coordinator.write_state({'pids': pids or [4567], 'cuda': True, 'restore': True})

    def stopped_status(self):
        return {'LoadState': 'loaded', 'ActiveState': 'inactive', 'MainPID': '0'}

    def test_sufficient_memory_leaves_whisper_running(self):
        self.launch()
        self.assertNotIn(mock.call('stop', runtime.WHISPER, timeout=15), self.command.mock_calls)
        self.assertFalse(self.coordinator.read_state()['restore'])

    def test_pressure_stops_then_waits_before_exec_and_records_recovery_first(self):
        self.pressure.side_effect = [True, False]
        self.status.side_effect = [self.status.return_value, self.stopped_status()]
        order = []

        def command(*args, **kwargs):
            if args[:1] == ('stop',):
                self.assertTrue(self.coordinator.read_state()['restore'])
                order.append('stop')

        self.command.side_effect = command
        self.release.side_effect = lambda *args: order.append('release')

        def execute(*args):
            order.append('exec')
            # This is the actual flock, held through the exec handoff.
            fd = self.coordinator.open_file('leases.lock')
            try:
                with self.assertRaises(BlockingIOError):
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            finally:
                os.close(fd)
            raise Executed

        self.execute.side_effect = execute
        self.launch()
        self.assertEqual(order, ['stop', 'release', 'exec'])
        self.release.assert_called_once_with([1234], True)

    def test_stop_failure_aborts_and_preserves_recovery(self):
        self.pressure.return_value = True
        self.command.side_effect = lambda *args, **kw: (_ for _ in ()).throw(ValueError('stop failed')) if args[:1] == ('stop',) else ''
        with self.assertRaisesRegex(ValueError, 'stop failed'):
            self.coordinator.run('/data/llama/bin/llama-cli', [])
        self.execute.assert_not_called()
        self.assertTrue(self.coordinator.read_state()['restore'])

    def test_incomplete_teardown_aborts(self):
        self.pressure.return_value = True
        with self.assertRaisesRegex(ValueError, 'teardown'):
            self.coordinator.run('/data/llama/bin/llama-cli', [])
        self.execute.assert_not_called()

    def test_gpu_release_failure_aborts_and_retains_recovery(self):
        self.pressure.return_value = True
        self.status.side_effect = [self.status.return_value, self.stopped_status()]
        self.release.side_effect = ValueError('GPU still resident')
        with self.assertRaisesRegex(ValueError, 'GPU still resident'):
            self.coordinator.run('/data/llama/bin/llama-cli', [])
        self.execute.assert_not_called()
        self.assertTrue(self.coordinator.read_state()['restore'])

    def test_insufficient_memory_after_stop_aborts(self):
        self.pressure.return_value = True
        self.status.side_effect = [self.status.return_value, self.stopped_status()]
        with self.assertRaisesRegex(ValueError, 'insufficient'):
            self.coordinator.run('/data/llama/bin/llama-cli', [])
        self.execute.assert_not_called()

    def test_guard_start_failure_does_not_stop_whisper(self):
        self.command.side_effect = ValueError('guard unavailable')
        with self.assertRaisesRegex(ValueError, 'guard unavailable'):
            self.coordinator.run('/data/llama/bin/llama-cli', [])
        self.status.assert_not_called()
        self.execute.assert_not_called()

    def test_inactive_whisper_is_not_claimed_for_restoration(self):
        self.status.return_value = self.stopped_status()
        self.launch()
        self.assertFalse(self.coordinator.read_state()['restore'])

    def test_restore_waits_for_all_concurrent_leases(self):
        self.suspended()
        holders = [self.coordinator.open_file('leases.lock') for _ in range(2)]
        try:
            for fd in holders:
                fcntl.flock(fd, fcntl.LOCK_SH)
            self.coordinator.restore_once()
            os.close(holders.pop())
            self.coordinator.restore_once()
            self.command.assert_not_called()
            self.release.assert_not_called()
        finally:
            for fd in holders:
                os.close(fd)
        self.status.side_effect = [self.stopped_status(), self.stopped_status(), self.status.return_value]
        self.coordinator.restore_once()
        self.release.assert_called_once_with([4567], True)
        self.assertEqual(self.command.mock_calls[-1], mock.call('start', runtime.WHISPER, timeout=130))
        self.assertFalse(self.coordinator.read_state()['restore'])

    def test_restore_failure_is_retryable(self):
        self.suspended()
        self.status.return_value = self.stopped_status()
        with self.assertRaisesRegex(ValueError, 'did not resume'):
            self.coordinator.restore_once()
        self.assertTrue(self.coordinator.read_state()['restore'])

    def test_closed_descriptor_does_not_restore_while_llama_pid_is_alive(self):
        self.suspended()
        self.exited.return_value = False
        self.coordinator.restore_once()
        self.command.assert_not_called()
        self.release.assert_not_called()

    def test_logout_does_not_restart_whisper(self):
        self.suspended()
        self.command.return_value = 'deactivating'
        self.coordinator.restore_once()
        self.assertEqual(self.command.call_count, 1)
        self.release.assert_not_called()

    def test_exec_condition_defers_during_llama_and_allows_recovery(self):
        self.suspended()
        holder = self.coordinator.open_file('leases.lock')
        try:
            fcntl.flock(holder, fcntl.LOCK_SH)
            self.assertFalse(self.coordinator.allowed())
        finally:
            os.close(holder)
        self.assertTrue(self.coordinator.allowed())

    def test_diagnostics_do_not_claim_memory_or_stop_services(self):
        self.launch(['--threads-batch', '8', '--help'])
        self.command.assert_not_called()
        self.budget.assert_not_called()

    def test_prompt_equal_to_help_is_not_diagnostic(self):
        self.launch(['-p', '--help'])
        self.budget.assert_called_once()

    def test_symlink_lock_is_rejected(self):
        (self.coordinator.directory / 'leases.lock').symlink_to('state.json')
        with self.assertRaises(OSError):
            self.coordinator.open_file('leases.lock')

    def test_malformed_state_is_rejected(self):
        self.coordinator.write_state({'pids': ['not-a-pid'], 'cuda': True, 'restore': True})
        with self.assertRaisesRegex(ValueError, 'invalid memory coordination state'):
            self.coordinator.read_state()


class BudgetTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(mock.patch.dict(os.environ, {
            'LLAMA_ARG_MODEL': '/fixture/model.gguf', 'LLAMA_ARG_CTX_SIZE': '16384',
            'LLAMA_ARG_N_GPU_LAYERS': '8', 'LLAMA_ARG_KV_OFFLOAD': '0',
        }, clear=True))
        self.model = types.SimpleNamespace(architecture='qwen2', context_length=32768,
            size_bytes=4683070000, metadata={'qwen2.block_count': 28,
                'qwen2.embedding_length': 3584, 'qwen2.attention.head_count': 28,
                'qwen2.attention.head_count_kv': 4})
        self.inspect = self.enterContext(mock.patch.object(runtime, 'inspect_gguf_for_resources', return_value=self.model))

    def test_p15s_859_mib_requires_eviction_and_fits_after_reclaim(self):
        ram, vram = runtime.memory_budget([])
        self.assertGreater(vram, 859 * runtime.MIB)
        self.assertLess(vram, 2048 * runtime.MIB)
        self.assertLess(ram, 46000 * runtime.MIB)

    def test_cli_overrides_are_used(self):
        ram, vram = runtime.memory_budget(['--model=/fixture/other.gguf', '-ngl', '0', '-c', '2048'])
        self.inspect.assert_called_once_with('/fixture/other.gguf')
        self.assertEqual(vram, 0)
        self.assertLess(ram, runtime.memory_budget([])[0])

    def test_prompt_operands_are_not_resource_options(self):
        expected = runtime.memory_budget([])
        self.assertEqual(runtime.memory_budget(['-p', '--no-kv-offload']), expected)
        self.assertEqual(runtime.memory_budget(['-p', '-ngl']), expected)

    def test_cpu_device_and_cuda_visibility_disable_vram_budget(self):
        self.assertEqual(runtime.memory_budget(['--device', 'none'])[1], 0)
        with mock.patch.dict(os.environ, {'CUDA_VISIBLE_DEVICES': ''}):
            self.assertEqual(runtime.memory_budget([])[1], 0)

    def test_kv_offload_and_full_layer_override_increase_vram(self):
        base = runtime.memory_budget([])[1]
        with mock.patch.dict(os.environ, {'LLAMA_ARG_KV_OFFLOAD': '1'}):
            self.assertGreater(runtime.memory_budget([])[1], base)
        self.assertGreater(runtime.memory_budget(['--n-gpu-layers=-1'])[1], base)

    def test_ram_pressure_and_gpu_telemetry_are_fixture_only(self):
        with mock.patch.object(runtime.Path, 'open', return_value=io.StringIO('MemAvailable: 100 kB\n')), \
             mock.patch.object(runtime, 'gpu_rows', return_value=[['2000']]):
            self.assertTrue(runtime.constrained(102401, 1))

    def test_missing_gpu_telemetry_fails_closed(self):
        with mock.patch.object(runtime.Path, 'open', return_value=io.StringIO('MemAvailable: 99999999 kB\n')), \
             mock.patch.object(runtime, 'gpu_rows', return_value=[['N/A']]), \
             self.assertRaisesRegex(ValueError, 'telemetry'):
            runtime.constrained(1, 1)

    def test_gpu_release_waits_for_two_clear_samples(self):
        with mock.patch.object(runtime, 'gpu_pids', side_effect=[{123}, set(), set()]) as query, \
             mock.patch.object(runtime.time, 'sleep'):
            runtime.wait_gpu_release([123], True)
        self.assertEqual(query.call_count, 3)

    def test_gpu_release_timeout(self):
        with mock.patch.object(runtime, 'gpu_pids', return_value={123}), \
             mock.patch.object(runtime.time, 'monotonic', side_effect=[0, 0, 21]), \
             mock.patch.object(runtime.time, 'sleep'), \
             self.assertRaisesRegex(ValueError, '20 seconds'):
            runtime.wait_gpu_release([123], True)


class LeaseIntegrationTests(unittest.TestCase):
    def test_lease_survives_exec_and_releases_on_sigkill(self):
        # Only the disposable image's Python and private fixture lock are used.
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'lease'
            path.touch(mode=0o600)
            program = ('import fcntl,os,sys; fd=os.open(sys.argv[1],os.O_RDWR); '
                       'fcntl.flock(fd,fcntl.LOCK_SH); os.set_inheritable(fd,True); '
                       'os.execv(sys.executable,[sys.executable,"-I","-B","-c",'
                       '\'import time; print("ready",flush=True); time.sleep(30)\'])')
            process = subprocess.Popen(['/usr/bin/python3', '-I', '-B', '-c', program, str(path)],
                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                env={'PATH': '/usr/bin:/bin', 'HOME': directory, 'LANG': 'C'}, cwd=directory)
            try:
                self.assertTrue(select.select([process.stdout], [], [], 5)[0])
                self.assertEqual(process.stdout.readline(32), b'ready\n')
                self.assertFalse(runtime.processes_exited([process.pid]))
                with path.open('r+') as holder:
                    with self.assertRaises(BlockingIOError):
                        fcntl.flock(holder, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    process.send_signal(signal.SIGKILL)
                    process.wait(timeout=5)
                    self.assertTrue(runtime.processes_exited([process.pid]))
                    fcntl.flock(holder, fcntl.LOCK_EX | fcntl.LOCK_NB)
            finally:
                if process.poll() is None:
                    process.kill()
                process.communicate(timeout=5)


if __name__ == '__main__':
    unittest.main()
