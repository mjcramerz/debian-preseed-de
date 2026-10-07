# POSIX awk: validate a fixed schema and three literal, non-executable .env files.
# Usage: awk -f theme-validate.awk theme-schema.tsv base.env apps.env office.env
# Output is a literal NAME=value map, consumed only after successful validation.
function die(message) {
    print "theme validation: " FILENAME ":" FNR ": " message > "/dev/stderr"
    failed = 1
    exit 1
}
function channels(value, count, maximum,    numbers,n,i) {
    gsub(/[][]| /, "", value)
    n = split(value, numbers, ",")
    if (n != count) return 0
    for (i = 1; i <= n; i++) {
        if (numbers[i] !~ /^[0-9]+([.][0-9]+)?$/) return 0
        if (numbers[i] + 0 < 0 || numbers[i] + 0 > (i == 4 ? 1 : maximum)) return 0
    }
    return 1
}
function valid(value, type,    copy,hexlen,n,i,parts) {
    if (type == "icon-color") return value == "inherit" || valid(value, "hash6")
    if (type == "hue") return value ~ /^[0-9]+([.][0-9]+)?$/ && value + 0 <= 360
    if (type == "percent") return value ~ /^[0-9]+([.][0-9]+)?%$/ && value + 0 <= 100
    if (type == "hsl") {
        n = split(value, parts, ",")
        if (n != 3) return 0
        for (i = 1; i <= n; i++) gsub(/^[ ]+|[ ]+$/, "", parts[i])
        return valid(parts[1], "hue") && valid(parts[2], "percent") && valid(parts[3], "percent")
    }
    if (type == "hash6-list") {
        n = split(value, parts, ",")
        if (n != 3) return 0
        for (i = 1; i <= n; i++) if (!valid(parts[i], "hash6")) return 0
        return 1
    }
    if (type ~ /^hex[68]$/) {
        hexlen = substr(type, 4) + 0
        return length(value) == hexlen && value ~ /^[0-9a-fA-F]+$/
    }
    if (type ~ /^hash[3468]$/) {
        hexlen = substr(type, 5) + 0
        return length(value) == hexlen + 1 && value ~ /^#[0-9a-fA-F]+$/
    }
    if (type == "rgb" || type == "rgba") {
        if (value !~ /^rgba?\([0-9., ]+\)$/) return 0
        copy = value
        sub(/^rgba?\(/, "", copy); sub(/\)$/, "", copy)
        return substr(value, 1, length(type)+1) == type "(" && channels(copy, type == "rgb" ? 3 : 4, 255)
    }
    if (type == "array3" || type == "array4") {
        return value ~ /^\[[0-9., ]+\]$/ && channels(value, substr(type, 6)+0, 1)
    }
    if (type == "rgb-table") {
        if (value !~ /^\{ rgb = \[[0-9., ]+\] \}$/) return 0
        copy = value; sub(/^\{ rgb = /, "", copy); sub(/ \}$/, "", copy)
        return channels(copy, 3, 1)
    }
    if (type == "alpha") return value ~ /^[0-9]+([.][0-9]+)?$/ && value + 0 >= 0 && value + 0 <= 1
    if (type == "uint") return value ~ /^[0-9]+$/ && value + 0 <= 4294967295
    if (type == "bool") return value == "true" || value == "false"
    if (type == "bool-title") return value == "True" || value == "False"
    if (type == "yes-no") return value == "yes" || value == "no"
    if (type == "symbol") return value == ">" || value == "<"
    if (type == "glyph") {
        # Unicode glyphs (possibly a variation selector/joiner), never syntax.
        return value != "" && value !~ /[!-~]/
    }
    if (type == "source-image" || type == "source-archive") {
        if (value !~ /^hooks\/target\/usr\/share\/backgrounds\/[A-Za-z0-9_.\/+-]+$/ || value ~ /(^|\/)\.\.?($|\/)|\/\//) return 0
        if (type == "source-archive") return value ~ /[.]tar[.]gz$/
        return value ~ /[.](png|jpg|jpeg|webp)$/
    }
    if (type == "icon-path" || type == "absolute-icon-path") {
        if (value ~ /(^|\/)\.\.?($|\/)|\/\//) return 0
        if (type == "absolute-icon-path" && value !~ /^\/usr\/share\//) return 0
        return value ~ /^(\/usr\/share\/|icons\/)[A-Za-z0-9_.\/+-]+[.](svg|png|jpg|jpeg|webp)$/
    }
    if (type == "font-weight") return value ~ /^[1-9]00$/
    if (type == "border-style") return value ~ /^(none|solid|dashed|dotted|double|groove|ridge|inset|outset)$/
    if (type == "font") return value ~ /^[A-Za-z0-9][A-Za-z0-9 .,_-]*$/
    if (type == "icon") return value ~ /^[A-Za-z0-9][A-Za-z0-9._+-]*$/
    if (type == "text") {
        # No shell, JSON, XML, CSS or language delimiters. Values are inserted
        # literally into pre-existing contexts, not evaluated as programs.
        return value ~ /^[A-Za-z0-9_ .,:\/+@#()%-]*$/
    }
    return 0
}
FILENAME == ARGV[1] {
    if ($0 ~ /^#/ || $0 == "") next
    if (NF != 3 || $1 !~ /^(base|apps|office)$/ || $2 !~ /^[A-Z][A-Z0-9_]*$/ || $2 in groups) die("invalid/duplicate schema row")
    groups[$2] = $1; types[$2] = $3
    order[++total] = $2
    next
}
{
    if ($0 ~ /^[ ]*(#|$)/) next
    if ($0 !~ /^[A-Z][A-Z0-9_]*=".*"$/) die("expected NAME=\"literal\"; no shell expressions or inline comments")
    delimiter = index($0, "=")
    name = substr($0, 1, delimiter-1)
    value = substr($0, delimiter+2, length($0)-delimiter-2)
    group = FILENAME; sub(/^.*\//, "", group); sub(/[.]env$/, "", group)
    if (!(name in groups)) die("unknown variable " name)
    if (groups[name] != group) die("variable " name " belongs in " groups[name] ".env")
    if (name in values) die("duplicate variable " name)
    if (length(value) > 4096 || value ~ /[\001-\037\177"'\\$`]/ || value ~ /__/) die("unsafe literal in " name)
    if (!valid(value, types[name])) die("invalid " types[name] " value for " name)
    values[name] = value
}
END {
    if (failed) exit 1
    for (i = 1; i <= total; i++) {
        name = order[i]
        if (!(name in values)) die("missing variable " name)
    }
    if (!total) die("empty theme schema")
    for (i = 1; i <= total; i++) print order[i] "=" values[order[i]]
}
