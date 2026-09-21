#!/usr/bin/env python3
"""Verify the generated payload against source bytes, modes and preseed pins."""
from pathlib import Path
import hashlib
import importlib.util
import json
import re
import runpy
import tarfile

root = Path(__file__).resolve().parents[2]
seed = root / 'd-i/forky'
spec = importlib.util.spec_from_file_location('r5_build', root / 'tools/build.py')
build = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build)
build.validate_tomat_profiles()
checker = runpy.run_path(str(root / 'tools/check_resctl_bench.py'))
assert checker['check'](seed) == 13
manifest = {}
for line in (seed / 'payload.manifest').read_text().splitlines():
    match = re.fullmatch(r'([0-9a-f]{64})  ([A-Za-z0-9_./@+-]+)', line)
    if not match or match[2] in manifest or '..' in Path(match[2]).parts:
        raise SystemExit('Invalid or duplicate manifest entry')
    manifest[match[2]] = match[1]
seen = set()
with tarfile.open(seed / 'payload.tar.gz', 'r:gz') as archive:
    for member in archive.getmembers():
        if not member.isfile() or member.name in seen or member.name not in manifest:
            raise SystemExit('Unexpected payload entry: ' + member.name)
        seen.add(member.name)
        data = archive.extractfile(member).read()
        source = seed / member.name
        if data != source.read_bytes() or hashlib.sha256(data).hexdigest() != manifest[member.name]:
            raise SystemExit('Payload/manifest/source mismatch: ' + member.name)
        expected_mode = 0o755 if source.stat().st_mode & 0o111 else 0o644
        if member.mode != expected_mode:
            raise SystemExit('Payload mode mismatch: ' + member.name)
if seen != set(manifest) or seen != {p.relative_to(seed).as_posix() for p in build.payload_files()}:
    raise SystemExit('Payload manifest/source membership mismatch')
hashes = {name: hashlib.sha256((seed / name).read_bytes()).hexdigest()
          for name in ('payload.tar.gz', 'payload.manifest', 'scripts/common/source.sh')}
expected = build.generate_preseed(hashes['payload.tar.gz'], hashes['payload.manifest'], hashes['scripts/common/source.sh'])
if expected != (seed / 'preseed.cfg').read_bytes():
    raise SystemExit('Preseed entry point does not match the generated product pins')
hashes['preseed.cfg'] = hashlib.sha256((seed / 'preseed.cfg').read_bytes()).hexdigest()
result = {'payload_entries': len(seen), 'validated_profiles': len(list((seed / 'hosts/profiles').glob('*.env'))),
          'source_bytes_and_modes_match': True, 'preseed_pins_match': True, 'sha256': hashes}
Path(__file__).with_name('payload-integrity.json').write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps(result, indent=2))
