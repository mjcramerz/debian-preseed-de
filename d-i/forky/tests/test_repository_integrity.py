#!/usr/bin/env python3
"""Repository boundaries, preserved profiles and relocation contracts."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import tempfile
import unittest

FORKY = Path(__file__).resolve().parents[1]
ROOT = FORKY.parents[1]
ROLE = re.search(r'^REPOSITORY_ROLE="([^"]+)"', (FORKY/'repo.env').read_text(), re.M).group(1)

def records():
    for file in sorted((FORKY/'classes/configs').glob('*.cfg')):
        for stanza in re.split(r'\n\s*\n', file.read_text()):
            fields = dict(line.split(': ', 1) for line in stanza.splitlines()
                          if ': ' in line and not line.startswith('#'))
            if fields.get('Type') == 'class':
                yield fields

class RepositoryIntegrityTests(unittest.TestCase):
    def test_layout_only_expected_scopes(self):
        self.assertEqual({p.name for p in (FORKY/'hooks').iterdir() if p.is_dir()}, {'installer','target'})
        for name in ('apt-setup','base-stage.d','d-i','finish-install.d','partman','pre-pkgsel.d'):
            self.assertTrue((FORKY/'hooks/installer'/name).is_dir(), name)
        self.assertTrue((FORKY/'hooks/installer/late_command.sh').is_file())
        self.assertFalse(any(p.is_dir() for p in (FORKY/'hosts/profiles').iterdir()))
        self.assertFalse((FORKY/'hosts/shared').exists())
    def test_profiles_preserved_byte_for_byte(self):
        ledger = json.loads((ROOT/'docs/migration-map.json').read_text())
        profile_records = {item['destination']:item for item in ledger['files']
                           if item['destination'].startswith('d-i/forky/hosts/profiles/')}
        files = list((FORKY/'hosts/profiles').glob('*.env'))
        self.assertEqual(len(profile_records), len(files))
        for path in files:
            with self.subTest(profile=path.name):
                item = profile_records[str(path.relative_to(ROOT))]
                self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), item['source_sha256'])
    def test_each_flat_profile_composes(self):
        override_names = {r['Name'] for r in records() if r['Group'] == 'profile'}
        profiles = sorted((FORKY/'hosts/profiles').glob('*.env'))
        with tempfile.TemporaryDirectory() as temp:
            commands = ['. "$INSTALLER_SOURCE_ROOT/scripts/common/lib.sh"',
                        'installer_ensure_repo_env "$INSTALLER_SOURCE_ROOT"',
                        'installer_classes_cache_ensure']
            for profile in profiles:
                logical = ('override-' if profile.stem in override_names else '') + profile.stem
                out = Path(temp)/profile.name
                commands.append(f'installer_fetch_host_env "$INSTALLER_SOURCE_ROOT" {shlex.quote(logical)} {shlex.quote(str(out))}')
                commands.append(f'/bin/sh -n {shlex.quote(str(out))}')
            env = {**os.environ, 'INSTALLER_RUNTIME_DIR':temp, 'INSTALLER_CMDLINE':'',
                   'INSTALLER_SOURCE_ROOT':str(FORKY),
                   'INSTALLER_SOURCE_LIBRARY':str(FORKY/'scripts/common/source.sh')}
            result = subprocess.run(['/bin/sh','-eu','-c','; '.join(commands)],
                capture_output=True,text=True,env=env,timeout=45)
            self.assertEqual(result.returncode,0,result.stderr)
            for profile in profiles:
                with self.subTest(profile=profile.name):
                    self.assertTrue((Path(temp)/profile.name).read_bytes().startswith(profile.read_bytes()))
    def test_role_scoped_entries(self):
        other = 'desktop' if ROLE == 'server' else 'server'
        self.assertTrue((FORKY/'classes/class-select/role'/f'{ROLE}.cfg').exists())
        self.assertFalse((FORKY/'classes/class-select/role'/f'{other}.cfg').exists())
        self.assertTrue((FORKY/'scripts/late'/f'{ROLE}.sh').exists())
        self.assertFalse((FORKY/'scripts/late'/f'{other}.sh').exists())
        if ROLE == 'desktop':
            self.assertFalse(any('gitlab-runner' in p.name for p in FORKY.rglob('*')))
            self.assertFalse((FORKY/'classes/class-select/service').exists())
        else:
            self.assertTrue((FORKY/'scripts/late/gitlab-runner.sh').exists())
            self.assertFalse((FORKY/'scripts/desktop').exists())
            self.assertFalse((FORKY/'hooks/target/usr/local/bin/labwc-session.tmpl').exists())
    def test_class_dependency_references_are_local(self):
        items=list(records())
        names={r['Group']+'/'+r['Name'] for r in items}
        for record in items:
            for field in ('RequiresClasses','RejectedClasses','AllowedHardwareClasses'):
                for name in re.split(r'[,\s]+',record.get(field,'')):
                    if name:
                        self.assertIn(name,names,f"{record['Name']}: {field}")
    def test_no_legacy_path_references_in_active_installer(self):
        old = re.compile(r'hooks/(?:shared|role|hardware|services)/|hosts/shared/|hosts/profiles/(?:btrfs|f2fs|vm|override)/')
        for directory in ('scripts','hooks/installer'):
            for path in (FORKY/directory).rglob('*'):
                if path.is_file():
                    self.assertIsNone(old.search(path.read_text()),str(path.relative_to(FORKY)))
    def test_no_symlinks_published(self):
        for path in FORKY.rglob('*'):
            self.assertFalse(path.is_symlink(),str(path.relative_to(FORKY)))
    def test_build_products_are_current(self):
        result=subprocess.run([sys.executable,'-B',str(ROOT/'tools/build.py'),'--check'],capture_output=True,text=True,timeout=30)
        self.assertEqual(result.returncode,0,result.stderr+result.stdout)

if __name__ == '__main__':
    unittest.main()
