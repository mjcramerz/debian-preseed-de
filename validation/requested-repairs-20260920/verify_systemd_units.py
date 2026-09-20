from pathlib import Path
import tempfile,shutil,subprocess
source=Path(__file__).resolve().parents[2] / 'd-i/forky/hooks/target'
names=['grub-btrfs-refresh.'+s for s in ('service','path','timer')]+['timeshift-'+s+'.service' for s in ('daily','weekly','monthly')]
with tempfile.TemporaryDirectory(prefix='repair-unit-verify-') as td:
 root=Path(td)
 units=root/'etc/systemd/system';units.mkdir(parents=True)
 for name in names:shutil.copy2(source/'etc/systemd/system'/name,units/name)
 for name in ('sysinit','basic','shutdown','local-fs','timers','paths','multi-user'):
  (units/(name+'.target')).write_text('[Unit]\nDescription=Test-only dependency target\nDefaultDependencies=no\n')
 for name in ('grub-btrfs-refresh','timeshift-managed-snapshot'):
  p=root/'usr/local/libexec'/name;p.parent.mkdir(parents=True,exist_ok=True)
  shutil.copy2(source/'usr/local/libexec'/name,p);p.chmod(0o755)
 p=root/'usr/bin/systemctl';p.parent.mkdir(parents=True,exist_ok=True);shutil.copy2('/usr/bin/systemctl',p)
 (root/'etc/os-release').write_text('ID=debian\nVERSION_ID=13\n')
 result=subprocess.run(['systemd-analyze','verify','--man=no','--generators=no','--root='+str(root),*['/etc/systemd/system/'+n for n in names]],capture_output=True,text=True)
 print('Real systemd-analyze verify; isolated fixture root; target executables copied but NOT executed.')
 print('Dependency targets are explicit fixture stubs, not a live system-manager integration test.')
 print(result.stdout+result.stderr,end='');print('Exit status:',result.returncode)
 raise SystemExit(result.returncode)
