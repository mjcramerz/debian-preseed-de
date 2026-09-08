#!/usr/bin/env python3
'''Managed external Debian repository and package-policy regressions.'''
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

FORKY = Path(__file__).resolve().parents[1]
PERL_LIB = FORKY / (
    'hooks/target/usr/local/lib/perl5/site_perl/external-managed-software'
)
SERVICING = PERL_LIB / 'ExternalSoftware/Servicing'
SYSTEM_PATH = '/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin'


class ManagedExternalSoftwareTests(unittest.TestCase):
    def run_perl(self, source: str, *arguments: object) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ['/usr/bin/perl', '-I', str(PERL_LIB), '-e', source,
             *(str(argument) for argument in arguments)],
            env={**os.environ, 'LC_ALL': 'C.UTF-8', 'PATH': SYSTEM_PATH},
            text=True,
            capture_output=True,
            timeout=30,
        )

    def test_repository_package_digest_uses_the_512_mib_streaming_bound(self):
        repository = (SERVICING / 'Repository.pm').read_text()
        self.assertIn('ExternalSoftware::Servicing::Atomic->sha256_file(', repository)
        self.assertNotIn('read_limited($path, 536_870_912)', repository)

        with tempfile.TemporaryDirectory(prefix='managed-package-digest-') as temporary:
            path = Path(temporary) / 'archive.deb'
            size = 64 * 1024 * 1024 + 1
            with path.open('wb') as stream:
                stream.write(b'managed-package-digest\0')
                stream.seek(size - 1)
                stream.write(b'\0')
            with path.open('rb') as stream:
                expected_sha256 = hashlib.file_digest(stream, 'sha256').hexdigest()
            source = r'''
use strict;
use warnings;
use ExternalSoftware::Servicing::Atomic;
my ($size, $sha256) = ExternalSoftware::Servicing::Atomic->sha256_file(
    $ARGV[0],
    $ARGV[1],
);
print "$size|$sha256\n";
'''
            result = self.run_perl(source, path, 536_870_912)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(
                result.stdout,
                f'{size}|{expected_sha256}\n',
            )

            too_small = self.run_perl(source, path, size - 1)
            self.assertNotEqual(too_small.returncode, 0)
            self.assertIn('bounded regular file', too_small.stderr)

            symlink = Path(temporary) / 'archive-link.deb'
            symlink.symlink_to(path)
            indirect = self.run_perl(source, symlink, 536_870_912)
            self.assertNotEqual(indirect.returncode, 0)
            self.assertIn('bounded regular file', indirect.stderr)

    def test_chatgpt_repacked_depends_excludes_x11_xwayland_and_nvidia(self):
        dependencies = [
            'libgtk-3-0',
            'libnotify4',
            'libx11-6 (>= 2:1.4.99.1)',
            'libx11-xcb1',
            'libxcb-dri3-0',
            'libxcb1',
            'libxcursor1',
            'libxcomposite1',
            'libxdamage1',
            'libxext6',
            'libxfixes3',
            'libxi6',
            'libxinerama1',
            'libxkbfile1',
            'libxmu6',
            'libxpm4',
            'libxrandr2',
            'libxrender1',
            'libxres1',
            'libxss1',
            'libxt6',
            'libxtst6',
            'libxv1',
            'libxvmc1',
            'libxxf86vm1',
            'x11-utils',
            'xauth',
            'xfonts-base',
            'xorg',
            'xserver-xorg-core',
            'xwayland',
            'xwayland-dev',
            'nvidia-driver',
            'libnvidia-gl-580',
            'firmware-nvidia-gsp',
            'xserver-xorg-video-nvidia',
            'cuda-toolkit-13',
            'libcuda1',
            'mesa-vulkan-drivers | vulkan-icd',
            'nvidia-driver | mesa-utils',
            'libwayland-client0',
            'libxkbcommon0',
            'libglib2.0-bin | kde-cli-tools',
        ]
        expected = (
            'libgtk-3-0, libnotify4, mesa-utils, libwayland-client0, '
            'libxkbcommon0, libglib2.0-bin | kde-cli-tools'
        )
        with tempfile.TemporaryDirectory(prefix='chatgpt-control-rewrite-') as temporary:
            work = Path(temporary)
            package_root = work / 'package'
            control_dir = package_root / 'DEBIAN'
            executable = package_root / 'usr/lib/chatgpt/ChatGPT'
            control_dir.mkdir(parents=True)
            control_dir.chmod(0o755)
            executable.parent.mkdir(parents=True)
            executable.write_text('#!/bin/sh\nexit 0\n')
            executable.chmod(0o755)
            (control_dir / 'control').write_text(
                'Package: chatgpt\n'
                'Version: 1.0\n'
                'Architecture: amd64\n'
                'Maintainer: Test <test@example.invalid>\n'
                f'Depends: {", ".join(dependencies)}\n'
                'Description: managed ChatGPT dependency policy fixture\n'
            )
            package = work / 'source.deb'
            built = subprocess.run(
                ['/usr/bin/dpkg-deb', '--build', '--root-owner-group',
                 str(package_root), str(package)],
                env={**os.environ, 'LC_ALL': 'C.UTF-8', 'PATH': SYSTEM_PATH},
                text=True,
                capture_output=True,
                timeout=30,
            )
            self.assertEqual(built.returncode, 0, built.stderr)

            source = r'''
use strict;
use warnings;
use ExternalSoftware::Servicing::ChatGPT;
use ExternalSoftware::Servicing::Deb;
my $deb = ExternalSoftware::Servicing::Deb->new(
    repository => bless({}, 'TestRepository'),
);
my $chatgpt = ExternalSoftware::Servicing::ChatGPT->new(
    state => bless({}, 'TestState'),
);
my $spec = $chatgpt->spec();
my $output = $deb->repack_without_dependencies(
    label        => $spec->{label},
    path         => $ARGV[0],
    work         => $ARGV[1],
    name         => $spec->{name},
    dependencies => $spec->{remove_dependencies},
);
print "$output\n";
'''
            repacked = self.run_perl(source, package, work)
            self.assertEqual(repacked.returncode, 0, repacked.stderr)
            output = Path(repacked.stdout.strip())
            self.assertTrue(output.is_file())
            depends = subprocess.check_output(
                ['/usr/bin/dpkg-deb', '-f', str(output), 'Depends'],
                env={**os.environ, 'LC_ALL': 'C.UTF-8', 'PATH': SYSTEM_PATH},
                text=True,
                timeout=30,
            ).strip()
            self.assertEqual(depends, expected)
            for forbidden in (
                'x11', 'xcb', 'xcomposite', 'xdamage', 'xext', 'xfixes',
                'xrandr', 'xwayland', 'xorg', 'xserver', 'nvidia', 'cuda',
                'mesa-vulkan-drivers', 'vulkan-icd',
            ):
                with self.subTest(forbidden=forbidden):
                    self.assertNotIn(forbidden, depends.lower())
            self.assertIn('libwayland-client0', depends)
            self.assertIn('libxkbcommon0', depends)

    def test_repository_failure_is_reported_for_every_managed_deb(self):
        source = r'''
use strict;
use warnings;
use ExternalSoftware::Servicing::CLI;
{
    package TestDeb;
    sub installed_version { return undef; }
}
{
    package TestRepository;
    sub retain { die "synthetic repository failure\n"; }
}
{
    package TestEvent;
}
no warnings 'redefine';
local *ExternalSoftware::Servicing::CLI::_log = sub { return 1; };
my $cli = ExternalSoftware::Servicing::CLI->new();
my ($result, $reason) = $cli->_stage_deb(
    bless({}, 'TestDeb'),
    bless({}, 'TestEvent'),
    bless({}, 'TestRepository'),
    {name => 'synthetic', label => 'Synthetic managed package'},
    '/tmp/synthetic.deb',
    {package => 'synthetic', version => '1.0', architecture => 'amd64'},
);
print join('|', $result, $reason, $cli->apply_failure_detail()), "\n";
'''
        result = self.run_perl(source)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout,
            '1|validation|repository: synthetic repository failure\n',
        )

    def test_chatgpt_forbidden_installed_dependencies_fail_postinstall(self):
        source = r'''
use strict;
use warnings;
use ExternalSoftware::Servicing::CLI;
{
    package TestDeb;
    sub new { return bless {install_calls => 0, reinstall => 0}, shift; }
    sub installed_version { return '1.0'; }
    sub installed_payload_valid { return 1; }
    sub installed_dependencies_allowed { return 0; }
    sub install {
        my ($self, undef, $reinstall) = @_;
        $self->{install_calls}++;
        $self->{reinstall} = $reinstall;
        return 1;
    }
}
{
    package TestRepository;
    sub latest {
        return {
            path => '/tmp/chatgpt-repacked.deb',
            metadata => {
                package => 'chatgpt',
                version => '1.0',
                architecture => 'amd64',
            },
        };
    }
}
{
    package TestEvent;
    sub emit { return 1; }
}
{
    package TestChatGPT;
    sub prepare_install { return 1; }
    sub finalize_install { return 1; }
    sub abort_install { return 1; }
    sub policy_valid { return 1; }
}
no warnings 'redefine';
local *ExternalSoftware::Servicing::CLI::_log = sub { return 1; };
local *ExternalSoftware::Servicing::Process::application_running = sub { return 0; };
my $deb = TestDeb->new();
my ($result, $reason) = ExternalSoftware::Servicing::CLI->new()->_apply_deb(
    $deb,
    bless({}, 'TestEvent'),
    bless({}, 'TestRepository'),
    {
        name => 'chatgpt',
        label => 'ChatGPT/Codex Desktop',
        packages => ['chatgpt'],
        executable => '/usr/lib/chatgpt/ChatGPT',
        remove_dependencies => ['*x11*', 'xwayland*', '*nvidia*'],
    },
    bless({}, 'TestChatGPT'),
    'installer',
);
print join(
    '|',
    $result,
    $reason,
    $deb->{install_calls},
    $deb->{reinstall},
), "\n";
'''
        result = self.run_perl(source)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, '1|postinstall|1|1\n')


if __name__ == '__main__':
    unittest.main()
