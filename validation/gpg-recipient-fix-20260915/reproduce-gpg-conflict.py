"""Reproduce old sealing logic with disposable, non-deployment GPG keys."""
import argparse, importlib.util, os, pathlib, pwd, subprocess, tempfile
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('baseline_root', type=pathlib.Path)
args=parser.parse_args()
if os.geteuid()!=0: raise SystemExit('This disposable fixture requires root for the installer entry point.')
source=args.baseline_root/'d-i/forky/hooks/target/usr/local/libexec/managed-ssh-install.py'
spec=importlib.util.spec_from_file_location('old_ssh',source); mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
with tempfile.TemporaryDirectory(prefix='gpg-conflict-',dir='/root') as tmp:
 home=pathlib.Path(tmp); gp=home/'.gnupg';gp.mkdir(mode=0o700)
 env=dict(mod.BASE_ENV,HOME=str(home),GNUPGHOME=str(gp))
 try:
  for uid,algo,usage in [('Aptly signing fixture','ed25519','sign'),('Managed desktop fixture','future-default','default')]:
   subprocess.run(['gpg','--no-options','--batch','--pinentry-mode','loopback','--passphrase-fd','0','--quick-generate-key',uid,algo,usage,'never'],env=env,input=b'disposable-fixture-passphrase\n',capture_output=True,check=True,timeout=45)
  listing=subprocess.run(['gpg','--no-options','--batch','--with-colons','--list-secret-keys'],env=env,capture_output=True,check=True).stdout.decode()
  print('Two generated secret identities; primary capability fields:',[r.split(':')[11] for r in listing.splitlines() if r.startswith('sec:')])
  try:mod.seal(pwd.getpwuid(0),home,b'disposable-ssh-secret')
  except mod.InstallError as exc:
   print('PRE-FIX REPRODUCED:',type(exc).__name__+':',str(exc))
   assert str(exc)=='managed GPG key cannot encrypt'
  else:raise AssertionError('Expected baseline failure was not reproduced')
  assert not (home/'.local/share/managed-ssh/git-key-passphrase.gpg').exists()
 finally:subprocess.run(['gpgconf','--kill','gpg-agent'],env=env,capture_output=True)
