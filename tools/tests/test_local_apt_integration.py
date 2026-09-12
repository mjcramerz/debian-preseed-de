#!/usr/bin/python3
"""Real isolated APT index test. Root required; no install/upgrade is executed."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from test_local_apt_repository import repo, fixture


@unittest.skipUnless(os.geteuid() == 0 and shutil.which('apt-get') and shutil.which('gpg'),
                     'requires root and the distribution APT/GnuPG tools')
class AptIntegrationTests(unittest.TestCase):
    def test_signed_file_repository_changes_candidate_without_installing(self):
        base = Path('/var/lib/local-apt-tests')
        base.mkdir(mode=0o755, exist_ok=True)
        work = Path(tempfile.mkdtemp(dir=base))
        os.chmod(work, 0o755)
        repository = repo.Repository(work / 'software', work / 'etc')
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
