# Permanent measured-boot enrollment policy; kept for kernel/initrd updates.
abi "/usr/share/apparmor-features/features",
#include <tunables/global>

profile tpm2-enroll /usr/local/sbin/tpm2-enroll.sh flags=(attach_disconnected) {
  #include <abstractions/wrapper-terminal>
  #include <abstractions/wrapper-base>

  /usr/local/sbin/tpm2-enroll.sh rix,
  /usr/local/libexec/tpm2-policy-check rix,
  /usr/bin/python3{,.[0-9]*} rix,
  /usr/lib/python3*/** mr,
  /usr/local/lib/python3*/** mr,
  /usr/{bin,sbin}/{tpm2_pcrread,lsinitramfs} PUx,
  /sys/kernel/security/tpm0/binary_bios_measurements r,
  /proc/sys/kernel/random/boot_id r,
  /boot/ r,
  /etc/initramfs-tools/scripts/installer-health-common r,
  /var/lib/tpm2-enrollment/boot-artifacts-cleaned rwk,
  /boot/initrd.img-* r,
  /var/lib/tpm2-enrollment/.enrollment-* rwk,
  /var/lib/tpm2-enrollment/enrollment.json rwk,
  /var/lib/tpm2-enrollment/enrollment.lock rwk,
  /usr/bin/{awk,chmod,cmp,date,dirname,flock,gawk,grep,id,install,mawk,mktemp,nawk,readlink,rm,stty} rix,
  /usr/bin/{mokutil,systemctl,systemd-cryptenroll} PUx,
  /usr/{bin,sbin}/cryptsetup PUx,
  /dev/tty rw,
  /dev/disk/by-uuid/ r,
  /dev/disk/by-uuid/* r,
  /dev/mapper/ r,
  /dev/mapper/* r,
  /dev/{mmcblk[0-9]*p[0-9]*,nvme[0-9]*n[0-9]*p[0-9]*,sd[a-z][0-9]*,vd[a-z][0-9]*} r,
  /etc/cryptsetup-keys.d/crypthome.key r,
  /run/lock/tpm2-enroll.lock rwk,
  owner /run/tpm2-enroll.*/ rw,
  owner /run/tpm2-enroll.*/** rwkl,
  /var/lib/tpm2-enrollment/ rw,
  /var/lib/tpm2-enrollment/config.env r,
  /var/lib/tpm2-enrollment/install-passphrase rw,
  /var/lib/tpm2-enrollment/tpm2-enroll.complete rwk,
  /var/lib/tpm2-enrollment/tpm2-enroll.pending rw,

  include if exists <local/usr.local.sbin.tpm2-enroll.sh>
}
