"""Atomic host environments and fail-closed late loading, without target writes.

The transport endpoint and runtime effects are fixtures. Profile resolution,
ordered composition, filesystem publication and strict-shell sourcing are real.
"""
from __future__ import annotations
from payload_fixture import installed_script
from payload_fixture import installed_argv as payload_installed_argv, source_exists as payload_source_exists, source_stat as payload_source_stat
from payload_fixture import read_bytes as payload_read_bytes, read_text as payload_read_text
import os
from pathlib import Path
import shlex
import shutil
import signal
import subprocess
import tempfile
import time
import unittest

from test_repository_integrity import records
from test_environment import skip_unless_process_tree_visibility

FORKY = Path(__file__).resolve().parents[1]
LIB = installed_script(FORKY / 'scripts/common/lib.sh')
CORE = FORKY / 'scripts/late/core.sh'
Q = shlex.quote


def shells():
    yield ['/bin/sh']
    busybox = shutil.which('busybox')
    if busybox:
        yield [busybox, 'sh']


class AtomicEnvironmentTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='host-env-publication-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.fragments = self.root / 'source'
        self.fragments.mkdir()
        self.names = ['profile.env', 'identity.env', 'runtime.env', 'layout.env', 'btrfs.env', 'boot.env']
        for number, name in enumerate(self.names):
            # No newline: assembly must insert its own boundary after each part.
            value = 'first' if number == 0 else '${PART_%d}-next' % (number - 1)
            (self.fragments / name).write_text('PART_%d="%s"' % (number, value))
        self.destination = self.root / 'private/host.env'

    def compose(self, shell, failure='', extra='', names=None, conditional=True):
        source = '''
. "$LIB"
installer_fatal() { printf '%s\\n' "$*" >&2; exit 1; }
installer_info() { :; }
installer_fetch_seed_path() {
    if [ "$2" = "$FAILURE" ]; then
        printf 'PARTIAL=secret\\n' >"$3"
        return 42
    fi
    cp -- "$FIXTURE/$2" "$3"
}
composite_seed_base=caller-value
'''
        source += extra + '\n'
        command = 'installer_fetch_composite_env_paths fixture "$DEST" 0600 ' + ' '.join(Q(n) for n in (self.names if names is None else names))
        if conditional:
            source += 'if ' + command + '; then :; else exit "$?"; fi\n'
        else:
            source += command + '\n'
        source += '[ "$composite_seed_base" = caller-value ]\n'
        environment = {**os.environ, 'LIB': str(LIB), 'FIXTURE': str(self.fragments),
                       'DEST': str(self.destination), 'FAILURE': failure}
        return subprocess.run(payload_installed_argv([*shell, '-eu', '-c', source]), env=environment,
                              text=True, capture_output=True, timeout=15)

    def assert_clean(self):
        self.assertFalse(list(self.root.rglob('*.parts.*')))

    def test_success_is_private_ordered_sourceable_and_preserves_caller_variables(self):
        for shell in shells():
            with self.subTest(shell=shell):
                result = self.compose(shell)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(payload_source_stat(self.destination).st_mode & 0o777, 0o600)
                expected = ''.join(payload_read_text(self.fragments / name) + '\n' for name in self.names)
                self.assertEqual(payload_read_text(self.destination), expected)
                sourced = subprocess.run(payload_installed_argv([*shell, '-eu', '-c', '. "$1"; printf "%s\\n" "$PART_5"', 'test', str(self.destination)]),
                                         env={'PATH': os.environ['PATH']}, capture_output=True, text=True, timeout=5)
                self.assertEqual(sourced.returncode, 0, sourced.stderr)
                self.assertEqual(sourced.stdout, 'first-next-next-next-next-next\n')
                self.assert_clean()

    def test_each_failed_fragment_leaves_no_partial_cache_or_secret_in_error(self):
        for shell in shells():
            for name in self.names:
                for existing in (False, True):
                    with self.subTest(shell=shell, failed=name, existing=existing):
                        self.destination.parent.mkdir(exist_ok=True)
                        self.destination.unlink(missing_ok=True)
                        if existing:
                            self.destination.write_bytes(b'KNOWN_GOOD=yes\n')
                            self.destination.chmod(0o640)
                        result = self.compose(shell, failure=name)
                        self.assertNotEqual(result.returncode, 0)
                        self.assertIn(name, result.stderr)
                        self.assertNotIn('secret', result.stderr)
                        if existing:
                            self.assertEqual(payload_read_bytes(self.destination), b'KNOWN_GOOD=yes\n')
                            self.assertEqual(payload_source_stat(self.destination).st_mode & 0o777, 0o640)
                        else:
                            self.assertFalse(payload_source_exists(self.destination))
                        self.assert_clean()

    def test_empty_and_malformed_last_fragment_do_not_publish(self):
        for shell in shells():
            for invalid in ('', 'SECRET="unterminated'):
                with self.subTest(shell=shell, invalid=bool(invalid)):
                    (self.fragments / 'boot.env').write_text(invalid)
                    result = self.compose(shell)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn('boot.env', result.stderr)
                    self.assertNotIn('SECRET', result.stderr)
                    self.assertFalse(payload_source_exists(self.destination))
                    self.assert_clean()

    def test_append_and_publish_failures_are_not_masked_by_conditional_caller(self):
        for shell in shells():
            for operation in ('cat', 'chmod', 'mv'):
                with self.subTest(shell=shell, operation=operation):
                    self.destination.parent.mkdir(exist_ok=True)
                    self.destination.write_bytes(b'KNOWN_GOOD=yes\n')
                    result = self.compose(shell, extra=operation + '() { return 37; }')
                    self.assertNotEqual(result.returncode, 0)
                    self.assertEqual(payload_read_bytes(self.destination), b'KNOWN_GOOD=yes\n')
                    self.assert_clean()

    @skip_unless_process_tree_visibility
    def test_group_termination_cleans_real_transport_temporary_files(self):
        # Exercise the real cache-to-destination publisher. Block only cp after
        # its private destination has been allocated, then stop the entire
        # process group as a session/installer termination would do.
        self.destination.parent.mkdir()
        self.destination.write_bytes(b'KNOWN_GOOD=yes\n')
        self.destination.chmod(0o640)
        marker = self.root / 'copy.started'
        for shell in shells():
            with self.subTest(shell=shell):
                marker.unlink(missing_ok=True)
                source = '. ' + Q(str(FORKY / 'scripts/common/source.sh')) + '\n'
                source += '. ' + Q(str(LIB)) + '\n'
                source += r'''installer_load_source_library() { :; }
installer_info() { :; }
installer_fatal() { printf '%s\n' "$*" >&2; exit 1; }
cache=$(source_cache_root /seed)
mkdir -p "$cache"
printf 'VALUE=complete\n' >"$cache/profile.env"
cp() { : >"$MARKER"; sleep 30; command cp "$@"; }
installer_fetch_composite_env_paths /seed "$DEST" 0600 profile.env
'''
                process = subprocess.Popen(payload_installed_argv([*shell, '-eu', '-c', source]),
                    env={**os.environ, 'INSTALLER_RUNTIME_DIR': str(self.root / 'runtime'),
                         'INSTALLER_CMDLINE': '', 'MARKER': str(marker), 'DEST': str(self.destination)},
                    text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    start_new_session=True)
                try:
                    deadline = time.monotonic() + 5
                    while not payload_source_exists(marker) and process.poll() is None and time.monotonic() < deadline:
                        time.sleep(.01)
                    self.assertTrue(payload_source_exists(marker), 'real source_fetch did not reach the copy boundary')
                    os.killpg(process.pid, signal.SIGTERM)
                    _, error = process.communicate(timeout=5)
                    self.assertNotEqual(process.returncode, 0, error)
                    self.assertEqual(payload_read_bytes(self.destination), b'KNOWN_GOOD=yes\n')
                    self.assertEqual(payload_source_stat(self.destination).st_mode & 0o777, 0o640)
                    self.assert_clean()
                finally:
                    # The group can outlive its leader. Clean it even if poll()
                    # says the leader has exited; never leak a fixture sleeper.
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    process.communicate(timeout=5)

    def test_missing_all_candidates_is_an_error(self):
        result = self.compose(['/bin/sh'], names=['', ''])
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(payload_source_exists(self.destination))
        self.assert_clean()

    def test_symlink_and_directory_destinations_are_rejected(self):
        self.destination.parent.mkdir()
        outside = self.root / 'unrelated'
        outside.write_bytes(b'UNCHANGED\n')
        self.destination.symlink_to(outside)
        result = self.compose(['/bin/sh'])
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(self.destination.is_symlink())
        self.assertEqual(payload_read_bytes(outside), b'UNCHANGED\n')
        self.destination.unlink()
        self.destination.mkdir()
        result = self.compose(['/bin/sh'])
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(list(self.destination.iterdir()), [])
        self.assert_clean()


class RealProfileEnvironmentTests(unittest.TestCase):
    def test_every_real_profile_fetches_and_sources_in_fresh_strict_shells(self):
        override_names = {record['Name'] for record in records() if record['Group'] == 'profile'}
        profiles = sorted((FORKY / 'hosts/profiles').glob('*.env'))
        self.assertEqual(len(profiles), 10)
        with tempfile.TemporaryDirectory(prefix='profile-strict-source-') as temporary:
            root = Path(temporary)
            commands = ['. "$INSTALLER_SOURCE_ROOT/scripts/common/lib.sh"',
                        'installer_ensure_repo_env "$INSTALLER_SOURCE_ROOT"',
                        'installer_classes_cache_ensure']
            for profile in profiles:
                logical = ('override-' if profile.stem in override_names else '') + profile.stem
                commands.append('installer_fetch_host_env "$INSTALLER_SOURCE_ROOT" ' + Q(logical) + ' ' + Q(str(root / profile.name)))
            environment = {**os.environ, 'INSTALLER_RUNTIME_DIR': str(root / 'runtime'), 'INSTALLER_CMDLINE': '',
                           'INSTALLER_SOURCE_ROOT': str(FORKY), 'INSTALLER_SOURCE_LIBRARY': str(FORKY / 'scripts/common/source.sh')}
            result = subprocess.run(payload_installed_argv(['/bin/sh', '-eu', '-c', '\n'.join(commands)]),
                                    env=environment, text=True, capture_output=True, timeout=60)
            self.assertEqual(result.returncode, 0, result.stderr)
            for profile in profiles:
                published = root / profile.name
                self.assertTrue(payload_read_bytes(published).startswith(payload_read_bytes(profile)))
                for shell in shells():
                    with self.subTest(profile=profile.name, shell=shell):
                        # No policy variables inherited from the resolver/composer.
                        check = '. "$1"; : "${SYSTEM_PREFIX:?}" "${SYSTEM_DOMAIN:?}" "${DIR_INSTALLER_STATE:?}" "${FS_LABEL_ROOT:?}" "${FUZZEL_MENU_EXTERNAL_WIDTH:?}"; printf OK'
                        loaded = subprocess.run(payload_installed_argv([*shell, '-eu', '-c', check, 'test', str(published)]),
                                                env={'PATH': '/usr/bin:/bin', 'HOME': str(root)}, text=True, capture_output=True, timeout=10)
                        self.assertEqual(loaded.returncode, 0, loaded.stderr)
                        self.assertEqual(loaded.stdout, 'OK')


class LateRuntimeFailureTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='late-runtime-load-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        text = payload_read_text(CORE)
        start = text.index('late_command_load_runtime_env() {\n')
        self.function = text[start:text.index('\n}\n', start) + 3]
        # Relocate only the legacy installer endpoint, never the state-dir API.
        self.function = self.function.replace('/tmp/install-env/runtime.env', str(self.root / 'legacy.env'))
        (self.root / 'runtime.sh').write_text(':\n')
        (self.root / 'state').mkdir()

    def invoke(self, failure='', extra='', capture='true'):
        steps = ['late_command_load_profile_env', 'runtime_apply_layout_from_cmdline',
                 'runtime_capture_dualboot_partition_sizes', 'runtime_write_runtime_env',
                 'installer_ensure_context_loaded', 'runtime_ensure_system_identity', 'validate_tmpfs_policy_env']
        source = self.function + '\n'
        for step in steps:
            source += step + '() { printf "%s\\n" ' + Q(step) + '; '
            source += 'return 37; }\n' if step == failure else ':; }\n'
        source += 'installer_runtime_state_dir() { printf "%s/state\\n" "$TMP_ENV_DIR"; }\n'
        source += extra + '\n'
        source += 'if late_command_load_runtime_env ' + capture + '; then printf "SUCCESS\\n"; else exit "$?"; fi\n'
        return subprocess.run(payload_installed_argv(['/bin/sh', '-eu', '-c', source]), env={**os.environ, 'TMP_ENV_DIR': str(self.root)},
                              text=True, capture_output=True, timeout=10), steps

    def test_first_runtime_failure_stops_every_later_step_and_preserves_status(self):
        for step_index in range(7):
            result, steps = self.invoke(failure=['late_command_load_profile_env', 'runtime_apply_layout_from_cmdline',
                'runtime_capture_dualboot_partition_sizes', 'runtime_write_runtime_env', 'installer_ensure_context_loaded',
                'runtime_ensure_system_identity', 'validate_tmpfs_policy_env'][step_index])
            with self.subTest(step=steps[step_index]):
                self.assertEqual(result.returncode, 37, result.stderr)
                self.assertEqual(result.stdout.splitlines(), steps[:step_index + 1])

    def test_runtime_library_and_saved_environment_source_failures_propagate(self):
        for path in (self.root / 'runtime.sh', self.root / 'legacy.env', self.root / 'state/runtime.env'):
            with self.subTest(path=path.name):
                path.write_text('return 39\n')
                result, _ = self.invoke()
                self.assertEqual(result.returncode, 39, result.stderr)
                self.assertEqual(result.stdout, 'late_command_load_profile_env\n')
                path.unlink()
                (self.root / 'runtime.sh').write_text(':\n')

    def test_relocated_saved_runtime_prevents_layout_recompute_and_preserves_identity(self):
        (self.root / 'state/runtime.env').write_text('SYSTEM_HOSTNAME=saved-identity\n')
        result, _ = self.invoke(extra='runtime_ensure_system_identity() { [ "$SYSTEM_HOSTNAME" = saved-identity ]; }')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn('runtime_apply_layout', result.stdout)
        self.assertNotIn('runtime_write_runtime_env', result.stdout)
        self.assertIn('SUCCESS', result.stdout)

    def test_state_path_failure_is_not_ignored(self):
        result, _ = self.invoke(extra='installer_runtime_state_dir() { return 41; }')
        self.assertEqual(result.returncode, 41, result.stderr)
        self.assertEqual(result.stdout, 'late_command_load_profile_env\n')


if __name__ == '__main__':
    unittest.main()
