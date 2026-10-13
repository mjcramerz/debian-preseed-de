#!/usr/bin/python3
"""Real isolated APT index test. Root required; no install/upgrade is executed."""

# Refuse host execution before importing runtime helpers or creating fixtures.
from pathlib import Path as _IsolationPath
import sys as _isolation_sys
_isolation_sys.path.insert(0, str(_IsolationPath(__file__).resolve().parents[2] / 'tools'))
# Copied checker/GUI fixtures still use the verified private checkout gate.
_isolation_sys.path.insert(0, '/workspace/repository/tools')
from isolation import require_test_isolation as _require_test_isolation
_isolation_sys.path.pop(0)
_require_test_isolation()

import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from test_local_apt_repository import repo, fixture, install_source_template


@unittest.skipUnless(os.geteuid() == 0 and shutil.which('apt-get') and shutil.which('gpg'),
                     'requires root and the distribution APT/GnuPG tools')
class AptIntegrationTests(unittest.TestCase):
    def test_signed_file_repository_changes_candidate_without_installing(self):
        base = Path('/workspace/apt-repo-local-tests')
        base.mkdir(mode=0o755, exist_ok=True)
        work = Path(tempfile.mkdtemp(dir=base))
        os.chmod(work, 0o755)
        repository = repo.Repository(work / 'software', work / 'etc')
        install_source_template(repository)
        try:
            lists = work / 'lists'
            lists.mkdir(mode=0o755)
            (lists / 'partial').mkdir()
            status = work / 'status'
            status.write_text('')
            options = ['-o', f'Dir::Etc::sourcelist={repository.source}',
                       '-o', 'Dir::Etc::sourceparts=-', '-o', 'Dir::Etc::main=-',
                       '-o', 'Dir::Etc::parts=-', '-o', f'Dir::State::lists={lists}',
                       '-o', f'Dir::State::status={status}', '-o', f'Dir::Cache={work}/cache',
                       '-o', 'APT::Get::List-Cleanup=false']
            for version in ('1.0', '2.0'):
                source = work / f'fixture-{version}.deb'
                fixture(source, version=version, depends='')
                with repository.locked():
                    repository.ingest(repository.stage(source))
                    repository.publish()
                for binary, arguments in [('apt-get', ['update']),
                                          ('apt-cache', ['policy', 'fixture-app'])]:
                    result = subprocess.run(['/usr/bin/' + binary, *options, *arguments],
                                            capture_output=True, text=True, timeout=30,
                                            env={**repo.ENV, 'DEBIAN_FRONTEND': 'noninteractive'})
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    if binary == 'apt-cache':
                        self.assertIn('Candidate: ' + version, result.stdout)
                        self.assertIn('Installed: (none)', result.stdout)
            self.assertEqual(status.read_text(), '')
        finally:
            subprocess.run(['/usr/bin/gpgconf', '--homedir', str(repository.signing),
                            '--kill', 'gpg-agent'], capture_output=True, check=False)
            shutil.rmtree(work)


if __name__ == '__main__':
    unittest.main(verbosity=2)
