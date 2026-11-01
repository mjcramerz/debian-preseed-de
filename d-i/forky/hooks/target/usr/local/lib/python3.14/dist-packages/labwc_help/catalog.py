"""Strict, bounded documentation data. No document is imported as code."""
from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
from urllib.parse import urlsplit

ROOT = Path('/usr/local/share/labwc-help')
TOPIC = re.compile(r'[a-z][a-z0-9-]*(?:\.[a-z][a-z0-9-]*){1,3}\Z')
ICON = re.compile(r'[A-Za-z0-9][A-Za-z0-9._+-]{0,127}\Z')
INLINE = re.compile(r'\[([^\]\n]{1,200})\]\(([^)\s]{1,2048})\)|\*\*([^*\n]+)\*\*|\*([^*\n]+)\*|`([^`\n]+)`')
MAX_ARTICLE = 128 * 1024
MAX_LIBRARY = 8 * 1024 * 1024


def icon_name(value: object) -> str:
    # Icon metadata is decorative. A malformed value removes only that icon;
    # it must not make the documentation unavailable.
    return value if isinstance(value, str) and ICON.fullmatch(value) else ''


def text(value: object, limit: int = 4096) -> str:
    if (not isinstance(value, str) or not value.strip() or len(value) > limit
            or any(ord(c) < 32 and c not in '\n\t' for c in value)
            or any(0x7f <= ord(c) <= 0x9f or 0xd800 <= ord(c) <= 0xdfff for c in value)):
        raise ValueError('Invalid documentation text')
    return value


def keys(value: object, required: set[str], optional: set[str] = frozenset()) -> dict:
    if not isinstance(value, dict) or not required <= value.keys() or value.keys() - required - optional:
        raise ValueError('Unsupported documentation fields')
    return value


def unique_pairs(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate JSON field')
        result[key] = value
    return result


def read_data(root: Path, relative: str, limit: int, *, owner: int = 0) -> bytes:
    """Reject symlinks, writable system data, traversal and oversized files."""
    parts = PurePosixPath(relative).parts
    if (not parts or relative != '/'.join(parts) or any(p in {'.', '..'} for p in parts)
            or PurePosixPath(relative).is_absolute() or not re.fullmatch(r'[a-zA-Z0-9_./-]+', relative)):
        raise ValueError('Unsafe documentation path')
    for parent in (*reversed(root.parents), root, *(root.joinpath(*parts[:i]) for i in range(1, len(parts)))):
        info = parent.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != owner or info.st_mode & 0o022:
            raise ValueError('Untrusted documentation directory')
    descriptor = os.open(root / relative, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    with os.fdopen(descriptor, 'rb') as stream:
        info = os.fstat(stream.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != owner or info.st_mode & 0o022
                or info.st_nlink != 1 or info.st_size > limit):
            raise ValueError('Unsafe documentation file')
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise ValueError('Documentation exceeds size limit')
    return raw


def decode(raw: bytes) -> dict:
    try:
        return json.loads(raw.decode('utf-8'), object_pairs_hook=unique_pairs)
    except (UnicodeError, json.JSONDecodeError, RecursionError) as error:
        raise ValueError('Invalid documentation JSON') from error


def link_target(uri: str, topics: set[str] | dict) -> str:
    if uri.startswith('help:') and TOPIC.fullmatch(uri[5:]) and uri[5:] in topics:
        return 'topic'
    parsed = urlsplit(uri)
    if (len(uri) <= 2048 and parsed.scheme == 'https' and parsed.hostname
            and not parsed.username and not parsed.password and not parsed.fragment
            and not any(ord(c) < 33 or ord(c) > 126 for c in uri)
            and not re.search(r'%(?:0[0-9a-f]|1[0-9a-f]|7f)', uri, re.I)):
        try:
            if parsed.port not in (None, 443):
                raise ValueError('Unsupported link port')
        except ValueError as error:
            raise ValueError('Invalid documentation link') from error
        return 'external'
    raise ValueError('Unsupported or unresolved documentation link')


@dataclass(frozen=True)
class Article:
    id: str
    category: str
    title: str
    summary: str
    keywords: tuple[str, ...]
    order: int
    icon: str
    related: tuple[str, ...]
    file: str
    updated: str
    blocks: tuple[dict, ...] = ()
    error: str = ''

    @property
    def content(self) -> str:
        return '\n'.join('\n'.join(b['items']) if b['type'] == 'list' else b.get('text', b.get('alt', '')) for b in self.blocks)


class Catalog:
    def __init__(self, root: Path = ROOT, *, owner: int = 0):
        self.root = root
        self.owner = owner
        self.categories: dict[str, dict] = {}
        self.articles: dict[str, Article] = {}
        self.featured: list[str] = []

    def load(self) -> 'Catalog':
        raw = read_data(self.root, 'catalog.json', 256 * 1024, owner=self.owner)
        data = keys(decode(raw), {'version', 'categories', 'articles', 'featured'})
        if type(data['version']) is not int or data['version'] != 1:
            raise ValueError('Unsupported documentation version')
        if not isinstance(data['categories'], list) or not 1 <= len(data['categories']) <= 32:
            raise ValueError('Invalid category count')
        for item in data['categories']:
            keys(item, {'id', 'title', 'icon', 'order'})
            cid = text(item['id'], 64)
            if not re.fullmatch(r'[a-z][a-z0-9-]*', cid) or cid in self.categories:
                raise ValueError('Invalid category identifier')
            self._metadata(item)
            self.categories[cid] = item
        if not isinstance(data['articles'], list) or not 1 <= len(data['articles']) <= 256:
            raise ValueError('Invalid topic count')
        for item in data['articles']:
            keys(item, {'id', 'category', 'title', 'summary', 'keywords', 'order', 'icon', 'related', 'file', 'updated'})
            self._metadata(item)
            aid = text(item['id'], 100)
            if not TOPIC.fullmatch(aid) or aid in self.articles or item['category'] not in self.categories:
                raise ValueError('Invalid topic identity')
            for field, maximum in (('keywords', 32), ('related', 12)):
                values = item.get(field, [])
                if not isinstance(values, list) or len(values) > maximum or len(set(map(str, values))) != len(values):
                    raise ValueError('Invalid topic list')
                for value in values:
                    text(value, 100)
            if (not re.fullmatch(r'articles/[a-z0-9.-]+\.json', item['file'])
                    or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', item['updated'])):
                raise ValueError('Invalid article path or date')
            self.articles[aid] = Article(aid, item['category'], item['title'], text(item['summary'], 500), tuple(item['keywords']), item['order'], item['icon'], tuple(item['related']), item['file'], item['updated'])
        if any(set(a.related) - self.articles.keys() or a.id in a.related for a in self.articles.values()):
            raise ValueError('Unresolved related topic')
        if (not isinstance(data['featured'], list) or len(data['featured']) > 12
                or any(not isinstance(x, str) or x not in self.articles for x in data['featured'])):
            raise ValueError('Invalid featured topics')
        self.featured = data['featured']
        total = len(raw)
        from dataclasses import replace
        for aid, article in list(self.articles.items()):
            try:
                raw = read_data(self.root, article.file, MAX_ARTICLE, owner=self.owner)
                total += len(raw)
                if total > MAX_LIBRARY:
                    raise ValueError('Documentation library exceeds size limit')
                blocks = self._blocks(decode(raw))
                self.articles[aid] = replace(article, blocks=blocks)
            except (OSError, ValueError) as error:
                # Do not echo hostile payloads, paths or parser excerpts in UI.
                self.articles[aid] = replace(article, error='This guide is missing or invalid. Reinstall the managed Help assets.')
                if total > MAX_LIBRARY:
                    raise ValueError('Documentation library exceeds size limit') from error
        return self

    @staticmethod
    def _metadata(item: dict) -> None:
        text(item['title'], 160)
        item['icon'] = icon_name(item['icon'])
        if type(item['order']) is not int or not 0 <= item['order'] <= 10000:
            raise ValueError('Invalid topic order')

    def _blocks(self, data: dict) -> tuple[dict, ...]:
        keys(data, {'version', 'blocks'})
        if type(data['version']) is not int or data['version'] != 1 or not isinstance(data['blocks'], list) or not 1 <= len(data['blocks']) <= 128:
            raise ValueError('Invalid article blocks')
        for block in data['blocks']:
            if not isinstance(block, dict):
                raise ValueError('Invalid article block')
            kind = block.get('type')
            if kind in {'paragraph', 'heading', 'code', 'warning'}:
                keys(block, {'type', 'text'}, {'level'} if kind == 'heading' else set())
                text(block['text'], 16000 if kind == 'code' else 8000)
                if kind == 'heading' and (type(block.get('level')) is not int or block['level'] not in (2, 3)):
                    raise ValueError('Invalid heading level')
            elif kind == 'list':
                keys(block, {'type', 'items'})
                if not isinstance(block['items'], list) or not 1 <= len(block['items']) <= 64:
                    raise ValueError('Invalid list')
                for item in block['items']:
                    text(item, 2000)
            elif kind == 'image':
                keys(block, {'type', 'path', 'alt'})
                text(block['alt'], 300)
                if not re.fullmatch(r'images/[a-z0-9-]+\.png', block['path']):
                    raise ValueError('Invalid image path')
                raw = read_data(self.root, block['path'], 1024 * 1024, owner=self.owner)
                # Bound dimensions before asking GTK to decode a raster image.
                if len(raw) < 24 or raw[:8] != b'\x89PNG\r\n\x1a\n' or raw[12:16] != b'IHDR':
                    raise ValueError('Invalid PNG')
                width, height = int.from_bytes(raw[16:20]), int.from_bytes(raw[20:24])
                if not 0 < width <= 4096 or not 0 < height <= 4096 or width * height > 8_000_000:
                    raise ValueError('Oversized image')
            else:
                raise ValueError('Unsupported block type')
            if kind != 'code':
                for source in block.get('items', [block.get('text', '')]):
                    for match in INLINE.finditer(source):
                        if match.group(2):
                            link_target(match.group(2), self.articles)
        return tuple(data['blocks'])
