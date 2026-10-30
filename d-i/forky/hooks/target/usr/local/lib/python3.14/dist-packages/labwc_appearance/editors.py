"""Surgical, comment-preserving writers for the installed native formats."""
from __future__ import annotations
import re
from collections import defaultdict
from functools import lru_cache
import tinycss2
from tinycss2.color3 import parse_color
from .catalog import Palette, readable_text, rgb

GLOW_START = '/* labwc-appearance: hover glow begin */'
GLOW_END = '/* labwc-appearance: hover glow end */'
MAX_STYLESHEET_BYTES = 2 * 1024 * 1024
MAX_STATE_SELECTORS = 1024


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


def _replace_tokens(tokens, replacements):
    result = []
    for token in tokens:
        if id(token) in replacements:
            result.extend(replacements[id(token)])
        else:
            if token.type == 'function' and token.lower_name not in ('url', '-gtk-recolor'):
                token.arguments = _replace_tokens(token.arguments, replacements)
            result.append(token)
    return result


def _css_rules(text):
    rules = tinycss2.parse_stylesheet(text, skip_comments=False, skip_whitespace=False)
    if any(rule.type == 'error' for rule in rules):
        raise ValueError('invalid native CSS')
    for rule in rules:
        if rule.type == 'at-rule':
            raise ValueError('appearance component stylesheets must be self-contained')
    return rules


def _declarations(rule):
    parsed = tinycss2.parse_declaration_list(rule.content, skip_comments=False, skip_whitespace=False)
    if any(part.type == 'error' for part in parsed):
        raise ValueError('invalid CSS declaration')
    return parsed


def _selector(rule) -> str:
    return ' '.join(tinycss2.serialize(rule.prelude).split())


@lru_cache(maxsize=512)
def _selector_groups(selector: str) -> tuple[str, ...]:
    """Separate selector lists without splitting functions or quoted values."""
    groups, pending = [], []
    for token in tinycss2.parse_component_value_list(selector):
        if token.type == 'literal' and token.value == ',':
            groups.append(tinycss2.serialize(pending).strip())
            pending = []
        else:
            pending.append(token)
    groups.append(tinycss2.serialize(pending).strip())
    return tuple(groups)


@lru_cache(maxsize=512)
def _selector_info(selector: str) -> tuple[frozenset[str], frozenset[str], str]:
    """Read positive states without treating strings or :not() as states.

    A state on an ancestor affects inherited text. Only a state on the final
    widget may add its own fill or glow; menu labels must not become buttons.
    """
    compounds, pending = [], []
    for token in tinycss2.parse_component_value_list(selector):
        if token.type == 'comment':
            continue
        if token.type == 'whitespace' or (token.type == 'literal' and token.value in ('>', '+', '~')):
            if pending:
                compounds.append(pending)
                pending = []
        else:
            pending.append(token)
    if pending:
        compounds.append(pending)

    def states(tokens):
        result = set()
        for index, token in enumerate(tokens):
            if token.type != 'ident':
                continue
            previous = tokens[index - 1] if index else None
            if previous is not None and previous.type == 'literal' and previous.value in ('.', ':'):
                result.add(token.value.lower())
                if previous.value == ':' and token.value.lower() == 'active':
                    result.add('pressed')
            elif token.value.lower() == 'selection':
                result.add('selected')
        return result

    final = compounds[-1] if compounds else []
    target = final[0].value.lower() if final and final[0].type == 'ident' else (
        '*' if final and final[0].type == 'literal' and final[0].value == '*' else '')
    return (frozenset().union(*(states(tokens) for tokens in compounds)),
            frozenset(states(final)), target)


def _role(selector: str, prop: str, p: Palette, *, background: bool = False,
          tone: int = 0) -> str:
    # A declaration shared by normal and hovered selectors supplies their
    # common base. The owned per-selector state rules below add hover/focus
    # colors without accidentally giving the normal selector a hover fill.
    groups = [_selector_info(group) for group in _selector_groups(selector)]
    def every(*words):
        return all(states.intersection(words) for states, _, _ in groups)
    selected = every('active', 'checked', 'selected', 'suggested-action')
    hovered = every('hover')
    focused = every('focus', 'focus-visible', 'focus-within')
    # CSS classes such as .active identify persistent selection. Only the
    # :active pseudo-class identifies a control currently being pressed.
    pressed = every('pressed')
    alert = every('critical', 'urgent', 'error', 'shutdown', 'recording')
    warning = every('warning', 'reboot', 'disconnected')
    success = every('success', 'connected', 'charging')
    disabled = every('disabled', 'hidden', 'off', 'unavailable', 'no-controller', 'muted')
    highlight = p.error if alert else p.warning if warning else p.success if success else (
        p.accent_pressed if pressed else p.accent_hover if selected and hovered else p.accent)
    if 'shadow' in prop:
        return highlight if (alert or warning or success) and (selected or hovered or focused) else (
            p.glow if selected or hovered or focused else p.shadow)
    if 'border' in prop or 'outline' in prop:
        if disabled:
            return p.surface_alt
        return highlight if selected or alert or warning or success else (
            p.glow if focused else p.accent_hover if hovered else p.border)
    if prop in ('color', 'fill', 'stroke', 'caret-color'):
        if disabled:
            return p.disabled
        if selected:
            return readable_text(highlight)
        if alert or warning or success:
            return readable_text(highlight) if background else highlight
        if every('minimized'):
            return p.muted
        return p.foreground
    if disabled:
        return p.surface
    if selected or alert or warning or success:
        if alert or warning or success:
            return highlight
        shades = ((p.accent_pressed, p.accent, p.accent_hover) if pressed else
                  (p.accent_hover, p.glow, p.accent) if hovered else
                  (p.accent, p.accent_hover, p.glow))
        return shades[min(tone, 2)]
    if focused or hovered:
        return (p.hover, p.pressed, p.surface_alt)[min(tone, 2)]
    # Decide from the target widget, not an ancestor such as window#waybar:
    # controls below the window need their own raised surface colors.
    targets = [target for _, _, target in groups]
    if all(target in ('*', 'window', 'entry', 'textview') for target in targets):
        return (p.background, p.surface, p.surface_alt)[min(tone, 2)]
    if all(target in ('menu', 'tooltip') for target in targets):
        return (p.surface_alt, p.surface, p.background)[min(tone, 2)]
    return (p.surface, p.surface_alt, p.hover)[min(tone, 2)]


def _without_glow(text: str) -> str:
    starts, ends = text.count(GLOW_START), text.count(GLOW_END)
    if not starts and not ends:
        return text
    if starts != 1 or ends != 1:
        raise ValueError('ambiguous appearance hover-glow block')
    start, end = text.index(GLOW_START), text.index(GLOW_END)
    if end <= start:
        raise ValueError('invalid appearance hover-glow block')
    end += len(GLOW_END)
    if text[end:end+1] == '\n':
        end += 1
    return text[:start] + text[end:]


def _glow_rules(rules, p: Palette) -> str:
    """Complete interactive state colors using existing widget selectors."""
    result = []
    selected_hover = []
    seen = set()
    gradients = {}
    for rule in rules:
        if rule.type != 'qualified-rule':
            continue
        gradient = None
        for decl in _declarations(rule):
            if decl.type != 'declaration' or decl.lower_name not in ('background', 'background-image'):
                continue
            value = [token for token in decl.value if token.type not in ('whitespace', 'comment')]
            if (len(value) == 1 and value[0].type == 'function' and
                    value[0].lower_name in ('linear-gradient', 'radial-gradient')):
                gradient = tinycss2.serialize(value)
        for selector in _selector_groups(tinycss2.serialize(rule.prelude)):
            _, state, _ = _selector_info(selector)
            if (not state.intersection(('hover', 'focus', 'focus-visible', 'focus-within', 'active',
                                        'checked', 'selected', 'suggested-action')) or
                    'disabled' in state):
                continue
            if selector not in seen:
                if len(seen) >= MAX_STATE_SELECTORS:
                    raise ValueError('appearance stylesheet has too many interactive selectors')
                seen.add(selector)
                result.append(selector)
                if (state.intersection(('active', 'checked', 'selected', 'suggested-action')) and
                        not state.intersection(('hover', 'pressed'))):
                    selected_hover.extend(((selector + ':hover', selector), (selector + ':active', selector)))
            if gradient is not None:
                gradients[selector] = gradient
    for selector, original in selected_hover:
        if selector not in seen:
            if len(seen) >= MAX_STATE_SELECTORS:
                raise ValueError('appearance stylesheet has too many interactive selectors')
            seen.add(selector)
            result.append(selector)
            if original in gradients:
                gradients[selector] = gradients[original]
    if not result:
        return ''
    lines = [GLOW_START]
    size = len(GLOW_START) + len(GLOW_END) + 2
    for selector in result:
        color = _role(selector, 'box-shadow', p)
        r, g, b = rgb(color)
        outline = _role(selector, 'border-color', p)
        background = _role(selector, 'background-color', p)
        foreground = _role(selector, 'color', p, background=True)
        image = ''
        if selector in gradients:
            tokens = tinycss2.parse_component_value_list(gradients[selector])
            replacements = {}
            for index, (token, color) in enumerate(_color_tokens(tokens)):
                if color.alpha == 0:
                    continue
                value = _role(selector, 'background-image', p, tone=index)
                if color.alpha < 1:
                    red, green, blue = rgb(value)
                    value = f'rgba({red}, {green}, {blue}, {color.alpha:.6g})'
                replacements[id(token)] = tinycss2.parse_component_value_list(value)
            image = '; background-image: ' + tinycss2.serialize(_replace_tokens(tokens, replacements))
        line = (selector + ':not(:disabled) { background-color: ' + background + '; color: ' + foreground +
                image + '; border-color: ' + outline + '; box-shadow: 0 0 0 1px ' + outline +
                f', inset 0 0 8px 1px rgba({r}, {g}, {b}, 0.38);' + ' }')
        size += len(line.encode('utf-8')) + 1
        if size > MAX_STYLESHEET_BYTES:
            raise ValueError('appearance state stylesheet exceeds the size limit')
        lines.append(line)
    lines.append(GLOW_END)
    return '\n'.join(lines) + '\n'


def css(text: str, baseline: str, p: Palette | None, *, glow: bool = False) -> str:
    """Rewrite literal colors only; preserve font sizes, borders and geometry.

    Reset uses the installed stylesheet's selector/property color inventory,
    never a first-run snapshot of user modifications. Files are parsed before
    the caller commits a multi-file transaction.
    """
    if any(len(value.encode('utf-8')) > MAX_STYLESHEET_BYTES for value in (text, baseline)):
        raise ValueError('appearance stylesheet exceeds the size limit')
    # Own only this marked block. Removing it restores pre-existing `none`
    # shadows and user geometry without trying to infer their previous values.
    text, baseline = _without_glow(text), _without_glow(baseline)
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
                    value = _role(_selector(rule), decl.lower_name, p,
                                  background=background, tone=index)
                    if color.alpha < 1:
                        r, g, b = rgb(value)
                        value = f'rgba({r}, {g}, {b}, {color.alpha:.6g})'
                    replacements[id(token)] = tinycss2.parse_component_value_list(value)
            decl.value = _replace_tokens(decl.value, replacements)
        rule.content = tinycss2.parse_component_value_list(tinycss2.serialize(declarations))
    rendered = tinycss2.serialize(rules)
    if glow and p is not None:
        extra = _glow_rules(rules, p)
        if extra:
            if len(rendered.encode('utf-8')) + len(extra.encode('utf-8')) + 1 > MAX_STYLESHEET_BYTES:
                raise ValueError('complete appearance stylesheet exceeds the size limit')
            rendered = rendered.rstrip('\n') + '\n' + extra
    return rendered
