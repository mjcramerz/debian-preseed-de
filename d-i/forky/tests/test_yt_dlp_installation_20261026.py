"""Unexecuted static fixtures for the complete yt-dlp integration.

These fixtures inspect source and pinned manifest data only. They do not invoke
yt-dlp, download a plugin, contact a supported site, or run installer code.
Repository guidance requires them to remain unexecuted in this checkout.
"""
from __future__ import annotations

from pathlib import Path as _IsolationPath
import sys as _isolation_sys
_isolation_sys.path.insert(0, str(_IsolationPath(__file__).resolve().parents[3] / 'tools'))
from isolation import require_test_isolation as _require_test_isolation
_isolation_sys.path.pop(0)
_require_test_isolation()

import json
from pathlib import Path
import unittest


class YtDlpInstallationFixtures(unittest.TestCase):
    root = Path(__file__).resolve().parents[1]

    def test_official_runtime_preserves_full_configuration_and_plugin_discovery(self):
        source = (self.root / 'scripts/late/devops-tools.py').read_text(encoding='utf-8')
        wrapper = (self.root / 'hooks/target/usr/local/bin/youtube-dl').read_text(encoding='utf-8')
        public_cli = (self.root / 'hooks/target/usr/local/bin/yt-dlp').read_text(encoding='utf-8')
        for forbidden in ('--ignore-config', '--no-plugin-dirs', 'YTDLP_NO_PLUGINS', '--no-remote-components'):
            self.assertNotIn(forbidden, source)
            self.assertNotIn(forbidden, wrapper)
        config = (self.root / 'hooks/target/etc/yt-dlp/config').read_text(encoding='utf-8')
        self.assertIn('--plugin-dirs /usr/local/lib/yt-dlp/libexec/yt-dlp-plugins', config)
        self.assertIn('exec /usr/local/lib/yt-dlp/bin/yt-dlp "$@"', public_cli)
        self.assertIn('extractor/postprocessor plugins', source)

    def test_plugin_manifest_is_pinned_and_matches_the_standalone_release(self):
        manifest_path = self.root / 'scripts/late/devops/yt-dlp-plugins.json'
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
        self.assertEqual(manifest['schema'], 1)
        self.assertEqual(manifest['yt_dlp_version'], '2026.08.19')
        plugin_ids = {plugin['id'] for plugin in manifest['plugins']}
        self.assertGreaterEqual(
            plugin_ids,
            {'bgutil-pot', 'rajiko', 'apple-developer', 'srt-fix',
             'return-youtube-dislike', 'fixup-mtime'},
        )
        paths = []
        for plugin in manifest['plugins']:
            self.assertTrue(plugin['source'].startswith('https://'))
            for item in plugin['files']:
                self.assertRegex(item['sha256'], r'^[0-9a-f]{64}$')
                self.assertGreater(item['size'], 0)
                self.assertTrue(item['url'].startswith('https://'))
                paths.append(item['path'])
        self.assertEqual(len(paths), len(set(paths)))
        helper = (self.root / 'scripts/late/devops-tools.py').read_text(encoding='utf-8')
        self.assertNotIn('--list-extractors', helper)
        self.assertNotIn('missing expected built-in/plugin extractors', helper)

    def test_builtin_catalog_is_not_replaced_by_a_youtube_only_allowlist(self):
        wrapper = (self.root / 'hooks/target/usr/local/bin/youtube-dl').read_text(encoding='utf-8')
        docs = (self.root / 'hooks/target/usr/local/share/doc/yt-dlp/CONFIGURATION.md').read_text(encoding='utf-8')
        self.assertIn('HTTP or HTTPS media URL', wrapper)
        self.assertIn('complete built-in extractor catalog', docs)
        self.assertIn('Pornhub', docs)
        self.assertIn('make_supportedsites.py', docs)
        self.assertNotIn('youtube.com only', wrapper.lower())


if __name__ == '__main__':
    raise SystemExit(unittest.main())
