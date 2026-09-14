#!/usr/bin/python3 -I
"""Root-only, bounded, read-only diagnostics and reversible initramfs capture.

The public wrapper enters `sudo -i`. Only explicit hook actions write boot
configuration. No command strings, user plugins, shell evaluation, downloads,
benchmarks, driver reloads, firmware writes or automatic tuning are executed.
"""
from __future__ import annotations
import argparse
import collections
import contextlib
import datetime as dt
import fcntl
import glob
import hashlib
import json
import os
from pathlib import Path
import pwd
import re
import selectors
import shlex
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
import uuid

sys.dont_write_bytecode = True
LOGROOT = Path('/var/log/debugsys')
STATE = Path('/var/lib/debugsys')
TEMPLATES = Path('/usr/local/share/debugsys/initramfs')
PHASES = ('init-top', 'init-premount', 'local-top', 'local-premount', 'local-bottom', 'init-bottom')
CATEGORIES = ('hardware', 'system', 'boot', 'desktop', 'security', 'storage', 'network', 'credentials')
MAX_OUTPUT = 2 * 1024 * 1024
MAX_FILE = 256 * 1024
MAX_TOTAL = 96 * 1024 * 1024
MAX_FILES = 4096
ENV = {'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'HOME': '/root', 'USER': 'root',
       'LOGNAME': 'root', 'LANG': 'C.UTF-8', 'LC_ALL': 'C.UTF-8',
       'SYSTEMD_PAGER': '', 'SYSTEMD_COLORS': '0', 'PAGER': 'cat', 'TERM': 'dumb'}
MARKER = '# Managed by debugsys; do not edit.'

ISOLATION_UNITS = (
    'bluetooth-controller-init.service', 'managed-nvidia-char-links.service',
    'zram-writeback.service', 'zram-writebackd.service',
    'debugsys-boot-report.service', 'firstboot.service', 'tmpfs-pre-clean.service',
)
ISOLATION_PROPERTIES = ('Id,LoadState,ActiveState,SubState,Result,MainPID,ControlGroup,'
                        'PrivatePIDs,PrivateUsers,ProtectProc,ProcSubset,KillMode,'
                        'KillSignal,SendSIGKILL,TimeoutStopUSec,NoNewPrivileges,'
                        'FragmentPath,DropInPaths')

# No shell expansion: every probe is an argv array. Missing optional packages
# are recorded as unavailable, not silently treated as passing diagnostics.
PROBES = {
 'hardware': [
  ('cpu', ['lscpu']), ('cpu-topology', ['lscpu','--extended']),
  ('pci-drivers',['lspci','-nnk']), ('pci-links',['lspci','-vvnn']),
  ('pci-topology',['lspci','-tv']), ('usb',['lsusb']), ('usb-topology',['lsusb','-t']),
  ('firmware-memory',['dmidecode','--type','0,1,2,4,16,17']),
  ('hardware-tree',['lshw','-json']), ('sensors',['sensors','-j']),
  ('cpu-policy',['cpupower','frequency-info']), ('cpu-idle',['cpupower','idle-info']),
  ('power-profiles',['powerprofilesctl','list']), ('power-devices',['upower','-d']),
  ('firmware-devices',['fwupdmgr','get-devices','--json']),
 ],
 'system': [
  ('kernel',['uname','-a']), ('uptime',['uptime']), ('virtualization',['systemd-detect-virt']),
  ('failed-units',['systemctl','--failed','--no-pager','--plain']),
  ('units',['systemctl','list-units','--all','--no-pager','--plain']),
  ('unit-files',['systemctl','list-unit-files','--no-pager']),
  ('timers',['systemctl','list-timers','--all','--no-pager']),
  ('kernel-errors',['journalctl','-k','-b','-p','warning','--no-pager','-n','2500','-o','short-iso-precise']),
  ('system-errors',['journalctl','-b','-p','warning','--no-pager','-n','2500','-o','short-iso-precise']),
  ('processes',['ps','-eo','pid,ppid,uid,stat,ni,psr,pcpu,pmem,rss,comm','--sort=-rss']),
  ('package-audit',['dpkg','--audit']), ('packages',['dpkg-query','-W','-f=${binary:Package}\t${Version}\t${db:Status-Abbrev}\n']),
  ('dkms',['dkms','status']), ('journal-space',['journalctl','--disk-usage']),
  ('clock',['timedatectl','status']), ('sessions',['loginctl','list-sessions','--no-pager']),
 ],
 'boot': [
  ('boot-times',['systemd-analyze','time']), ('boot-blame',['systemd-analyze','blame','--no-pager']),
  ('boot-chain',['systemd-analyze','critical-chain','--no-pager']),
  ('boot-list',['journalctl','--list-boots','--no-pager']),
  ('boot-kernel',['journalctl','-k','-b','--no-pager','-n','3500','-o','short-monotonic']),
  ('previous-boot-errors',['journalctl','-b','-1','-p','warning','--no-pager','-n','1500']),
  ('efi-boot',['efibootmgr','-v']), ('secure-boot',['mokutil','--sb-state']),
  ('boot-storage',['findmnt','/boot']), ('efi-storage',['findmnt','/boot/efi']),
  ('modules',['lsmod']), ('udev-queue',['udevadm','settle','--timeout=1']),
 ],
 'desktop': [
  ('login-manager',['systemctl','show','greetd.service','seatd.service','--property=Id,ActiveState,SubState,Result,NRestarts,MainPID']),
  ('seats',['loginctl','seat-status','seat0','--no-pager']),
  ('labwc-version',['labwc','--version']), ('graphics-drivers',['lspci','-nnk']),
  ('nvidia-health',['nvidia-smi','-q','-x']), ('drm-devices',['ls','-l','/dev/dri']),
  ('input-devices',['libinput','list-devices']),
 ],
 'security': [
  ('service-isolation',['systemctl','show',*ISOLATION_UNITS,'--property='+ISOLATION_PROPERTIES]),
  ('apparmor',['aa-status','--json']), ('security-units',['systemctl','show','apparmor.service','auditd.service','--property=Id,ActiveState,SubState,Result']),
  ('isolation',['lsns','--output','NS,TYPE,NPROCS,PID,UID,USER']),
  ('unit-hardening',['systemd-analyze','security','--no-pager']),
  ('capabilities',['capsh','--print']), ('firewall',['nft','list','ruleset']),
  ('audit-status',['auditctl','-s']), ('apparmor-audit',['journalctl','-k','-b','--grep=apparmor=','--no-pager','-n','2000']),
  ('secure-boot-policy',['mokutil','--sb-state']),
  ('kernel-hardening',['sysctl','kernel.kptr_restrict','kernel.dmesg_restrict','kernel.unprivileged_bpf_disabled','kernel.yama.ptrace_scope','kernel.unprivileged_userns_clone','vm.unprivileged_userfaultfd']),
 ],
 'storage': [
  ('block-devices',['lsblk','--json','--output-all']), ('mounts',['findmnt','--json']),
  ('filesystem-space',['df','-hT']), ('inode-space',['df','-i']),
  ('swap',['swapon','--show','--bytes']), ('zram',['zramctl','--output-all']),
  ('memory',['free','--wide','--bytes']), ('numa',['numactl','--hardware']),
  ('vm-sample',['vmstat','-w','1','3']), ('io-sample',['iostat','-xz','1','3']),
  ('io-pressure',['cat','/proc/pressure/io']), ('memory-pressure',['cat','/proc/pressure/memory']),
  ('nvme-devices',['nvme','list','-o','json']),
  ('vm-policy',['sysctl','vm.swappiness','vm.dirty_ratio','vm.dirty_background_ratio','vm.dirty_bytes','vm.dirty_background_bytes','vm.vfs_cache_pressure','vm.overcommit_memory']),
 ],
 'network': [
  ('addresses',['ip','-details','address','show']), ('routes',['ip','route','show','table','all']),
  ('routes-v6',['ip','-6','route','show','table','all']), ('routing-rules',['ip','rule','show']),
  ('links',['ip','-s','-s','link']), ('listeners',['ss','-lntup']),
  ('dns',['resolvectl','status']), ('network-manager',['nmcli','general','status']),
  ('network-devices',['nmcli','device','show']), ('network-connections',['nmcli','-f','NAME,UUID,TYPE,DEVICE','connection','show']),
  ('radio-blocks',['rfkill','--output-all']), ('network-errors',['journalctl','-b','-u','NetworkManager.service','--no-pager','-n','1200']),
 ],
 'credentials': [
  ('ssh-version',['ssh','-V']), ('gpg-version',['gpg','--no-options','--version']),
  ('git-version',['git','--version']),
 ],
}
FILES = {
 'hardware': [
  '/sys/class/dmi/id/{bios_vendor,bios_version,bios_date,sys_vendor,product_name,product_version,board_name}',
  '/sys/devices/system/cpu/{online,offline,present,possible}',
  '/sys/devices/system/cpu/cpu*/cpufreq/{scaling_driver,scaling_governor,scaling_min_freq,scaling_max_freq,cpuinfo_max_freq,scaling_available_governors,energy_performance_preference,energy_performance_available_preferences}',
  '/sys/devices/system/cpu/cpu*/cpuidle/state*/{name,desc,latency,usage,time,disable}',
  '/sys/devices/system/cpu/{intel_pstate,amd_pstate}/*',
  '/sys/devices/system/cpu/cpu*/microcode/version', '/sys/devices/system/cpu/vulnerabilities/*',
  '/sys/class/hwmon/hwmon*/{name,temp*_input,temp*_crit,fan*_input,power*_average,power*_cap}',
  '/sys/class/thermal/thermal_zone*/{type,temp,trip_point_*_temp}',
  '/sys/class/power_supply/*/{type,status,capacity,cycle_count,energy_full,energy_full_design,power_now,voltage_now}',
  '/sys/bus/pci/devices/*/{current_link_speed,current_link_width,max_link_speed,max_link_width,aer_dev_correctable,aer_dev_nonfatal,aer_dev_fatal}',
  '/sys/bus/pci/devices/*/power/{control,runtime_status,runtime_suspended_time}',
  '/sys/bus/usb/devices/*/power/{control,autosuspend_delay_ms,runtime_status}',
  '/sys/bus/thunderbolt/devices/*/{security,authorized,generation}',
 ],
 'system': ['/etc/os-release','/proc/{version,uptime,loadavg,stat,meminfo,interrupts,softirqs}', '/proc/self/{cgroup,status,attr/current}'],
 'boot': ['/proc/cmdline','/proc/modules','/proc/mounts','/etc/initramfs-tools/initramfs.conf',
          '/sys/power/{state,mem_sleep,disk}', '/sys/module/{nvme_core,pcie_aspm,i915,amdgpu,nvidia}/parameters/*'],
 'desktop': ['/sys/class/drm/card*-*/{status,enabled,modes,dpms}', '/sys/module/{i915,amdgpu,nvidia_drm}/parameters/*',
             '/proc/asound/{cards,devices,pcm,modules,version}', '/sys/class/backlight/*/{type,brightness,max_brightness}'],
 'security': ['/sys/kernel/security/{lsm,lockdown}', '/sys/fs/cgroup/cgroup.controllers','/proc/self/{cgroup,attr/current,status,uid_map,gid_map}',
              '/proc/sys/kernel/{tainted,perf_event_paranoid,kexec_load_disabled,modules_disabled}'],
 'storage': ['/proc/{meminfo,vmstat,buddyinfo,zoneinfo,diskstats,swaps}', '/proc/pressure/*',
             '/sys/kernel/mm/transparent_hugepage/{enabled,defrag,shmem_enabled}', '/sys/kernel/mm/ksm/run',
             '/sys/module/zswap/parameters/*', '/sys/block/*/queue/{scheduler,rotational,read_ahead_kb,nr_requests,discard_max_bytes,logical_block_size,physical_block_size}',
             '/sys/block/zram*/{disksize,comp_algorithm,mm_stat,io_stat,mem_limit}', '/proc/sys/kernel/numa_balancing'],
 'network': ['/proc/net/{dev,snmp,snmp6,softnet_stat}', '/etc/resolv.conf',
             '/sys/class/net/*/{mtu,operstate,speed,duplex,carrier}', '/sys/class/net/*/statistics/*'],
 'credentials': ['/etc/ssh/managed_git_known_hosts'],
}

class DebugError(ValueError):
    pass

def stamp() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')

def redact(text: str) -> str:
    text = re.sub(r'(?is)-----BEGIN [^-]*PRIVATE KEY-----.*?-----END [^-]*PRIVATE KEY-----', '[PRIVATE KEY REDACTED]', text)
    text = re.sub(r'(?im)(\b(?:[\w.-]*(?:password|passphrase|secret|token|api[_-]?key|authkey)[\w.-]*|authorization)\s*[:=]\s*)("[^"\n]*"|\x27[^\x27\n]*\x27|[^\s,;]+)', r'\1[REDACTED]', text)
    text = re.sub(r'(?i)\b(Bearer|Basic)\s+[A-Za-z0-9+/._=-]+', r'\1 [REDACTED]', text)
    text = re.sub(r'(https?://)[^/@\s]+:[^/@\s]+@', r'\1[REDACTED]@', text)
    # Escape terminal control bytes in evidence, including ESC/OSC sequences.
    return ''.join(c if c in '\n\t' or ord(c) >= 32 and ord(c) != 127 else f'\\x{ord(c):02x}' for c in text)

def safe_directory(path: Path, mode: int = 0o700) -> None:
    if path == Path('/'):
        return
    if not path.parent.exists():
        safe_directory(path.parent, 0o755)
    # Never follow a replaceable/symlinked parent for privileged output.
    for parent in [path.parent, *path.parent.parents]:
        st = parent.lstat()
        if not stat.S_ISDIR(st.st_mode) or st.st_uid != 0 or st.st_mode & 0o022:
            raise DebugError(f'unsafe root-owned output parent: {parent}')
    try:
        path.mkdir(mode=mode)
    except FileExistsError:
        st = path.lstat()
        if not stat.S_ISDIR(st.st_mode) or st.st_uid != 0 or st.st_mode & 0o022:
            raise DebugError(f'unsafe output directory: {path}')
    path.chmod(mode)

def atomic_write(path: Path, data: bytes, mode: int = 0o600) -> None:
    safe_directory(path.parent, stat.S_IMODE(path.parent.stat().st_mode))
    if path.exists() or path.is_symlink():
        st = path.lstat()
        if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1 or st.st_uid != 0:
            raise DebugError(f'unsafe destination: {path}')
    fd, temporary = tempfile.mkstemp(prefix='.debugsys-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            os.fchmod(stream.fileno(), mode)
            stream.write(data); stream.flush(); os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)

@contextlib.contextmanager
def lock():
    safe_directory(STATE)
    fd = os.open(STATE/'operation.lock', os.O_CREAT | os.O_WRONLY | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_uid != 0 or st.st_nlink != 1:
            raise DebugError('unsafe operation lock')
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise DebugError('another debugsys operation is running') from exc
        yield
    finally:
        os.close(fd)

def run(argv: list[str], timeout: int = 30, cap: int = MAX_OUTPUT) -> tuple[str, dict]:
    """Stream with memory/output limits and terminate the complete process group."""
    executable = shutil.which(argv[0], path=ENV['PATH']) if not argv[0].startswith('/') else argv[0]
    if not executable or not Path(executable).is_file():
        return '', {'status':'not-installed', 'returncode':None, 'seconds':0}
    start = time.monotonic()
    out = bytearray()
    status = 'ok'
    proc = subprocess.Popen([executable, *argv[1:]], env=ENV, stdin=subprocess.DEVNULL,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, start_new_session=True)
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(proc.stdout, selectors.EVENT_READ)
            while selector.get_map():
                if time.monotonic()-start > timeout:
                    status = 'timeout'; break
                for key, _ in selector.select(.2):
                    chunk = os.read(key.fileobj.fileno(), 65536)
                    if not chunk:
                        selector.unregister(key.fileobj); continue
                    remaining = max(0, cap-len(out))
                    out.extend(chunk[:remaining])
                    if len(chunk) > remaining:
                        status = 'output-limit'; break
                if status != 'ok':
                    break
        if status == 'ok':
            try:
                proc.wait(timeout=max(.1, timeout-(time.monotonic()-start)))
            except subprocess.TimeoutExpired:
                status = 'timeout'
        if status == 'ok' and proc.returncode:
            status = 'nonzero'
    finally:
        # Handles grandchildren keeping stdout open and cancellation as well.
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        proc.wait()
        proc.stdout.close()
    return redact(out.decode(errors='replace')), {'status':status, 'returncode':proc.returncode,
                                                 'seconds':round(time.monotonic()-start,3)}

def expand_braces(pattern: str) -> list[str]:
    match = re.search(r'\{([^{}]+)\}', pattern)
    if not match:
        return [pattern]
    return [item for choice in match[1].split(',') for item in expand_braces(pattern[:match.start()]+choice+pattern[match.end():])]

def direct_text(path: Path, limit: int = MAX_FILE, sysfs: bool = False) -> tuple[str, dict]:
    # /sys/class paths are kernel-owned aliases; resolve only within /sys.
    original = path
    if sysfs:
        path = path.resolve()
        if not path.is_relative_to('/sys'):
            return '', {'status':'unsafe-symlink'}
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK
    try:
        fd = os.open(path, flags)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode):
                return '', {'status':'not-regular'}
            data = os.read(fd, limit+1)
        finally:
            os.close(fd)
        return redact(data[:limit].decode(errors='replace')), {'status':'output-limit' if len(data)>limit else 'ok', 'path':str(original)}
    except OSError as exc:
        return '', {'status':'unavailable', 'errno':exc.errno, 'path':str(original)}

def desktop_account():
    name = os.environ.get('SUDO_USER', '')
    if name and name != 'root':
        try:
            user = pwd.getpwnam(name)
            if user.pw_uid >= 1000:
                return user
        except KeyError:
            pass
    # Direct root invocation: select an existing active user manager, not root.
    candidates = [u for u in pwd.getpwall() if u.pw_uid >= 1000 and u.pw_uid < 65534
                  and Path(f'/run/user/{u.pw_uid}/bus').exists()]
    return candidates[0] if len(candidates) == 1 else None

def user_command(user, argv: list[str], wayland: bool = False) -> list[str] | None:
    runtime = Path(f'/run/user/{user.pw_uid}')
    try:
        st = runtime.lstat()
        bus = (runtime/'bus').lstat()
        if (not stat.S_ISDIR(st.st_mode) or st.st_uid != user.pw_uid
                or stat.S_IMODE(st.st_mode) != 0o700 or not stat.S_ISSOCK(bus.st_mode)
                or bus.st_uid != user.pw_uid):
            return None
    except OSError:
        return None
    env = [f'HOME={user.pw_dir}', f'USER={user.pw_name}', f'LOGNAME={user.pw_name}',
           f'XDG_RUNTIME_DIR={runtime}', f'DBUS_SESSION_BUS_ADDRESS=unix:path={runtime}/bus',
           f'SSH_AUTH_SOCK={runtime}/openssh_agent', 'PATH=/usr/bin:/bin', 'LC_ALL=C.UTF-8',
           'SYSTEMD_PAGER=', 'SYSTEMD_COLORS=0']
    if wayland:
        sockets = [p for p in runtime.glob('wayland-*') if re.fullmatch(r'wayland-[0-9]+',p.name)
                   and stat.S_ISSOCK(p.lstat().st_mode) and p.lstat().st_uid == user.pw_uid]
        if len(sockets) != 1:
            return None
        env += [f'WAYLAND_DISPLAY={sockets[0].name}', 'XDG_SESSION_TYPE=wayland']
    return ['/usr/sbin/runuser','-u',user.pw_name,'--','/usr/bin/env','-i',*env,*argv]

class Report:
    def __init__(self, categories: list[str], prefix: str = 'report'):
        safe_directory(LOGROOT)
        if shutil.disk_usage(LOGROOT).free < MAX_TOTAL + 128 * 1024 * 1024:
            raise DebugError('not enough free report space (224 MiB required); archive old reports explicitly')
        self.path = LOGROOT/(stamp()+'-'+prefix+'-'+uuid.uuid4().hex[:8])
        self.path.mkdir(mode=0o700)
        (self.path/'evidence').mkdir(mode=0o700)
        self.categories = categories
        self.records: list[dict] = []
        self.total = 0
        self.contents: dict[str,str] = {}
        self.started = dt.datetime.now(dt.timezone.utc).isoformat()
        self.user = desktop_account()
        self.deadline = time.monotonic()+900

    def add(self, category: str, label: str, text: str, metadata: dict, source=None):
        if self.total >= MAX_TOTAL:
            text = ''; metadata = dict(metadata, status='report-byte-limit')
        encoded = text.encode()
        available = max(0, MAX_TOTAL-self.total)
        if len(encoded) > available:
            encoded = encoded[:available]; metadata = dict(metadata, status='report-byte-limit')
        self.total += len(encoded)
        number = len(self.records)+1
        safe = re.sub('[^A-Za-z0-9_-]', '_', label)[:95]
        name = f'evidence/{number:04d}-{safe}.txt'
        atomic_write(self.path/name, encoded)
        self.records.append(dict(id=number, category=category, label=label, source=source,
                                 evidence=name, bytes=len(encoded), sha256=hashlib.sha256(encoded).hexdigest(), **metadata))
        # Only short excerpts kept for overview/rule evaluation, not entire logs.
        self.contents[label] = encoded[:24000].decode(errors='replace')

    def command(self, category: str, label: str, argv: list[str], timeout: int = 30):
        if self.total >= MAX_TOTAL:
            self.add(category,label,'',{'status':'report-byte-limit'},argv); return
        remaining = self.deadline-time.monotonic()
        if remaining <= 0:
            self.add(category,label,'',{'status':'report-time-limit'},argv); return
        try:
            text, meta = run(argv, min(timeout, max(.1,remaining)))
        except OSError as exc:
            text, meta = '', {'status':'unavailable','errno':exc.errno}
        self.add(category,label,text,meta,argv)

    def gather(self):
        self.command('system','collector-context',['id'])
        for category in self.categories:
            print(f'Gathering {category} evidence...', flush=True)
            for label, argv in PROBES[category]:
                self.command(category,label,argv,60 if label in ('unit-hardening','hardware-tree') else 30)
            seen = set()
            for pattern in FILES[category]:
                matched = False
                for expanded in expand_braces(pattern):
                    # A bounded iterator avoids expanding a massive tree in RAM.
                    for name in glob.iglob(expanded):
                        if name in seen:
                            continue
                        matched = True; seen.add(name)
                        if len(seen) > MAX_FILES or self.total >= MAX_TOTAL or time.monotonic() > self.deadline:
                            break
                        text, meta = direct_text(Path(name), sysfs=name.startswith('/sys/'))
                        self.add(category,name,text,meta,name)
                    if len(seen) > MAX_FILES or self.total >= MAX_TOTAL or time.monotonic() > self.deadline:
                        break
                if len(seen) > MAX_FILES or self.total >= MAX_TOTAL or time.monotonic() > self.deadline:
                    self.add(category,'file-coverage-limit','',{'status':'collection-limit'},pattern); break
                if not matched:
                    self.add(category,'no-matching-files','',{'status':'no-match'},pattern)
            self.dynamic(category)

    def dynamic(self, category: str):
        if category == 'storage':
            for path in sorted(Path('/sys/block').glob('*')):
                if re.fullmatch(r'(sd[a-z]+|vd[a-z]+|nvme[0-9]+n[0-9]+|mmcblk[0-9]+)',path.name):
                    self.command(category,'smart-'+path.name,['smartctl','-x','-n','standby','/dev/'+path.name])
            for path in sorted(Path('/sys/class/nvme').glob('nvme[0-9]*')):
                if re.fullmatch(r'nvme[0-9]+',path.name):
                    self.command(category,'nvme-health-'+path.name,['nvme','smart-log','-o','json','/dev/'+path.name])
                    self.command(category,'nvme-controller-'+path.name,['nvme','id-ctrl','-H','/dev/'+path.name])
            # Read-only filesystem-specific details for the installed root.
            self.command(category,'root-filesystem-type',['findmnt','-n','-o','FSTYPE','/'])
            text = self.contents.get('root-filesystem-type', '')
            ok = self.records[-1]['status'] == 'ok'
            if ok and text.strip() == 'btrfs':
                self.command(category,'btrfs-root',['btrfs','filesystem','usage','-b','/'])
                self.command(category,'btrfs-errors',['btrfs','device','stats','/'])
            elif ok and text.strip() == 'xfs':
                self.command(category,'xfs-root',['xfs_info','/'])
        if category == 'network':
            for path in sorted(Path('/sys/class/net').glob('*')):
                if re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,31}',path.name) and path.name != 'lo':
                    for suffix, option in [('driver','-i'),('offloads','-k'),('rings','-g'),('coalescing','-c')]:
                        self.command(category,'nic-'+path.name+'-'+suffix,['ethtool',option,path.name])
        if category == 'desktop':
            if not self.user:
                self.add(category,'user-session','No unique active desktop account; user probes were not attempted.',{'status':'no-session'})
                return
            probes = [
                ('user-failed',['systemctl','--user','--failed','--no-pager'],False),
                ('desktop-units',['systemctl','--user','show','labwc-session.target','labwc-compositor.service','pipewire.service','wireplumber.service','ssh-agent.socket','ssh-agent.service','labwc-ssh-key-load.service','--property='+ISOLATION_PROPERTIES+',NRestarts,PartOf,Requisite,BindsTo'],False),
                ('outputs',['wlr-randr'],True),('wayland-protocols',['wayland-info'],True),
                ('audio',['wpctl','status'],False),('pipewire',['pw-dump'],False),
                ('pulse',['pactl','info'],False),
            ]
            for label,argv,wayland in probes:
                command = user_command(self.user,argv,wayland)
                if command:
                    self.command(category,label,command)
                else:
                    self.add(category,label,'',{'status':'no-session'})
            self.command(category,'desktop-journal',['journalctl','-b',f'_UID={self.user.pw_uid}','--no-pager','-n','2000'])
        if category == 'credentials':
            if not self.user:
                self.add(category,'identity-metadata','No unique active desktop account.',{'status':'no-session'}); return
            command = user_command(self.user, ['systemctl','--user','show',
                'ssh-agent.socket','ssh-agent.service','labwc-ssh-key-load.service',
                '--property='+ISOLATION_PROPERTIES+',PartOf,Requisite,BindsTo'])
            if command:
                self.command(category,'managed-agent-units',command)
            else:
                self.add(category,'managed-agent-units','',{'status':'no-session'})
            home = Path(self.user.pw_dir)
            names = ['.ssh/config','.ssh/id_git_ed25519.pub','.local/share/managed-ssh/private/id_git_ed25519',
                     '.local/share/managed-ssh/git-key-passphrase.gpg','.gnupg','.gnupg/gpg-agent.conf',
                     '.config/gitops/gitops.env','.config/git/config']
            records = []
            for name in names:
                try:
                    st=(home/name).lstat()
                    records.append({'path':str(home/name),'uid':st.st_uid,'gid':st.st_gid,
                                    'mode':oct(stat.S_IMODE(st.st_mode)),'size':st.st_size,'symlink':stat.S_ISLNK(st.st_mode)})
                except OSError as exc:
                    records.append({'path':str(home/name),'unavailable':exc.errno})
            self.add(category,'identity-metadata',json.dumps(records,indent=2),{'status':'ok'})
            # Listing fingerprints does not ask the agent to sign or GPG to decrypt.
            command=user_command(self.user,['ssh-add','-l','-E','sha256'])
            sock=Path(f'/run/user/{self.user.pw_uid}/openssh_agent')
            try:
                st=sock.lstat()
                safe=stat.S_ISSOCK(st.st_mode) and st.st_uid==self.user.pw_uid and stat.S_IMODE(st.st_mode)==0o600
            except OSError:
                safe=False
            if command and safe:
                self.command(category,'agent-fingerprints',command)
            else:
                self.add(category,'agent-fingerprints','Managed agent unavailable or unsafe.',{'status':'no-session'})

    def initramfs_evidence(self):
        source=Path('/run/initramfs/debugsys')
        if not source.exists():
            self.add('boot','early-capture','No early-boot capture available. Use menu option 3, then reboot.',{'status':'not-armed'})
            return
        st=source.lstat()
        if not stat.S_ISDIR(st.st_mode) or st.st_uid!=0 or stat.S_IMODE(st.st_mode)!=0o700:
            raise DebugError('unsafe initramfs capture directory')
        for i,path in enumerate(sorted(source.iterdir())):
            if i>=64:
                self.add('boot','early-capture-limit','',{'status':'file-count-limit'}); break
            text,meta=direct_text(path,1024*1024)
            self.add('boot','early-'+path.name,text,meta,str(path))

    def finish(self, interrupted: bool = False):
        counts=collections.Counter(item['status'] for item in self.records)
        coverage={category:dict(collections.Counter(item['status'] for item in self.records if item['category']==category))
                  for category in self.categories}
        summary={'created_utc':self.started,'completed_utc':dt.datetime.now(dt.timezone.utc).isoformat(),
                 'categories':self.categories,'effective_uid':os.geteuid(),'desktop_account':self.user.pw_name if self.user else None,
                 'interrupted':interrupted,'evidence_count':len(self.records),'bytes':self.total,'outcomes':dict(counts),
                 'coverage':coverage,'limits':{'probe_bytes':MAX_OUTPUT,'file_bytes':MAX_FILE,'report_bytes':MAX_TOTAL,'files_per_category':MAX_FILES},
                 'privacy':'Root-only; redaction is best-effort. Inspect before sharing. No private key contents or process environments were collected.'}
        atomic_write(self.path/'manifest.json',json.dumps(self.records,indent=2).encode())
        atomic_write(self.path/'summary.json',json.dumps(summary,indent=2).encode())
        overview=['# System diagnostic overview','',f'UTC: {self.started}',f'Categories: {", ".join(self.categories)}',
                  f'Evidence records: {len(self.records)}; outcomes: {dict(counts)}','',
                  '**Privacy:** This report is root-only. Logs, addresses, serial numbers and usernames can be sensitive. Redaction is best-effort; review before sharing.',
                  '**Coverage:** Missing tools, unreadable interfaces, timeouts, output limits and no active desktop are recorded below. They are not evidence of health or hardware absence.',
                  '**Safety:** Collection is read-only. No tuning, network scan, benchmark, firmware update or key decryption was performed.','', '## Coverage by area','']
        overview += [f'- **{c}:** {coverage[c]}' for c in self.categories]
        highlights=('kernel','cpu','firmware-memory','failed-units','package-audit','memory','swap','filesystem-space',
                    'boot-times','boot-chain','desktop-units','outputs','audio','apparmor','secure-boot','addresses','dns','identity-metadata','managed-agent-units','service-isolation')
        for label in highlights:
            matches=[x for x in self.records if x['label']==label]
            if not matches: continue
            rec=matches[0]; excerpt=self.contents[label][:6000]
            overview += ['',f'## {label} ({rec["status"]})',f'Evidence: [{rec["evidence"]}]({rec["evidence"]})','',
                         '```text',excerpt.replace('```','[code fence]'),'```']
        overview += ['', '## Evidence index', '', '| ID | Area | Probe/source | Outcome | Evidence |', '|---|---|---|---|---|']
        for rec in self.records:
            label=rec['label'].replace('|','\\|').replace('\n',' ')
            overview.append(f'| {rec["id"]} | {rec["category"]} | {label} | {rec["status"]} | [{rec["evidence"]}]({rec["evidence"]}) |')
        atomic_write(self.path/'OVERVIEW.md','\n'.join(overview).encode())
        self.tuning()
        print(f'Report: {self.path}/OVERVIEW.md',flush=True)
        print('Structured summary and SHA-256 evidence manifest are alongside the overview.',flush=True)

    def tuning(self):
        lines=['# Hardware tuning review','',
               'These are evidence-linked review opportunities, not measured performance gains. No settings were changed. Benchmark one reversible change at a time against the actual workload.',
               'Keep CPU security mitigations, IOMMU protection and disk integrity safeguards enabled. Do not use blanket ASPM or NVMe power overrides.','']
        rules=[
          ('cpufreq','CPU frequency / energy preference','Review the recorded driver, governor, available policies and energy preference together. A performance policy can trade power/heat for latency; a powersave name alone does not prove a fixed slow clock.'),
          ('cpuidle','CPU idle latency','Compare idle-state latency/residency with workload latency requirements; do not disable deep idle states globally based on a single snapshot.'),
          ('power_supply','Battery health and power budget','Compare full versus design energy, cycles and current supply status. Battery-health estimates depend on firmware calibration; do not infer degradation from a missing field.'),
          ('current_link','PCIe link capacity','Compare current and maximum width/speed with the device workload and its slot. An idle link can downshift normally; confirm under a representative workload before treating this as a bottleneck.'),
          ('/power/control','Device runtime power','Identify devices forced on versus auto. Evaluate wake reliability and USB/network stability before any device-specific runtime-PM change.'),
          ('temp','Thermal headroom','Compare temperature inputs with the same device critical/trip thresholds and observed throttling logs; units and firmware thresholds matter.'),
          ('/queue/','Storage queues and read-ahead','Compare scheduler, rotational flag, logical/physical block sizes and read-ahead with the workload. Do not apply one scheduler or queue depth to every device.'),
          ('pressure','Memory / I/O contention','Use the bounded vmstat/iostat samples and pressure counters to identify a candidate bottleneck. Confirm sustained pressure rather than treating cumulative counters as current saturation.'),
          ('transparent_hugepage','Transparent huge pages','Evaluate the selected THP policy against the application and latency profile; an enabled policy is not in itself a fault.'),
          ('nic-','Network offload and queue policy','Review driver/firmware, counters, offloads, rings and coalescing. Changes can trade CPU use, throughput and latency; this report does not send traffic or change links.'),
          ('nvme-health','NVMe endurance and errors','Review health warnings, spare capacity, media errors and temperature before experimenting with power states. Back up data before maintenance.'),
          ('smart-','Disk health','Review individual SMART flags and attributes. smartctl uses bitmask exit statuses; a nonzero result is not necessarily a command failure. Sleeping disks are not deliberately awakened.'),
        ]
        for token,title,advice in rules:
            records=[r for r in self.records if token in r['label'] and r['status']=='ok']
            if records:
                links=', '.join(f'[{r["id"]}]({r["evidence"]})' for r in records[:12])
                lines += [f'## {title}',advice,f'Evidence: {links}', '']
        lines += ['## Boundaries','Unavailable probes do not prove a feature is unsupported. This is a sequential snapshot, not synchronized tracing; no MSR writes, stress tests, exhaustive device tests or firmware flashing occur.',
                  'Reference semantics: Linux CPUFreq and intel_pstate documentation; Linux PSI documentation; Debian initramfs-tools manual. See the installed managed-git README for source references.']
        atomic_write(self.path/'TUNING.md','\n'.join(lines).encode())

INITRAMFS = Path('/etc/initramfs-tools')
BOOT = Path('/boot')
UNIT = 'debugsys-boot-report.service'

def hook_files() -> dict[Path, bytes]:
    """Only these exact files belong to this feature; never remove other hooks."""
    source = TEMPLATES/'hook'
    st = source.lstat()
    if not stat.S_ISREG(st.st_mode) or st.st_uid != 0 or st.st_mode & 0o022:
        raise DebugError('unsafe initramfs hook template')
    content = source.read_bytes()
    if MARKER.encode() not in content[:512]:
        raise DebugError('initramfs template marker missing')
    files = {INITRAMFS/'hooks/debugsys': content}
    for phase in PHASES:
        files[INITRAMFS/'scripts'/phase/'debugsys'] = (
            '#!/bin/sh\n'+MARKER+'\nPREREQ=""\n'
            'case "${1:-}" in prereqs) echo "$PREREQ"; exit 0 ;; esac\n'
            f'/usr/local/libexec/debugsys-initramfs {phase} || :\nexit 0\n').encode()
    return files

def previous_file(path: Path) -> tuple[bytes, int] | None:
    if not path.exists() and not path.is_symlink():
        return None
    st = path.lstat()
    if (not stat.S_ISREG(st.st_mode) or st.st_uid != 0 or st.st_nlink != 1
            or st.st_mode & 0o022 or st.st_size > MAX_FILE):
        raise DebugError(f'unsafe managed hook/state file: {path}')
    data = path.read_bytes()
    if MARKER.encode() not in data[:512]:
        raise DebugError(f'refusing to replace an unmanaged file: {path}')
    return data, stat.S_IMODE(st.st_mode)

def successful(argv: list[str], journal: Path, label: str, timeout: int = 60) -> str:
    text, meta = run(argv, timeout, 8*1024*1024)
    atomic_write(journal/(label+'.log'), text.encode())
    atomic_write(journal/(label+'.json'), json.dumps(meta,indent=2).encode())
    if meta['status'] != 'ok':
        raise DebugError(f'{label} failed ({meta["status"]}); details: {journal}')
    return text

def verify_images(enabled: bool, journal: Path):
    # Match update-initramfs -u -k all: installed versions with existing images.
    # A .bak/.dpkg-bak or orphaned rescue image is NOT an installed kernel and
    # must not turn successful removal into an endless rollback/rebuild cycle.
    versions = successful(['linux-version','list'],journal,'installed-kernels').splitlines()
    if any(not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9.+~_-]*',v) for v in versions):
        raise DebugError('unsafe installed kernel version')
    images = [BOOT/('initrd.img-'+v) for v in sorted(set(versions))
              if (BOOT/('initrd.img-'+v)).exists() or (BOOT/('initrd.img-'+v)).is_symlink()]
    if not images:
        raise DebugError('no installed-kernel initramfs images found after rebuild')
    retained = sorted(str(p) for p in BOOT.glob('initrd.img-*') if p not in images)
    atomic_write(journal/'retained-other-images.json',json.dumps(retained,indent=2).encode())
    expected = ['usr/local/libexec/debugsys-initramfs', *[f'scripts/{p}/debugsys' for p in PHASES]]
    for index, image in enumerate(images):
        st = image.lstat()
        if not stat.S_ISREG(st.st_mode) or st.st_uid != 0 or st.st_mode & 0o022:
            raise DebugError(f'unsafe initramfs image: {image}')
        # lsinitramfs reads an archive; it neither boots nor executes its contents.
        listing = successful(['lsinitramfs',str(image)],journal,f'image-{index}',120)
        entries = {line.strip().removeprefix('./') for line in listing.splitlines()}
        present = [name in entries for name in expected]
        if enabled and not all(present) or not enabled and any(present):
            raise DebugError(f'initramfs hook verification failed: {image}')

def change_hooks(enabled: bool):
    files = hook_files()
    armed = STATE/'armed'
    desired = dict(files)
    desired[armed] = (MARKER+'\nCapture remains enabled until explicitly removed.\n').encode()
    # Validate the complete set before changing anything.
    saved = {path:previous_file(path) for path in desired}
    safe_directory(STATE)
    journal = STATE/('transaction-'+stamp()+'-'+uuid.uuid4().hex[:8])
    journal.mkdir(mode=0o700)
    manifest = []
    for number,(path,before) in enumerate(saved.items()):
        backup = f'before-{number}' if before else None
        if before:
            atomic_write(journal/backup,before[0],before[1])
        manifest.append({'path':str(path),'backup':backup,'mode':before[1] if before else None})
    atomic_write(journal/'before.json',json.dumps(manifest,indent=2).encode())
    _, unit_meta = run(['systemctl','is-enabled',UNIT])
    was_enabled = unit_meta['status'] == 'ok'
    changed = False
    try:
        for path,content in desired.items():
            if enabled:
                safe_directory(path.parent,0o700 if path == armed else 0o755)
                changed = True
                atomic_write(path,content,0o600 if path == armed else 0o755)
            else:
                changed = True
                path.unlink(missing_ok=True)
        print('Rebuilding all installed initramfs images. No reboot is performed.',flush=True)
        successful(['update-initramfs','-u','-k','all'],journal,'rebuild',900)
        verify_images(enabled,journal)
        successful(['systemctl','enable' if enabled else 'disable',UNIT],journal,'unit-state')
        atomic_write(journal/'result.json',json.dumps({'success':True,'enabled':enabled}).encode())
    except BaseException as exc:
        # A failed update may already have rewritten some kernel images. Restore
        # every before-image and rebuild ALL kernels again, not just the last one.
        failures = []
        if changed:
            for path,before in saved.items():
                try:
                    if before:
                        atomic_write(path,*before)
                    else:
                        path.unlink(missing_ok=True)
                except (DebugError,OSError) as error:
                    failures.append(f'cannot restore {path}: {error}')
            try:
                successful(['update-initramfs','-u','-k','all'],journal,'rollback-rebuild',900)
                rollback_images=journal/'rollback-images'
                rollback_images.mkdir(mode=0o700)
                verify_images(saved[armed] is not None,rollback_images)
                successful(['systemctl','enable' if was_enabled else 'disable',UNIT],journal,'rollback-unit')
            except (DebugError,OSError) as error:
                failures.append(str(error))
        atomic_write(journal/'result.json',json.dumps({'success':False,'error':str(exc),'rollback_errors':failures},indent=2).encode())
        suffix = (' ROLLBACK INCOMPLETE: '+ '; '.join(failures)+'. Do not reboot until repaired.') if failures else ' Previous hooks restored and images rebuilt.'
        raise DebugError(f'Hook transaction failed: {exc}.{suffix} Recovery records: {journal}') from exc
    print(('Early-boot capture is armed for the next boot; hooks remain until removed.' if enabled
           else 'Managed hooks removed; all initramfs images rebuilt and verified. Existing reports retained.'),flush=True)
    print(f'Operation record: {journal}',flush=True)

def collect(categories: list[str], prefix: str = 'report', budget: int = 900):
    report = Report(categories,prefix)
    report.deadline = time.monotonic()+budget
    interrupted = False
    try:
        report.gather()
        if 'boot' in categories:
            report.initramfs_evidence()
    except BaseException:
        interrupted = True
        raise
    finally:
        report.finish(interrupted)
    return report.path

def status():
    print('\nEarly-boot capture: '+('ARMED' if (STATE/'armed').is_file() else 'not armed'))
    print('Initramfs evidence: '+('available' if Path('/run/initramfs/debugsys').is_dir() else 'not available in this boot'))
    print(f'Reports: {LOGROOT}')
    if LOGROOT.exists():
        safe_directory(LOGROOT)
        for path in sorted(LOGROOT.iterdir(),reverse=True)[:25]:
            if not path.is_symlink() and path.is_dir() and (path/'OVERVIEW.md').is_file():
                print('  '+str(path/'OVERVIEW.md'))
    print('Reports are root-only; inspect for sensitive information before sharing.\n')

MENU = {
 1: ('Hardware inventory and tuning review', ['hardware','storage']),
 2: ('System health and service debugging report', ['system','boot']),
 3: ('Prepare next-boot initramfs capture (rebuild all images)', []),
 4: ('Boot timeline and captured initramfs evidence report', ['boot']),
 5: ('Remove managed initramfs hooks (rebuild all images)', []),
 6: ('Labwc, graphics, audio and desktop-session report', ['desktop']),
 7: ('AppArmor, process isolation and security report', ['security']),
 8: ('Storage, memory pressure and device-health report', ['storage']),
 9: ('Network, driver and connectivity-state report', ['network']),
 10: ('Git/SSH/GPG integration metadata (no secret contents)', ['credentials']),
 11: ('Comprehensive overview and all read-only reports', list(CATEGORIES)),
 12: ('Show capture status and saved report locations', []),
}

def selections(value: str) -> list[int]:
    chosen = set()
    tokens = value.replace(',',' ').split()
    if not tokens:
        raise DebugError('choose at least one entry')
    for token in tokens:
        if re.fullmatch(r'[0-9]{1,2}',token):
            chosen.add(int(token))
        elif re.fullmatch(r'[0-9]{1,2}-[0-9]{1,2}',token):
            first,last=map(int,token.split('-'))
            if not 1 <= first <= last <= 12:
                raise DebugError('range must be ascending between 1 and 12')
            chosen.update(range(first,last+1))
        else:
            raise DebugError('use numbers, commas, spaces or ranges such as 1,6-9')
    if not chosen <= {0,*MENU} or 0 in chosen and len(chosen)>1:
        raise DebugError('choose 0 alone to exit, or entries 1 through 12')
    if {3,5} <= chosen:
        raise DebugError('arming and removing hooks cannot be selected together')
    return sorted(chosen)

def confirm(enabled: bool, yes: bool):
    if yes:
        return
    action='ARM' if enabled else 'REMOVE'
    print('This changes only debugsys hooks and rebuilds ALL installed initramfs images.')
    print('Existing reports are retained. No tuning or reboot is performed.')
    if not sys.stdin.isatty() or input(f'Type {action} to proceed: ').strip() != action:
        raise DebugError('boot configuration change cancelled; nothing changed')

def menu():
    while True:
        print('\nDEBUGSYS | System evidence and early-boot diagnostics\n')
        for number,(label,_) in MENU.items():
            print(f' [{number:2d}] {label}')
        print(' [ 0] Exit\nSelect multiple entries: 1,6-9. Entry 11 never changes boot configuration.')
        try:
            chosen=selections(input('Selection: '))
            if chosen == [0]:
                return
            print('\nSelected: '+ '; '.join(MENU[n][0] for n in chosen))
            if 3 in chosen or 5 in chosen:
                confirm(3 in chosen,False)
            with lock():
                if 3 in chosen or 5 in chosen:
                    change_hooks(3 in chosen)
                categories=[c for c in CATEGORIES if any(c in MENU[n][1] for n in chosen)]
                if categories:
                    collect(categories)
                if 12 in chosen:
                    status()
        except (DebugError,OSError) as exc:
            print(f'debugsys: {exc}',file=sys.stderr)
        except (EOFError,KeyboardInterrupt):
            print('\nLeaving debugsys. Completed and partial reports are retained.')
            return

def main() -> int:
    if os.geteuid() != 0:
        raise DebugError('use /usr/local/bin/debugsys; collection must enter sudo -i')
    os.umask(0o077)
    import resource
    resource.setrlimit(resource.RLIMIT_CORE,(0,0))
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='action')
    report=sub.add_parser('report',help='read-only report; no boot changes')
    report.add_argument('--categories',nargs='+',choices=CATEGORIES,default=list(CATEGORIES))
    for action in ('boot-enable','boot-disable'):
        sub.add_parser(action).add_argument('--yes',action='store_true',help='explicitly authorize the initramfs rebuild')
    sub.add_parser('boot-finalize',help=argparse.SUPPRESS)
    sub.add_parser('status')
    args=parser.parse_args()
    if args.action is None:
        if not sys.stdin.isatty():
            parser.error('interactive menu requires a terminal; use report or status')
        menu(); return 0
    if args.action == 'status':
        status(); return 0
    with lock():
        if args.action == 'report':
            collect(list(dict.fromkeys(args.categories)))
        elif args.action.startswith('boot-') and args.action != 'boot-finalize':
            enabled=args.action == 'boot-enable'
            confirm(enabled,args.yes); change_hooks(enabled)
        elif args.action == 'boot-finalize':
            if not (STATE/'armed').is_file() or not Path('/run/initramfs/debugsys').is_dir():
                return 0
            boot_id=Path('/proc/sys/kernel/random/boot_id').read_text().strip()
            if not re.fullmatch('[0-9a-f-]{36}',boot_id):
                raise DebugError('invalid kernel boot ID')
            marker=STATE/'last-captured-boot'
            if marker.exists() and marker.read_text().strip()==boot_id:
                return 0
            collect(['boot','system'],'early-boot',budget=180)
            atomic_write(marker,(boot_id+'\n').encode())
    return 0

if __name__ == '__main__':
    for sig in (signal.SIGTERM,signal.SIGHUP):
        signal.signal(sig,lambda signum,frame: sys.exit(128+signum))
    try:
        raise SystemExit(main())
    except (DebugError,OSError) as error:
        print(f'debugsys: {error}',file=sys.stderr)
        raise SystemExit(1)
    except KeyboardInterrupt:
        print('debugsys: interrupted; completed and partial evidence retained',file=sys.stderr)
        raise SystemExit(130)
