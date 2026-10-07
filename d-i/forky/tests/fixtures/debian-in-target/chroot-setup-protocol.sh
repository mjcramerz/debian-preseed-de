# TEST-ONLY reduction of debian-installer-utils 1.155 chroot-setup.sh.
# The query/locale/unset sequence below is retained. Filesystem setup, package
# diversions and mounts are replaced by markers in an isolated temporary chroot.
# This file is never in the served installer payload.
chroot_setup () {
    logger -t "$0" "warning: /target/etc/mtab won't be updated since it is a symlink."
    printf 'setup-entered\n' >>/var/log/target-protocol-progress

    RET=$(debconf-get mirror/protocol || true)
    if [ "$RET" = "http" ]; then
        RET=$(debconf-get mirror/http/proxy || true)
        if [ "$RET" ]; then
            http_proxy="$RET"
            export http_proxy
        fi
    fi

    DEBIAN_PRIORITY=$(debconf-get debconf/priority || true)
    export DEBIAN_PRIORITY
    LANG=${IT_LANG_OVERRIDE:-$(debconf-get debian-installer/locale || true)}
    export LANG
    export PERL_BADLANG=0
    unset DEBIAN_HAS_FRONTEND
    unset DEBIAN_FRONTEND
    unset DEBCONF_FRONTEND
    unset DEBCONF_REDIR
    DEBCONF_ADMIN_EMAIL=""
    export DEBCONF_ADMIN_EMAIL
    APT_LISTCHANGES_FRONTEND=none
    export APT_LISTCHANGES_FRONTEND
    SUDO_FORCE_REMOVE=yes
    export SUDO_FORCE_REMOVE

    printf 'setup-completed\n' >>/var/log/target-protocol-progress
    return 0
}
chroot_cleanup () {
    printf 'cleanup-completed\n' >>/var/log/target-protocol-progress
}
