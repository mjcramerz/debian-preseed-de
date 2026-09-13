#!/usr/bin/env python3
"""Check the installer payload, manifest and pins against the audited sources."""
import hashlib
import json
from pathlib import Path
import sys
import tarfile

repo = Path(sys.argv[1]).resolve()
seed = repo / 'd-i/forky'
manifest = {}
for line in (seed / 'payload.manifest').read_text().splitlines():
    digest, relative = line.split('  ', 1)
    assert relative not in manifest, ('duplicate manifest path', relative)
    assert not relative.startswith('/') and '..' not in Path(relative).parts
    manifest[relative] = digest
    assert hashlib.sha256((seed / relative).read_bytes()).hexdigest() == digest, relative
with tarfile.open(seed / 'payload.tar.gz', 'r:gz') as archive:
    members = archive.getmembers()
    assert len(members) == len({member.name for member in members})
    assert set(manifest) == {member.name for member in members}
    for member in members:
        assert member.isfile(), member.name
        source = seed / member.name
        assert archive.extractfile(member).read() == source.read_bytes(), member.name
        assert member.mode == (0o755 if source.stat().st_mode & 0o111 else 0o644), member.name
    required = ['hooks/target/etc/skel-desktop/.config/wayscriber/config.toml',
                'hooks/target/usr/local/lib/perl5/site_perl/apparmor-managed-modes/AppArmor/ManagedModes/LoadedState.pm']
    for unit in ('pipewire.socket', 'pipewire.service', 'pipewire-pulse.socket', 'pipewire-pulse.service'):
        required.extend(p.relative_to(seed).as_posix() for p in
                        (seed / 'hooks/target/etc/systemd/user' / (unit + '.d')).glob('*.tmpl'))
    assert len(required) == 6
    assert all(relative in manifest for relative in required)
    assert not any(relative.endswith('managed-nvidia-char-links.path') for relative in manifest)
hashes = {name: hashlib.sha256((seed / name).read_bytes()).hexdigest()
          for name in ('payload.tar.gz', 'payload.manifest', 'preseed.cfg')}
preseed = (seed / 'preseed.cfg').read_text()
assert hashes['payload.tar.gz'] in preseed
assert hashes['payload.manifest'] in preseed
print(json.dumps({'payload_files_verified': len(manifest), 'all_file_bytes_and_normalized_modes_match': True,
                  'required_assets_present': required, 'removed_path_unit_absent': True,
                  'preseed_payload_and_manifest_pins_match': True, 'sha256': hashes}, indent=2))
