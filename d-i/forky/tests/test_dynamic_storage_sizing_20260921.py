"""RAM/disk-derived sizing and recipe regressions; never touch a real device.

Shell tests execute the production sizing and emitters with only hardware reads
stubbed. Perl tests run the real config validator and exact sizing method; the
latter's hardware/config access is injected so these tests need no Moo or sysfs.
"""
from __future__ import annotations
from payload_fixture import installed_argv as payload_installed_argv
from payload_fixture import read_bytes as payload_read_bytes, read_text as payload_read_text

import configparser
from functools import lru_cache
import json
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import tempfile
import unittest

FORKY = Path(__file__).resolve().parents[1]
TARGET = FORKY / 'hooks/target'
PERL_LIB = TARGET / 'usr/local/lib/perl5/site_perl/zram-writeback'
PROFILES = tuple(p.stem for p in sorted((FORKY / 'hosts/profiles').glob('*.env')))
Q = shlex.quote
GIB = 1024**3
MIB = 1024**2
MB = 10**6
KEYS = ('DEV_PART_EFI_MB', 'DEV_PART_BOOT_MB', 'DEV_PART_ROOT_MB',
        'DEV_PART_HOME_MB', 'DEV_PART_OPT_MB', 'DEV_PART_DATA_MB',
        'DEV_PART_POOL_MB', 'DEV_PART_VAR_TMP_MB', 'DEV_PART_VAR_LIB_SHSIGNED_MB',
        'DEV_PART_VAR_LOG_JOURNAL_MB', 'DEV_PART_RAW_SWAP_MB',
        'DEV_PART_RAW_ZRAM_MB', 'SWAP_SIZE_MIB', 'RUNTIME_DISK_TOTAL_MB',
        'RUNTIME_PRESERVED_TOTAL_MB', 'RUNTIME_USABLE_BUDGET_MB',
        'RUNTIME_BASE_LAYOUT_MB', 'RUNTIME_INSTALL_RAM_MIB')


def profile_values(profile):
    return dict(re.findall(r'^([A-Z][A-Z0-9_]*)="([^"\n]*)"$',
                           payload_read_text(FORKY / 'hosts/profiles' / f'{profile}.env'), re.M))


def shell(body, profile='btrfs-de-flex', *, executable='dash', check=True):
    family = 'f2fs' if profile.startswith('f2fs') else 'btrfs'
    sources = ['scripts/runtime/common.sh', f'scripts/runtime/{family}.sh',
               f'hosts/profiles/{profile}.env', 'hosts/installer/runtime.env',
               'hosts/installer/layout.env', f'hosts/installer/{family}.env']
    code = 'set -e\nRUNTIME_TEMPLATE_DIR=' + Q(str(FORKY/'scripts/runtime/templates')) + '\n' + '\n'.join('. '+Q(str(FORKY / s)) for s in sources) + '\n'
    code += 'runtime_fatal() { printf "fatal: %s\\n" "$*" >&2; exit 1; }\n'
    command = ['busybox', 'sh'] if executable == 'busybox' else [executable]
    result = subprocess.run(payload_installed_argv([*command, '-c', code+body]), text=True, capture_output=True, timeout=15)
    if check and result.returncode:
        raise AssertionError(result.stdout+result.stderr)
    return result


def layout(profile, *, disk=380*GIB, ram=7578, preserved=0,
           efi=512*MB, crypto=False, executable='dash', check=True):
    body = f'''
DEV_INSTALL_DISK=/dev/fixture
DEV_PART_PREFIX=/dev/fixturep
runtime_device_size_bytes() {{
  case "$1" in
    /dev/fixture) printf '%s\\n' {disk} ;;
    /dev/fixturep1) printf '%s\\n' {efi} ;;
    /dev/fixturep2) printf '%s\\n' {preserved-efi} ;;
    *) exit 1 ;;
  esac
}}
runtime_total_ram_mib() {{ printf '%s\\n' {ram}; }}
runtime_root_home_crypto_enabled() {{ {'true' if crypto else 'false'}; }}
'''
    if preserved:
        body += '''runtime_assign_dualboot_slots 1 3 "$SECURE_BOOT_STATE_MODE"
RUNTIME_DEBIAN_START_SLOT=$RUNTIME_BOOT_SLOT
runtime_capture_dualboot_partition_sizes
'''
    else:
        body += 'runtime_assign_default_slots\n'
    body += 'runtime_compute_layout_sizing\n'
    for k in KEYS:
        body += 'printf "'+k+'=%s\\n" "${'+k+':-0}"\n'
    body += "printf '%s\\n' '---RECIPE---'\nruntime_emit_debian_partition_recipe\n"
    result = shell(body, profile, executable=executable, check=check)
    if result.returncode:
        return result
    vals, recipe = result.stdout.split('---RECIPE---\n', 1)
    return dict((k,int(v)) for k,v in (line.split('=',1) for line in vals.splitlines())), recipe


@lru_cache(maxsize=None)
def rendered_policy(profile):
    """Use the installer placeholder map and literal scalar renderer."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        policy = tmp / 'zram.conf'
        policy.write_bytes(payload_read_bytes(TARGET / 'etc/zram-writeback/policy.conf'))
        shell(f'''
. {Q(str(FORKY/'scripts/late/templates.sh'))}
ZRAM_BACKING_RAW_PARTUUID=11111111-2222-3333-4444-555555555555
ZRAM_BACKING_RAW_DEVICE=/dev/fixturep12
ZRAM_BACKING_DEVICE=/dev/mapper/zram-writeback
render_target_template_placeholder_map > {Q(str(tmp/'map'))}
render_target_scalar_placeholders {Q(str(policy))} {Q(str(tmp/'map'))}
''',profile)
        text = payload_read_text(policy)
    assert '__' not in text, text
    parsed = configparser.ConfigParser(interpolation=None, strict=True)
    parsed.read_string(text)
    return {section:dict(parsed[section]) for section in parsed.sections()}


def normalize(policy, *, check=True):
    # This module has no Moo dependency; no validator is stubbed or bypassed.
    code = '''use JSON::PP; use Zram::Config::Validator qw(normalize_config);
local $/; my $raw = decode_json(<STDIN>); print encode_json(normalize_config($raw));'''
    result = subprocess.run(payload_installed_argv(['perl', '-I'+str(PERL_LIB), '-e', code]),
                            input=json.dumps(policy), text=True, capture_output=True, timeout=10)
    if check and result.returncode:
        raise AssertionError(result.stderr)
    return json.loads(result.stdout) if check else result


def logical_sizes(profile, ram, backing=16384):
    config = normalize(rendered_policy(profile))
    source = payload_read_text(PERL_LIB / 'Zram/Setup/Device.pm')
    function = re.search(r'^sub _dynamic_sizes \{.*?^\}', source, re.M|re.S).group()
    code = f'''
use strict; use warnings; use JSON::PP;
use Zram::Sizing qw(bytes_to_writeback_pages);
local $/; my $config = decode_json(<STDIN>);
sub cfg {{ $config->{{$_[0]}} }}
sub _memory_mib {{ {ram} }}
sub _backing_mib {{ {backing} }}
sub fatal {{ die $_[0] }}
{function}
print encode_json([ (bless {{}}, 'main')->_dynamic_sizes() ]);
'''
    result = subprocess.run(payload_installed_argv(['perl','-I'+str(PERL_LIB),'-e',code]),
                            input=json.dumps(config), text=True, capture_output=True,timeout=10)
    if result.returncode:
        raise AssertionError(result.stderr)
    return json.loads(result.stdout)


class DynamicStorageTests(unittest.TestCase):
    def test_requested_hardware_reaches_logical_and_fallback_targets(self):
        for p in PROFILES:
            f2 = p.startswith('f2fs')
            ram = (3424 if 'hp14' in p else 4096) if f2 else (7489 if '-flex' in p else 47935)
            gib = 6 if f2 else (16 if '-flex' in p else 28)
            swap = 2 if f2 else (6 if '-flex' in p else 8)
            with self.subTest(profile=p):
                vals,_ = layout(p,disk=(32 if f2 else 380)*GIB,ram=ram,
                                preserved=(10 if f2 else 100)*GIB if p.endswith('-duo') else 0)
                self.assertEqual(logical_sizes(p,ram)[0],gib*1024)
                self.assertEqual(vals['SWAP_SIZE_MIB'],swap*1024)
                self.assertEqual(vals['DEV_PART_RAW_SWAP_MB'],(swap*GIB+MB-1)//MB)

    def test_logical_sizes_really_scale_down_with_ram(self):
        for p,ram in (('btrfs-de-flex',4096),('btrfs-de-p15s',16384),('f2fs-de-hp14',2048)):
            with self.subTest(profile=p):
                cfg=profile_values(p)
                expected=min(int(cfg['ZRAM_MAX_MIB']), max(int(cfg['ZRAM_MIN_MIB']),
                            (ram*int(cfg['ZRAM_PCT'])+99)//100))
                actual=logical_sizes(p,ram)[0]
                self.assertEqual(actual,expected)
                self.assertLess(actual,int(cfg['ZRAM_MAX_MIB']))
                self.assertLess(int(cfg['ZRAM_MIN_MIB']),int(cfg['ZRAM_MAX_MIB']))

    def test_backing_really_scales_down_with_available_storage(self):
        for p in ('btrfs-de-flex','btrfs-de-p15s','f2fs-de-hp14'):
            with self.subTest(profile=p):
                small,_=layout(p,disk=24*GIB,ram=4096)
                large,_=layout(p,disk=380*GIB,ram=4096)
                self.assertLess(small['DEV_PART_RAW_ZRAM_MB'],large['DEV_PART_RAW_ZRAM_MB'])
                self.assertEqual(large['DEV_PART_RAW_ZRAM_MB'],int(profile_values(p)['SIZE_PART_RAW_ZRAM_MAX_MB']))

    def test_swap_scales_with_both_ram_and_disk(self):
        for p in ('btrfs-de-flex','btrfs-de-p15s','f2fs-de-hp14'):
            with self.subTest(profile=p):
                values=list(map(int,shell('''
runtime_compute_swap_partition_mib 500000 1024
runtime_compute_swap_partition_mib 500000 65536
runtime_compute_swap_partition_mib 12000 65536
''',p).stdout.split()))
                self.assertLess(values[0],values[1]); self.assertLess(values[2],values[1])

    def test_all_profiles_fit_and_only_root_absorbs_recipe_remainder(self):
        for p in PROFILES:
            for crypto in (False,True):
                for preserved in (0,100*GIB):
                    with self.subTest(profile=p,crypto=crypto,preserved=preserved):
                        vals,recipe=layout(p,ram=47935,crypto=crypto,preserved=preserved)
                        parts=re.findall(r'^\s*(\d+) (\d+) (\d+) (\w+)\s*$',recipe,re.M)
                        self.assertEqual(tuple(map(int,parts[-1][:3])),(vals['DEV_PART_RAW_ZRAM_MB'],)*3)
                        self.assertEqual(tuple(map(int,parts[-2][:3])),(vals['DEV_PART_RAW_SWAP_MB'],)*3)
                        growers=[row for row in parts if int(row[2])>int(row[0])]
                        self.assertEqual(len(growers),1)
                        self.assertEqual(int(growers[0][0]),vals['DEV_PART_ROOT_MB'])
                        self.assertGreater(int(growers[0][1]),int(growers[0][0]))
                        root=re.search(r'\d+ \d+ 1000000000 (?:ext4|btrfs)\n(.*?)\n\s*\.',recipe,re.S)
                        self.assertIsNotNone(root); self.assertIn('mountpoint{ / }',root[1])
                        assigned=sum(int(row[0]) for row in parts)+(0 if preserved else vals['DEV_PART_EFI_MB'])
                        self.assertEqual(assigned,vals['RUNTIME_USABLE_BUDGET_MB'])
                        self.assertLessEqual(vals['RUNTIME_BASE_LAYOUT_MB'],assigned)

    def test_dual_budget_uses_measured_preserved_partitions_not_a_hardcoded_reservation(self):
        for p in ('btrfs-de-flex-duo','btrfs-de-p15s-duo','f2fs-de-hp14-duo'):
            for disk,preserved in ((380,100),(480,100),(380,180)):
                with self.subTest(profile=p,disk=disk,preserved=preserved):
                    vals,_=layout(p,disk=disk*GIB,preserved=preserved*GIB)
                    total=(preserved*GIB-512*MB+MB-1)//MB+512
                    self.assertEqual(vals['RUNTIME_PRESERVED_TOTAL_MB'],total)
                    self.assertEqual(vals['RUNTIME_USABLE_BUDGET_MB'],disk*GIB//MB-total-int(profile_values(p)['SIZE_LAYOUT_SAFETY_MARGIN_MB']))

    def test_cbook_nominal_32gb_and_32gib_with_firmware_reserved_ram_fit(self):
        for disk in (32*10**9,32*GIB):
            for p in ('f2fs-de-hp14','f2fs-de-hp14-duo'):
                with self.subTest(profile=p,disk=disk):
                    vals,_=layout(p,disk=disk,ram=3424,preserved=10*GIB if p.endswith('-duo') else 0)
                    self.assertEqual(logical_sizes(p,3424)[0],6144)
                    self.assertEqual(vals['SWAP_SIZE_MIB'],2048)
                    self.assertLessEqual(vals['RUNTIME_BASE_LAYOUT_MB'],vals['RUNTIME_USABLE_BUDGET_MB'])
                    self.assertGreaterEqual(vals['DEV_PART_ROOT_MB'],4096)

    def test_f2fs_overflow_path_never_shrinks_or_double_counts_reused_esp(self):
        vals,recipe=layout('f2fs-de-hp14-duo',disk=22*GIB,preserved=10*GIB,efi=2048*MB,ram=3424)
        self.assertEqual(vals['DEV_PART_EFI_MB'],2048)
        self.assertEqual(sum(int(v) for v in re.findall(r'^\s*(\d+) \d+ \d+ \w+$',recipe,re.M)),vals['RUNTIME_USABLE_BUDGET_MB'])
        self.assertNotIn('method{ efi }',recipe)

    def test_too_small_disk_fails_closed(self):
        for p in ('btrfs-de-flex','btrfs-de-p15s','f2fs-de-hp14','f2fs-de-hp14-duo'):
            with self.subTest(profile=p):
                result=layout(p,disk=5*GIB,check=False)
                self.assertNotEqual(result.returncode,0)
                self.assertIn('too small',result.stderr)

    def test_dual_has_no_space_after_preservation(self):
        result=layout('btrfs-de-flex-duo',disk=100*GIB,preserved=100*GIB,check=False)
        self.assertNotEqual(result.returncode,0); self.assertIn('collapsed',result.stderr)

    def test_mb_mib_conversion_and_invalid_values(self):
        result=shell('runtime_mib_to_recipe_mb test 2048; runtime_mib_to_recipe_mb test 6144; runtime_mib_to_recipe_mb test 8192')
        self.assertEqual(result.stdout.split(),['2148','6443','8590'])
        for bad in ('0','-1','01024','foo','1;id','2147483648','999999999999999999999'):
            with self.subTest(value=bad):
                self.assertNotEqual(shell('runtime_mib_to_recipe_mb test '+Q(bad),check=False).returncode,0)

    def test_byte_probes_round_disk_down_and_preserved_devices_up_in_decimal_mb(self):
        result=shell('''
DEV_INSTALL_DISK=/dev/fixture
runtime_device_size_bytes() { printf '10737418241\\n'; }
runtime_install_disk_size_mb
runtime_device_size_mb /dev/fixture
''')
        self.assertEqual(result.stdout.split(),['10737','10738'])

    def test_ram_and_layout_budgets_are_not_mixed_units(self):
        result=shell('''
SIZE_PART_SWAP_MIN_MIB=1
SIZE_PART_SWAP_MAX_MIB=8192
SIZE_PART_SWAP_RAM_DIVISOR=1
SIZE_PART_SWAP_LAYOUT_DIVISOR=8
runtime_compute_swap_partition_mib 16000 8192
''')
        self.assertEqual(int(result.stdout),16000*MB//MIB//8)

    def test_reversed_capacity_ranges_are_rejected(self):
        for body in ('SIZE_PART_RAW_ZRAM_MAX_MB=1; runtime_compute_raw_zram_partition_mb 50000 50000',
                     'SIZE_PART_SWAP_MAX_MIB=1; runtime_compute_swap_partition_mib 50000 7489'):
            with self.subTest(body=body): self.assertNotEqual(shell(body,check=False).returncode,0)

    @unittest.skipUnless(shutil.which('busybox'),'BusyBox unavailable')
    def test_dash_and_busybox_generate_identical_layouts(self):
        for p,ram,preserved in (('btrfs-de-flex-duo',7489,100*GIB),('btrfs-de-p15s',47935,0),
                                ('f2fs-de-hp14-duo',3424,10*GIB)):
            with self.subTest(profile=p):
                kwargs=dict(disk=(32 if p.startswith('f2fs') else 380)*GIB,ram=ram,preserved=preserved)
                self.assertEqual(layout(p,**kwargs),layout(p,executable='busybox',**kwargs))


class LogicalPolicyTests(unittest.TestCase):
    def test_all_rendered_profiles_pass_the_real_policy_validator(self):
        for p in PROFILES:
            with self.subTest(profile=p):
                cfg=normalize(rendered_policy(p))
                self.assertEqual(cfg['ZRAM_SIZE_PERCENT'],int(profile_values(p)['ZRAM_PCT']))
                self.assertEqual(cfg['ZRAM_SWAP_PRIORITY'],300)
                self.assertEqual(cfg['ZRAM_BACKING_DEVICE'],'/dev/mapper/zram-writeback')

    def test_logical_percentage_accepts_bounded_multiples_but_other_percentages_do_not(self):
        policy=json.loads(json.dumps(rendered_policy('btrfs-de-flex')))
        for value in (1,60,100,180,220,300):
            with self.subTest(value=value):
                policy['zram']['size_percent']=str(value)
                self.assertEqual(normalize(policy)['ZRAM_SIZE_PERCENT'],value)
        for value in ('0','301','99999999999999999999999999','-1','180.5','220;id',''):
            with self.subTest(value=value):
                policy['zram']['size_percent']=value
                self.assertNotEqual(normalize(policy,check=False).returncode,0)
        for section,key in (('zram','mem_limit_percent'),('writeback','writeback_limit_percent')):
            policy=json.loads(json.dumps(rendered_policy('btrfs-de-flex')))
            policy[section][key]='101'
            self.assertNotEqual(normalize(policy,check=False).returncode,0)

    def test_compressed_memory_limit_stays_bounded_by_physical_memory(self):
        for p in ('btrfs-de-flex','btrfs-de-p15s','btrfs-de','f2fs-de-hp14','f2fs-de-x360'):
            for ram in (1024,2048,3424,7489,47935,131072):
                with self.subTest(profile=p,ram=ram):
                    size,memory,_=logical_sizes(p,ram)
                    pct=int(profile_values(p)['ZRAM_MEM_LIMIT_PCT'])
                    self.assertEqual(memory,(min(ram,size)*pct+99)//100)
                    self.assertLess(memory,ram)

    def test_writeback_limit_respects_smaller_measured_backing(self):
        for p in ('btrfs-de-flex','btrfs-de-p15s','f2fs-de-hp14'):
            with self.subTest(profile=p):
                _,_,pages=logical_sizes(p,47935,backing=1024)
                self.assertLessEqual(pages,(1024-128)*256)


class RawPartitionValidationTests(unittest.TestCase):
    def validate(self,mb,actual,*,block=True,device='/dev/fixture'):
        return shell(f'''
. {Q(str(FORKY/'scripts/late/zram-swap.sh'))}
installer_fatal() {{ printf 'fatal: %s\\n' "$*" >&2; exit 1; }}
installer_warn() {{ :; }}
function [ {{
  if [[ "$1" == -b ]]; then {'true' if block else 'false'}; return; fi
  builtin [ "$@"
}}
blockdev() {{ printf '%s\\n' {Q(str(actual))}; }}
validate_raw_storage_partition {Q(device)} {Q(str(mb))}
''',executable='bash',check=False)

    def test_computed_sizes_accept_only_alignment_sized_deviations(self):
        for mb in (2148,6443,8590,17180,30065):
            for delta in (-2097152,-1,0,1,2097152):
                with self.subTest(mb=mb,delta=delta):
                    result=self.validate(mb,mb*MB+delta)
                    self.assertEqual(result.returncode,0,result.stderr)
            for delta in (-2097153,2097153,500*MB):
                with self.subTest(mb=mb,delta=delta):
                    self.assertNotEqual(self.validate(mb,mb*MB+delta).returncode,0)

    def test_missing_device_or_invalid_measurement_is_rejected(self):
        self.assertNotEqual(self.validate(6443,6443*MB,block=False).returncode,0)
        for actual in ('','error','-1','99999999999999999999999999'):
            with self.subTest(actual=actual): self.assertNotEqual(self.validate(6443,actual).returncode,0)
        for mb in ('','0','-1','01024','1;id','2147483648'):
            with self.subTest(mb=mb): self.assertNotEqual(self.validate(mb,6443*MB).returncode,0)
        self.assertNotEqual(self.validate(6443,6443*MB,device='/tmp/fixture').returncode,0)

    def test_both_measurements_are_wired_before_their_target_publications(self):
        source=payload_read_text(FORKY/'scripts/late/zram-swap.sh')
        stage=source.split('stage_target_zram_assets() {',1)[1]
        self.assertLess(stage.index('validate_raw_storage_partition "$ZRAM_BACKING_RAW_DEVICE" "$DEV_PART_RAW_ZRAM_MB"'),stage.index('  stage_target_asset '))
        config=source.split('write_target_swap_fallback_config() {',1)[1]
        self.assertLess(config.index('validate_raw_storage_partition "$SWAP_FALLBACK_RAW_DEVICE" "$DEV_PART_RAW_SWAP_MB"'),config.index('  SWAP_FALLBACK_RAW_PARTUUID='))


if __name__=='__main__':
    unittest.main()
