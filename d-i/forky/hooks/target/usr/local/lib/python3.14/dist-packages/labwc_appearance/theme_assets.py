"""Prepare the complete offline GTK3/GTK4 and Qt asset candidate as data.

No upstream installer, maintainer script, compiler or network client is used.
Publication is a separate installation step after this complete candidate has
passed its member, byte, path, source-hash and CSS-reference boundaries.
"""
from __future__ import annotations
from dataclasses import dataclass, field
import hashlib
import json
from pathlib import PurePosixPath
import re
import time
from managed_workflows.fs import Tree, parts
from .theme_archive import Archive, MAX_INPUT, MAX_MEMBER, name
from .theme_resources import materialize
from .themes import Theme, VARIANTS, validate_catalog

MAX_FILES = 24000
MAX_BYTES = 512 * 1024**2
EXTENSIONS = {'.css', '.svg', '.png', '.jpg', '.jpeg', '.gif', '.gresource', '.ttf', '.otf', '.woff', '.woff2'}

# Precompiled upstream stylesheets and their corresponding native asset trees.
# Paths are inside pinned archives; they are never executed as source code.
REPOS = {
    'canta': ('Canta-332fdecb1f7f.tar.gz', 'Canta-theme-332fdecb1f7f18324400b4c22f9d9e787e94e39f',
              '{version}/gtk-{shade}.css', (('assets', 'assets'), ('common-assets', 'common-assets'))),
    'chromeos': ('ChromeOS-b80a8b77f189.tar.gz', 'ChromeOS-theme-b80a8b77f189c790ff45cc9ece2a281106274bfe',
                 '{version}/gtk-{Shade}.css', (('assets', 'assets'),)),
    'fluent': ('Fluent-76f8112ff22d.tar.gz', 'Fluent-gtk-theme-76f8112ff22d81b372f7081c4fad13e9a08227de',
               '{version}/gtk-{Shade}.css', (('assets', 'assets'), ('scalable', 'assets/scalable'))),
    'layan': ('Layan-c712588a8395.tar.gz', 'Layan-gtk-theme-c712588a8395b8edc9f2ac5a3f6cf2359dec4d48',
              '{version}/gtk-{Shade}.css', (('assets', 'assets'),)),
    'matcha': ('Matcha-4f18ea92d53d.tar.gz', 'Matcha-gtk-theme-4f18ea92d53d16e139faf541c3f3071ad0c5da41',
               'gtk-{version}/gtk-{shade}-sea.css', (('assets-sea', 'assets'),)),
    'qogir': ('Qogir-619f33047877.tar.gz', 'Qogir-theme-619f33047877bf9afeef33370ea8a4a4338a5458',
              'theme-{version}/gtk-{Shade}.css', (('assets/assets', 'assets'), ('assets/assets-common', 'assets'))),
    'vimix': ('Vimix-c11aca86854d.tar.gz', 'Vimix-gtk-themes-c11aca86854dcf9e33892c59aef4f296d985bb60',
              '{version}/gtk-{shade}.css', (('assets/assets-doder', 'assets'),
                                         ('assets/window-assets', 'assets/window-assets'),
                                         ('assets/scalable', 'assets/scalable'))),
}


class Source:
    def __init__(self, tree: Tree, *, deadline: float):
        self.tree, self.deadline = tree, deadline
        self.manifest = json.loads(tree.read('sources.json', limit=512 * 1024))
        self.files = self.manifest.get('files') if isinstance(self.manifest, dict) else None
        if (not isinstance(self.manifest, dict) or self.manifest.get('schema') != 1 or not isinstance(self.files, dict) or
                not self.files or len(self.files) > 256):
            raise ValueError('invalid pinned desktop theme source inventory')
        for path, meta in self.files.items():
            parts(path)
            if (path.split('/', 1)[0] not in ('gtk', 'qt', 'licenses') or
                    not isinstance(meta, dict) or type(meta.get('bytes')) is not int or
                    not 0 < meta['bytes'] <= MAX_INPUT or
                    not isinstance(meta.get('sha256'), str) or
                    not re.fullmatch(r'[0-9a-f]{64}', meta['sha256'])):
                raise ValueError('invalid pinned desktop theme source descriptor')
        self.cached_name = None
        self.cached_archive = None

    def check(self) -> None:
        if time.monotonic() >= self.deadline:
            raise TimeoutError('desktop theme asset preparation exceeded its deadline')

    def read(self, path: str) -> bytes:
        self.check()
        if path not in self.files:
            raise ValueError('desktop theme asset has no pinned source hash')
        meta = self.files[path]
        blob = self.tree.read(path, limit=meta['bytes'])
        if len(blob) != meta['bytes'] or hashlib.sha256(blob).hexdigest() != meta['sha256']:
            raise ValueError('desktop theme source hash/length mismatch: ' + path)
        return blob

    def verify_all(self) -> None:
        for path in self.files:
            self.read(path)

    def archive(self, filename: str) -> Archive:
        path = 'gtk/' + filename
        if path != self.cached_name:
            archive = Archive(self.read(path), filename, deadline=self.deadline)
            self.cached_name, self.cached_archive = path, archive
        return self.cached_archive


def _copy(archive: Archive, source: str, destination: str, output: dict[str, bytes]) -> None:
    size = sum(len(value) for value in output.values())
    for relative, blob in archive.tree(source).items():
        if any(part.startswith('._') for part in PurePosixPath(relative).parts):
            continue
        if PurePosixPath(relative).suffix.lower() not in EXTENSIONS:
            continue
        path = name(destination + '/' + relative if destination else relative)
        if 'gtk-2.0' in PurePosixPath(path).parts:
            raise ValueError('GTK2 theme installation is prohibited')
        size += len(blob) - len(output.get(path, b''))
        if (len(output) + (path not in output)) > MAX_FILES or size > MAX_BYTES:
            raise ValueError('selected desktop theme exceeds the installation budget')
        output[path] = blob


def _styles(output: dict[str, bytes], version: str, blob: bytes) -> None:
    # Each menu variant is an explicit appearance. Applications requesting a
    # dark provider must not silently switch a selected light variant's assets.
    output['gtk-' + version + '/gtk.css'] = blob
    output['gtk-' + version + '/gtk-dark.css'] = blob


def _prebuilt(archive: Archive, root: str, *, modern3: bool = False,
              force_dark: bool = False) -> dict[str, bytes]:
    output = {}
    for version in ('3.0', '4.0'):
        source = root + '/gtk-' + ('3.20' if version == '3.0' and modern3 else version)
        _copy(archive, source, 'gtk-' + version, output)
        css = archive.read(source + ('/gtk-dark.css' if force_dark else '/gtk.css'))
        _styles(output, version, css)
    if root + '/assets' in archive.entries:
        _copy(archive, root + '/assets', 'assets', output)
    for license in ('COPYING', 'LICENSE', 'LICENSE.md', 'LICENSE.txt'):
        if root + '/' + license in archive.entries:
            output['COPYING'] = archive.read(root + '/' + license)
            break
    return output


def gtk_assets(source: Source, theme: Theme) -> dict[str, bytes]:
    family = theme.family
    if family == 'adwaita':
        return {}  # GTK's built-in Adwaita provider; no GTK2 package is needed.
    if family in REPOS:
        filename, root, pattern, assets = REPOS[family]
        archive = source.archive(filename)
        base = root + '/src/gtk/'
        output = {}
        shade = 'dark' if theme.dark else 'light'
        for version in ('3.0', '4.0'):
            css = archive.read(base + pattern.format(version=version, shade=shade, Shade=shade.title()))
            _styles(output, version, css)
            for input_path, output_path in assets:
                _copy(archive, base + input_path, 'gtk-' + version + '/' + output_path, output)
            if family == 'qogir':
                for scale in ('', '@2'):
                    output['gtk-' + version + '/assets/logo' + scale + '.svg'] = (
                        archive.read(base + 'assets/logos/logo' + scale + '-.svg'))
        for license in ('COPYING', 'LICENSE', 'LICENSE.md', 'LICENSE.txt'):
            if root + '/' + license in archive.entries:
                output['COPYING'] = archive.read(root + '/' + license)
                break
    elif family == 'catppuccin':
        root = theme.identity + '-standard+default'
        output = _prebuilt(source.archive(root + '.zip'), root)
    elif family == 'ant':
        archive = source.archive('Ant-79ddc06b40ad.tar.gz')
        output = _prebuilt(archive, 'Ant-79ddc06b40ad1e96c87d9270c71d7db3bfa0c3cd', modern3=True, force_dark=True)
    elif family == 'dracula':
        output = _prebuilt(source.archive('Dracula.tar.xz'), 'Dracula', modern3=True, force_dark=True)
    elif family in ('nordic', 'sweet', 'orchis', 'whitesur'):
        filename, root = {
            'nordic': ('Nordic.tar.xz', 'Nordic'),
            'sweet': ('Sweet-Dark.tar.xz', 'Sweet-Dark'),
            'orchis': ('Orchis.tar.xz', 'Orchis-Dark' if theme.dark else 'Orchis-Light'),
            'whitesur': ('WhiteSur-Dark.tar.xz', 'WhiteSur-Dark') if theme.dark else
                        ('WhiteSur-Light.tar.xz', 'WhiteSur-Light'),
        }[family]
        output = _prebuilt(source.archive(filename), root)
    elif family in ('arc', 'breeze', 'materia', 'yaru'):
        filename, root, package = {
            'arc': ('arc-theme_20221218-3_all.deb', 'Arc-Dark' if theme.dark else 'Arc', 'arc-theme'),
            'breeze': ('breeze-gtk-theme_6.7.4-1_amd64.deb', 'Breeze-Dark' if theme.dark else 'Breeze', 'breeze-gtk-theme'),
            'materia': ('materia-gtk-theme_20210322-1_all.deb', 'Materia-dark' if theme.dark else 'Materia-light', 'materia-gtk-theme'),
            'yaru': ('yaru-theme-gtk_25.10.3-3_all.deb', 'Yaru', 'yaru-theme-gtk'),
        }[family]
        archive = source.archive(filename)
        output = _prebuilt(archive, 'usr/share/themes/' + root)
        output['COPYING'] = archive.read('usr/share/doc/' + package + '/copyright')
    elif family == 'rose-pine':
        root = 'rose-pine' + ('-moon' if theme.identity.endswith('-moon') else
                              '-dawn' if theme.identity.endswith('-dawn') else '')
        archive = source.archive('rose-pine-gtk3.tar.gz')
        prefix = 'gtk3/' + root + '-gtk'
        output = {}
        _copy(archive, prefix + '/gtk-3.20', 'gtk-3.0', output)
        _copy(archive, prefix + '/assets', 'assets', output)
        _styles(output, '3.0', archive.read(prefix + '/gtk-3.20/gtk.css'))
        gtk4 = source.archive('rose-pine-gtk4.tar.gz')
        _styles(output, '4.0', gtk4.read('gtk4/' + root + '.css'))
    else:
        raise ValueError('desktop theme family has no GTK3/GTK4 asset recipe')
    for version in ('3.0', '4.0'):
        if not output.get('gtk-' + version + '/gtk.css'):
            raise ValueError('desktop theme lacks a complete GTK3/GTK4 provider')
    try:
        output = materialize(output, deadline=source.deadline)
    except ValueError as error:
        raise ValueError('desktop theme ' + theme.identity + ': ' + str(error)) from error
    output['index.theme'] = ('[Desktop Entry]\nType=X-GNOME-Metatheme\nName=' + theme.gtk +
                             '\n[X-GNOME-Metatheme]\nGtkTheme=' + theme.gtk + '\n').encode('utf-8')
    return output


@dataclass
class Candidate:
    directories: dict[str, dict[str, bytes]] = field(default_factory=dict)
    variants: dict[str, tuple[str, ...]] = field(default_factory=dict)
    repairs: list[dict[str, str]] = field(default_factory=list)
    count: int = 0
    size: int = 0

    def add(self, directory: str, files: dict[str, bytes]) -> None:
        parts(directory)
        if directory in self.directories or not files:
            raise ValueError('invalid or duplicate desktop theme destination')
        for path, blob in files.items():
            parts(path)
            if 'gtk-2.0' in PurePosixPath(path).parts or len(blob) > MAX_MEMBER:
                raise ValueError('prohibited or oversized installed desktop theme asset')
            self.count += 1
            self.size += len(blob)
            if self.count > MAX_FILES or self.size > MAX_BYTES:
                raise ValueError('desktop theme candidate exceeds the aggregate installation budget')
        self.directories[directory] = files


def prepare(source: Source) -> Candidate:
    validate_catalog()
    candidate = Candidate()
    for theme in VARIANTS.values():
        source.check()
        directories = []
        gtk = gtk_assets(source, theme)
        if gtk:
            directory = 'themes/' + theme.gtk
            candidate.add(directory, gtk)
            directories.append(directory)
        if theme.qt_source is not None:
            files = {}
            for extension in ('.kvconfig', '.svg'):
                path = 'qt/' + theme.qt_source + '/' + theme.qt_source + extension
                blob = source.read(path)
                files[theme.kvantum + extension] = blob
            directory = 'Kvantum/' + theme.kvantum
            candidate.add(directory, files)
            directories.append(directory)
        candidate.variants[theme.identity] = tuple(directories)
    licenses = {path.removeprefix('licenses/'): source.read(path)
                for path in source.files if path.startswith('licenses/')}
    licenses['sources.json'] = (json.dumps(source.manifest, sort_keys=True, indent=2) + '\n').encode('utf-8')
    candidate.add('doc/labwc-desktop-themes', licenses)
    return candidate
