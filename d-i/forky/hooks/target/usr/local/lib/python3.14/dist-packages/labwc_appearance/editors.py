"""Surgical, comment-preserving writers for the installed native formats."""
from __future__ import annotations
import re
from collections import defaultdict
import tinycss2
from tinycss2.color3 import parse_color
from .catalog import Palette, rgb


def ini_values(text: str) -> dict[tuple[str, str], str]:
    result = {}
    section = ''
    for line in text.splitlines():
        head = re.fullmatch(r'\s*\[([^\[\]]+)\]\s*(?:[#;].*)?', line)
        if head:
            section = head[1]
            continue
        key = re.match(r'^\s*([^#;\s=]+)\s*=\s*(.*?)\s*$', line)
        if key:
            pair = (section, key[1])
            if pair in result:
                raise ValueError('duplicate native INI key: ' + '/'.join(pair))
            result[pair] = key[2]
    return result


def edit_ini(text: str, updates: dict[tuple[str, str], str | None]) -> str:
    ini_values(text)  # detect ambiguous keys before any mutation
    remaining = dict(updates)
    output = []
    section = ''
    def append_missing():
        for pair in list(remaining):
            if pair[0] == section:
                value = remaining.pop(pair)
                if value is not None:
                    output.append(pair[1] + '=' + value + '\n')
    for line in text.splitlines(keepends=True):
        head = re.fullmatch(r'\s*\[([^\[\]]+)\]\s*(?:[#;].*)?\n?', line)
        if head:
            append_missing()
            section = head[1]
        key = re.match(r'^(\s*)([^#;\s=]+)\s*=.*', line)
        pair = (section, key[2]) if key else None
        if pair in remaining:
            value = remaining.pop(pair)
            if value is not None:
                output.append(key[1] + key[2] + '=' + value + '\n')
        else:
            output.append(line if line.endswith('\n') else line + '\n')
    append_missing()
    for name in dict.fromkeys(pair[0] for pair in remaining):
        items = [(key, value) for (sect, key), value in remaining.items() if sect == name and value is not None]
        if items:
            output.append('\n[' + name + ']\n' if name else '\n')
            output.extend(key + '=' + value + '\n' for key, value in items)
    return ''.join(output)


def flat_values(text: str, separator: str) -> dict[str, str]:
    expression = r'^\s*([^#\s:]+)' + (r'\s*:\s*' if separator == ':' else r'\s+') + r'(.*?)\s*$'
    result = {}
    for line in text.splitlines():
        match = re.match(expression, line)
        if match:
            if match[1] in result:
                raise ValueError('duplicate native key: ' + match[1])
            result[match[1]] = match[2]
    return result


def edit_flat(text: str, updates: dict[str, str | None], separator: str = ' ') -> str:
    flat_values(text, separator)
    expression = r'^(\s*)([^#\s:]+)' + (r'\s*:\s*' if separator == ':' else r'\s+')
    pending = dict(updates)
    output = []
    for line in text.splitlines(keepends=True):
        match = re.match(expression, line)
        if match and match[2] in pending:
            value = pending.pop(match[2])
            if value is not None:
                output.append(match[1] + match[2] + (': ' if separator == ':' else ' ') + value + '\n')
        else:
            output.append(line if line.endswith('\n') else line + '\n')
    output.extend(key + (': ' if separator == ':' else ' ') + value + '\n'
                  for key, value in pending.items() if value is not None)
    return ''.join(output)


def _color_tokens(tokens):
    for token in tokens:
        try:
            color = parse_color(token)
        except (AttributeError, TypeError, ValueError):
            color = None
        if color is not None and color != 'currentColor':
            yield token, color
        elif token.type == 'function' and token.lower_name not in ('url', '-gtk-recolor'):
            yield from _color_tokens(token.arguments)


def _css_rules(text):
    rules = tinycss2.parse_stylesheet(text, skip_comments=False, skip_whitespace=False)
    if any(rule.type == 'error' for rule in rules):
        raise ValueError('invalid native CSS')
    for rule in rules:
        if rule.type == 'at-rule':
            # Installed templates do not contain imports or nested rules. Refuse
            # unsupported imported styles rather than edit arbitrary files.
            raise ValueError('appearance requires a self-contained stylesheet without at-rules')
    return rules


def _declarations(rule):
    parsed = tinycss2.parse_declaration_list(rule.content, skip_comments=False, skip_whitespace=False)
    if any(part.type == 'error' for part in parsed):
        raise ValueError('invalid CSS declaration')
    return parsed


def _selector(rule) -> str:
    return ' '.join(tinycss2.serialize(rule.prelude).split())


def _role(selector: str, prop: str, p: Palette, *, background: bool = False) -> str:
    selector = re.sub(r':not\([^)]*\)', '', selector)
    selected = any(word in selector for word in ('.active', ':active', ':checked', 'selection', ':selected'))
    alert = any(word in selector for word in ('.critical', '.urgent', '.error', '.shutdown'))
    warning = '.warning' in selector
    disabled = ':disabled' in selector or '.hidden' in selector
    highlight = p.ansi[1] if alert else p.ansi[3] if warning else p.accent
    if 'shadow' in prop:
        # Hover, focus and selected controls use the accent as their glow;
        # ordinary drop shadows stay tied to the palette border so they remain
        # visible on both dark and light surfaces without becoming black halos.
        return p.accent if selected or ':hover' in selector or ':focus' in selector else p.border
    if 'border' in prop or 'outline' in prop:
        return highlight if selected or alert or ':focus' in selector else p.border
    if prop in ('color', 'fill', 'stroke', 'caret-color'):
        if disabled:
            return p.muted
        if selected or alert or warning:
            if not background:
                return highlight
            from .catalog import contrast
            return '#111111' if contrast(highlight, '#111111') >= contrast(highlight, '#ffffff') else '#ffffff'
        return p.foreground
    if selected or alert or warning:
        return highlight
    if 'window' in selector or selector == '*':
        return p.background
    return p.surface


def css(text: str, baseline: str, p: Palette | None) -> str:
    """Rewrite literal colors only; preserve font sizes, borders and geometry.

    Reset uses the installed stylesheet's selector/property color inventory,
    never a first-run snapshot of user modifications. Files are parsed before
    the caller commits a multi-file transaction.
    """
    references = defaultdict(list)
    for rule in _css_rules(baseline):
        if rule.type != 'qualified-rule':
            continue
        for decl in _declarations(rule):
            if decl.type == 'declaration':
                colors = [tinycss2.serialize([token]) for token, _ in _color_tokens(decl.value)]
                if colors:
                    references[(_selector(rule), decl.lower_name)].append(colors)
    seen = defaultdict(int)
    rules = _css_rules(text)
    for rule in rules:
        if rule.type != 'qualified-rule':
            continue
        declarations = _declarations(rule)
        background = any(d.type == 'declaration' and d.lower_name in ('background', 'background-color', 'background-image')
                         and any(color.alpha > 0 for _, color in _color_tokens(d.value)) for d in declarations)
        for decl in declarations:
            if decl.type != 'declaration':
                continue
            tokens = list(_color_tokens(decl.value))
            key = (_selector(rule), decl.lower_name)
            choices = references.get(key, [])
            reference = choices[min(seen[key], len(choices)-1)] if choices else None
            if tokens:
                seen[key] += 1
            # Do not interpret numbers/font strings/URLs as color properties.
            if not (decl.lower_name in ('color', 'background', 'background-color', 'background-image',
                                        'border', 'border-color', 'outline', 'outline-color',
                                        'box-shadow', 'text-shadow', 'caret-color', 'fill', 'stroke') or
                    decl.lower_name.startswith('border-')):
                continue
            replacements = {}
            for index, (token, color) in enumerate(tokens):
                if p is None:
                    if not reference:
                        continue
                    replacements[id(token)] = tinycss2.parse_component_value_list(reference[min(index, len(reference)-1)])
                else:
                    if color.alpha == 0:
                        continue  # preserve intentionally transparent surfaces
                    value = _role(_selector(rule), decl.lower_name, p, background=background)
                    if color.alpha < 1:
                        r, g, b = rgb(value)
                        value = f'rgba({r}, {g}, {b}, {color.alpha:.6g})'
                    replacements[id(token)] = tinycss2.parse_component_value_list(value)
            def replace(items):
                result = []
                for token in items:
                    if id(token) in replacements:
                        result.extend(replacements[id(token)])
                    else:
                        if token.type == 'function' and token.lower_name not in ('url', '-gtk-recolor'):
                            token.arguments = replace(token.arguments)
                        result.append(token)
                return result
            decl.value = replace(decl.value)
        rule.content = tinycss2.parse_component_value_list(tinycss2.serialize(declarations))
    return tinycss2.serialize(rules)
