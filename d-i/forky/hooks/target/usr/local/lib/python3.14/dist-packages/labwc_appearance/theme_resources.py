"""Materialize precompiled GTK resource data without global registration.

GTK4 user CSS imports must not depend on a theme provider having registered a
vendor's /org/gnome/theme namespace. Copy the existing resource bytes and make
their CSS URLs relative, using the packaged Gio reader at installation only.
"""
from __future__ import annotations
import json
import posixpath
import time
from urllib.parse import unquote, urlsplit
import tinycss2
from .theme_archive import MAX_ARCHIVE, MAX_MEMBER, MAX_MEMBERS, name

MAX_CSS = 2 * 1024**2


def _check(deadline: float) -> None:
    if time.monotonic() >= deadline:
        raise TimeoutError('theme resource preparation exceeded its deadline')


def bundle_files(blob: bytes, *, deadline: float) -> dict[str, bytes]:
    # This installed package dependency is intentionally imported only by the
    # target installation path, never by the ordinary appearance menu.
    import gi
    gi.require_version('Gio', '2.0')
    from gi.repository import Gio, GLib
    if len(blob) > MAX_MEMBER:
        raise ValueError('theme resource input exceeds the size limit')
    resource = Gio.Resource.new_from_data(GLib.Bytes.new(blob))
    result = {}
    pending = ['/']
    seen = set()
    count = size = 0
    while pending:
        _check(deadline)
        directory = pending.pop()
        if directory in seen:
            raise ValueError('cyclic theme resource directory')
        seen.add(directory)
        children = resource.enumerate_children(directory, Gio.ResourceLookupFlags.NONE)
        count += len(children)
        if count > MAX_MEMBERS:
            raise ValueError('theme resource member budget exceeded')
        for child in children:
            _check(deadline)
            if not child or '/' in child.rstrip('/') or len(child) > 255:
                raise ValueError('invalid theme resource child')
            path = directory + child
            relative = name(path[1:])
            if child.endswith('/'):
                pending.append('/' + relative + '/')
                continue
            info = resource.get_info(path, Gio.ResourceLookupFlags.NONE)
            # PyGObject releases expose the successful gboolean either as a
            # leading result or through exception semantics; size/flags are
            # the two final out parameters in both supported representations.
            if len(info) not in (2, 3) or (len(info) == 3 and info[0] is not True):
                raise ValueError('invalid theme resource size metadata')
            length = info[-2]
            if type(length) is not int or length < 0 or length > MAX_MEMBER:
                raise ValueError('theme resource member exceeds the size limit')
            size += length
            if size > MAX_ARCHIVE:
                raise ValueError('theme resource expansion exceeds the aggregate size limit')
            value = resource.lookup_data(path, Gio.ResourceLookupFlags.NONE).get_data()
            if not isinstance(value, bytes) or len(value) != length or relative in result:
                raise ValueError('invalid theme resource data')
            result[relative] = value
    return result


def rewrite_css(blob: bytes, path: str, resources: dict[str, str],
                files: set[str], *, deadline: float) -> bytes:
    if len(blob) > MAX_CSS:
        raise ValueError('vendor theme CSS exceeds the size limit')
    rules = tinycss2.parse_stylesheet(blob.decode('utf-8'), skip_comments=False, skip_whitespace=False)
    if any(rule.type == 'error' for rule in rules):
        raise ValueError('invalid vendor theme CSS')

    def url(value: str) -> str:
        _check(deadline)
        parsed = urlsplit(value)
        if parsed.scheme == 'data' and value.lower().startswith('data:image/'):
            return value
        if parsed.scheme == 'resource':
            if parsed.netloc or parsed.query:
                raise ValueError('invalid vendor theme resource URI')
            source = '/' + name(unquote(parsed.path).lstrip('/'))
            if source not in resources:
                if source.startswith('/org/gtk/libgtk/'):
                    return value  # Resources supplied by GTK itself.
                raise ValueError('vendor theme refers to a missing resource')
            target = resources[source]
        else:
            if parsed.scheme or parsed.netloc or parsed.query or parsed.path.startswith('/'):
                raise ValueError('external vendor theme asset URLs are prohibited')
            if not parsed.path:
                return value  # A local SVG fragment needs no other file.
            target = name(posixpath.normpath(posixpath.join(posixpath.dirname(path), unquote(parsed.path))))
            if target not in files:
                raise ValueError('vendor theme refers to a missing local asset')
        relative = posixpath.relpath(target, posixpath.dirname(path))
        return relative + ('#' + parsed.fragment if parsed.fragment else '')

    def walk(tokens, depth=0):
        if depth > 64:
            raise ValueError('vendor theme CSS nesting exceeds the limit')
        result = []
        for token in tokens:
            if token.type == 'error':
                raise ValueError('invalid vendor theme CSS token')
            value = None
            if token.type == 'url':
                value = token.value
            elif token.type == 'function' and token.lower_name == 'url':
                arguments = [item for item in token.arguments if item.type not in ('whitespace', 'comment')]
                if len(arguments) != 1 or arguments[0].type != 'string':
                    raise ValueError('invalid vendor theme CSS URL')
                value = arguments[0].value
            if value is not None:
                result.extend(tinycss2.parse_component_value_list('url(' + json.dumps(url(value)) + ')'))
            else:
                if token.type == 'function':
                    token.arguments = walk(token.arguments, depth + 1)
                elif hasattr(token, 'content') and token.content is not None:
                    token.content = walk(token.content, depth + 1)
                result.append(token)
        return result

    for rule in rules:
        _check(deadline)
        if hasattr(rule, 'prelude'):
            if rule.type == 'at-rule' and rule.lower_at_keyword == 'import':
                for index, token in enumerate(rule.prelude):
                    if token.type in ('whitespace', 'comment'):
                        continue
                    if token.type == 'string':
                        rule.prelude[index:index + 1] = tinycss2.parse_component_value_list(json.dumps(url(token.value)))
                    break
            rule.prelude = walk(rule.prelude)
        if hasattr(rule, 'content') and rule.content is not None:
            rule.content = walk(rule.content)
    result = tinycss2.serialize(rules).encode('utf-8')
    if len(result) > MAX_CSS:
        raise ValueError('rewritten vendor theme CSS exceeds the size limit')
    return result


def materialize(files: dict[str, bytes], *, deadline: float) -> dict[str, bytes]:
    result = dict(files)
    lookup: dict[str, dict[str, str]] = {}
    total = sum(len(value) for value in result.values())
    if len(result) > MAX_MEMBERS or total > MAX_ARCHIVE:
        raise ValueError('selected theme data exceeds the resource budget')
    for path, blob in files.items():
        if not path.endswith('.gresource'):
            continue
        directory = posixpath.dirname(path)
        if directory in lookup:
            raise ValueError('ambiguous theme resource namespace')
        resources = {}
        for relative, data in bundle_files(blob, deadline=deadline).items():
            target = directory + '/resources/' + relative
            total += len(data)
            if target in result or len(result) >= MAX_MEMBERS or total > MAX_ARCHIVE:
                raise ValueError('materialized theme resources exceed the member/byte budget')
            result[target] = data
            resources['/' + relative] = target
        lookup[directory] = resources
        del result[path]
    names = set(result)
    for path, blob in tuple(result.items()):
        if path.endswith('.css'):
            directory = path.split('/', 1)[0]
            result[path] = rewrite_css(blob, path, lookup.get(directory, {}), names, deadline=deadline)
    return result
