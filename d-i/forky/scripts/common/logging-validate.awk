# POSIX awk. Schema + literal .env -> resolved NAME=VALUE map, or no output.
# Values are never evaluated by a shell, sed replacement engine, or awk source.
function fail(message) {
    print "logging: " FILENAME ":" FNR ": " message > "/dev/stderr"
    bad=1; exit 1
}
function normalized(path) {
    return path ~ /^\/[A-Za-z0-9_.\/-]+$/ && path !~ /\/\// &&
        path !~ /\/$/ && path !~ /\/(\.|\.\.)(\/|$)/
}
FILENAME == ARGV[1] {
    if ($0 ~ /^#/ || $0 == "") next
    n=split($0, f, "\t")
    if (n < 2 || n > 3 || f[1] !~ /^LOG_[A-Z0-9_]+$/ || f[1] in kind)
        fail("invalid or duplicate schema row")
    order[++count]=f[1]; kind[f[1]]=f[2]; bound[f[1]]=f[3]; next
}
{
    if ($0 ~ /^[ \t]*#/ || $0 ~ /^[ \t]*$/) next
    if ($0 !~ /^LOG_[A-Z0-9_]+="[A-Za-z0-9_.\/@${}-]+"$/)
        fail("expected one quoted logging assignment; commands/escapes are forbidden")
    name=$0; sub(/=.*/, "", name)
    if (!(name in kind) || name in value) fail("unknown or duplicate key: " name)
    val=$0; sub(/^[^=]+="/, "", val); sub(/"$/, "", val)
    while (match(val, /\$\{LOG_[A-Z0-9_]+\}/)) {
        ref=substr(val,RSTART+2,RLENGTH-3)
        if (!(ref in value)) fail("forward/unknown reference: " ref)
        val=substr(val,1,RSTART-1) value[ref] substr(val,RSTART+RLENGTH)
    }
    if (val ~ /[$}{]/) fail("unresolved reference: " name)
    type=kind[name]
    if (type == "root") {
        if (val !~ /^\/var\/log\/managed(-[A-Za-z0-9_-]+)?$/)
            fail("LOG_ROOT must be a dedicated managed directory under /var/log")
    } else if (type == "managed") {
        if (!normalized(val) || index(val,value["LOG_ROOT"] "/") != 1)
            fail("managed destination escapes LOG_ROOT: " name)
    } else if (type == "state") {
        if (!normalized(val) || index(val,bound[name] "/") != 1)
            fail("invalid protected state path: " name)
    } else if (type == "int") {
        split(bound[name], limits, ",")
        if (val !~ /^[1-9][0-9]*$/ || length(val)>9 || val+0<limits[1]+0 || val+0>limits[2]+0)
            fail("integer out of range: " name)
    } else if (type == "enum") {
        if (index("," bound[name] ",", "," val ",") == 0)
            fail("unsupported value: " name)
    } else fail("unknown schema type")
    value[name]=val
}
END {
    if (bad) exit 1
    for (i=1;i<=count;i++) if (!(order[i] in value)) {
        print "logging: missing key: " order[i] > "/dev/stderr"; bad=1
    }
    if (bad) exit 1
    if (!(value["LOG_RSYSLOG_QUEUE_LOW"]+0 < value["LOG_RSYSLOG_QUEUE_HIGH"]+0 &&
          value["LOG_RSYSLOG_QUEUE_HIGH"]+0 < value["LOG_RSYSLOG_QUEUE_MESSAGES"]+0))
        fail("queue watermarks must satisfy low < high < size")
    if (value["LOG_RSYSLOG_QUEUE_SEGMENT_MIB"]+0 > value["LOG_RSYSLOG_QUEUE_DISK_MIB"]+0)
        fail("queue segment exceeds disk budget")
    if (value["LOG_CROWDSEC_FILE"] != value["LOG_CROWDSEC_DIR"] "/crowdsec.log" ||
        value["LOG_CROWDSEC_API_FILE"] != value["LOG_CROWDSEC_DIR"] "/crowdsec_api.log" ||
        value["LOG_CROWDSEC_BOUNCER_FILE"] != value["LOG_CROWDSEC_DIR"] "/crowdsec-firewall-bouncer.log")
        fail("CrowdSec native filenames are fixed; customize LOG_CROWDSEC_DIR instead")
    if (value["LOG_JOURNAL_DIR"] != "/var/lib/journal" ||
        value["LOG_BOOT_DIR"] != value["LOG_JOURNAL_DIR"] "/boot" ||
        value["LOG_POWER_DIR"] != value["LOG_JOURNAL_DIR"] "/power" ||
        value["LOG_POWER_ACTIONS_FILE"] != value["LOG_POWER_DIR"] "/actions.log")
        fail("journal state must use /var/lib/journal/{boot,power}")
    split("APPS SECURITY SYSTEM DESKTOP MODELS", categories, " ")
    for (i=1;i<=5;i++) {
        key="LOG_" categories[i] "_DIR"
        if (value[key] !~ ("^" value["LOG_ROOT"] "/[A-Za-z0-9_-]+$"))
            fail("category must be a direct child of LOG_ROOT: " key)
        if (value[key] in category_paths) fail("duplicate logging category")
        category_paths[value[key]]=key
    }
    for (i=1;i<=count;i++) {
        key=order[i]
        if (kind[key] != "managed") continue
        if (key != "LOG_CLAMAV_DIR" && key != "LOG_CLAMAV_FILE" && key != "LOG_FRESHCLAM_FILE" &&
            index(value[key],value["LOG_CLAMAV_DIR"] "/")==1)
            fail("non-ClamAV path under daemon-owned directory: " key)
        for (j=1;j<=2;j++) {
            private_key=(j==1 ? "LOG_CODEX_RUNTIME_DIR" : "LOG_CHATGPT_RUNTIME_DIR")
            allowed=(j==1 ? "LOG_CODEX_(RUNTIME_DIR|LOGIN_FILE|TUI_FILE)" : "LOG_CHATGPT_RUNTIME_(DIR|LOGIN_FILE|TUI_FILE)")
            if (key !~ ("^" allowed "$") &&
                (value[key]==value[private_key] || index(value[key],value[private_key] "/")==1))
                fail("protected output under private runtime directory: " key)
        }
    }
    if (index(value["LOG_CLAMAV_FILE"],value["LOG_CLAMAV_DIR"] "/") != 1 ||
        substr(value["LOG_CLAMAV_FILE"],length(value["LOG_CLAMAV_DIR"])+2) ~ /\// ||
        index(value["LOG_FRESHCLAM_FILE"],value["LOG_CLAMAV_DIR"] "/") != 1 ||
        substr(value["LOG_FRESHCLAM_FILE"],length(value["LOG_CLAMAV_DIR"])+2) ~ /\//)
        fail("ClamAV files must be direct children of their native directory")
    # An alias is intentional only for the single clamscan destination.
    for (i=1;i<=count;i++) {
        key=order[i]
        if (key ~ /_FILE$/ && key != "LOG_CLAMAV_SCAN_FILE") {
            if (value[key] in files) fail("two writers share a logfile: " key " / " files[value[key]])
            files[value[key]]=key
        }
    }
    for (i=1;i<=count;i++) print order[i] "=" value[order[i]]
}
