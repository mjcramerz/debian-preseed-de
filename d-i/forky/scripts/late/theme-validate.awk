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
function hex_color(value, lengths,    digits,i,allowed) {
    if (value !~ /^#[0-9A-Fa-f]+$/) return 0
    digits = length(value) - 1
    for (i = 1; i <= split(lengths, allowed, ","); i++)
        if (digits == allowed[i] + 0) return 1
    return 0
}
function named_color(value) {
    return value == "transparent" || value == "currentColor" ||
           value ~ /^[A-Za-z][A-Za-z0-9_-]*$/
}
function pango_name(value) {
    return value ~ /^[A-Za-z][A-Za-z0-9_-]*$/ && value != "transparent" && value != "currentColor"
}
function qt_name(value) {
    return value == "transparent" || (value ~ /^[A-Za-z][A-Za-z0-9_-]*$/ && value != "currentColor")
}
function css_color(value, alpha_hex,    digits) {
    if (named_color(value)) return 1
    if (value ~ /^#[0-9A-Fa-f]+$/) {
        digits = length(value) - 1
        if (alpha_hex && (digits == 3 || digits == 4 || digits == 6 || digits == 8 || digits == 9 || digits == 12 || digits == 16)) return 1
        if (!alpha_hex && (digits == 3 || digits == 6 || digits == 9 || digits == 12)) return 1
    }
    if (value ~ /^rgba?\([0-9.,%+ -]+\)$/ || value ~ /^hsla?\([0-9.,%+ -]+\)$/) return 1
    if (value ~ /^@[A-Za-z][A-Za-z0-9_-]*$/) return 1
    # CSS consumers may add color functions over time (for example var(),
    # color(), lab() or color-mix()). Keep the lexical boundary safe without
    # rejecting a function that the installed CSS engine accepts.
    return value ~ /^[A-Za-z][A-Za-z0-9_-]*\([A-Za-z0-9#@(),.%+\/ -]+\)$/
}
function qt_color(value) {
    return qt_name(value) || hex_color(value, "3,6,8,9,12")
}
function kitty_color(value) {
    if (qt_name(value)) return 1
    if (value ~ /^#[0-9A-Fa-f]+(@(0|1|0[.][0-9]+|1[.]0+))?$/)
        return hex_color(substr(value, 1, index(value, "@") ? index(value, "@") - 1 : length(value)), "3,6,9,12")
    return value ~ /^(rgb:[0-9A-Fa-f]+\/[0-9A-Fa-f]+\/[0-9A-Fa-f]+|rgbi:[0-9]+([.][0-9]+)?\/[0-9]+([.][0-9]+)?\/[0-9]+([.][0-9]+)?)(@(0|1|0[.][0-9]+|1[.]0+))?$/
}
function fzf_color(value) {
    # fzf accepts named/numbered ANSI colors, 24-bit #rrggbb colors, and
    # optional foreground attributes after a colon.
    return value ~ /^(-1|[0-9]+|[A-Za-z][A-Za-z0-9_-]*|#[0-9A-Fa-f]{6})(:[A-Za-z][A-Za-z0-9_-]*)*$/ \
           && (value !~ /^[0-9]+$/ || value + 0 <= 255)
}
function vscode_color(value) {
    # VS Code theme colors are CSS hex RGB/RGBA values; "default" is also
    # accepted for the color customizations that explicitly support it.
    return value == "default" || value ~ /^#[0-9A-Fa-f]{3,4}$/ ||
           value ~ /^#[0-9A-Fa-f]{6}([0-9A-Fa-f]{2})?$/
}
function zathura_color(value) {
    return named_color(value) || hex_color(value, "3,6,9,12") ||
           value ~ /^rgba?\([0-9.,%+ -]+\)$/
}
function xournalpp_color(value) {
    return hex_color(value, "6,8")
}
function zsh_color(value) {
    if (value ~ /^[0-9]+$/) return value + 0 <= 255
    return value ~ /^[A-Za-z][A-Za-z0-9_-]*$/ || value ~ /^#[0-9A-Fa-f]{6}$/
}
function valid(value, type,    copy,hexlen,n,i,parts) {
    if (type == "gtk3-color" || type == "gtk3-css-color") return css_color(value, 0)
    if (type == "gtk4-color" || type == "gtk4-css-color" || type == "css-color") return css_color(value, 1)
    if (type == "gtk3-pango-color" || type == "pango-color") return pango_name(value) || hex_color(value, "3,6,9,12")
    if (type == "qt-color") return qt_color(value)
    if (type == "kitty-color") return kitty_color(value)
    if (type == "fzf-color") return fzf_color(value)
    if (type == "vscode-color") return vscode_color(value)
    if (type == "mako-color") return value ~ /^#[0-9A-Fa-f]{6}([0-9A-Fa-f]{2})?$/
    if (type == "mako-progress") return value ~ /^over #[0-9A-Fa-f]{6}([0-9A-Fa-f]{2})?$/
    if (type == "fuzzel-rgba") return value ~ /^[0-9A-Fa-f]{8}$/
    if (type == "foot-rgb" || type == "swaylock-rgb") return value ~ /^[0-9A-Fa-f]{6}$/
    if (type == "swaylock-rgba") return value ~ /^[0-9A-Fa-f]{8}$/
    if (type == "xournalpp-hex") return value ~ /^[0-9A-Fa-f]{8}$/
    if (type == "xournalpp-color") return xournalpp_color(value)
    if (type == "zsh-color") return zsh_color(value)
    if (type == "zathura-color") return zathura_color(value)
    if (type == "labwc-color") return named_color(value) || hex_color(value, "3,6,8,9,12")
    if (type == "labwc-color-list") {
        n = split(value, parts, ",")
        if (n != 3) return 0
        for (i = 1; i <= n; i++) if (!valid(parts[i], "labwc-color")) return 0
        return 1
    }
    if (type == "wayscriber-color") return named_color(value) || hex_color(value, "3,6,9,12") || value ~ /^rgb\([0-9.,%+ -]+\)$/
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
    if (type == "alpha" || type == "decimal") return value ~ /^[0-9]+([.][0-9]+)?$/ && value + 0 >= 0 && value + 0 <= 1
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
