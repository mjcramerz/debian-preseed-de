# Literal replacement, not gsub replacement-string processing or shell eval.
function die(message) {
    print "theme rendering: " FILENAME ":" FNR ": " message > "/dev/stderr"
    failed=1
    exit 1
}
FILENAME == ARGV[1] {
    separator = index($0, "=")
    if (!separator) die("invalid value map")
    values[substr($0, 1, separator-1)] = substr($0, separator+1)
    next
}
{
    remaining = $0
    rendered = ""
    while (match(remaining, /__THEME_[A-Z0-9_]+__/)) {
        key = substr(remaining, RSTART+8, RLENGTH-10)
        source_key = key
        target_path = substr(key, 1, 12) == "TARGET_PATH_"
        if (target_path) source_key = substr(key, 13)
        if (!(source_key in values)) {
            die("unknown token " key)
        }
        value = values[source_key]
        if (target_path) {
            if (value !~ /^hooks\/target\/usr\/share\/backgrounds\//) die("invalid wallpaper target token " key)
            sub(/^hooks\/target/, "", value)
        }
        rendered = rendered substr(remaining, 1, RSTART-1) value
        remaining = substr(remaining, RSTART+RLENGTH)
    }
    if (index(remaining, "__THEME_")) {
        die("malformed/unresolved token")
    }
    print rendered remaining
}
END { if (failed) exit 1 }
