#!/usr/bin/env python3
"""Reproducible browser imports and policies; Python standard library only.

The inputs are reviewed configuration, not captured browser traffic. Coverage
means an applicable configuration, NEVER a claim of authenticated site testing.
Run this before tools/build.py. --check detects edits to generated artifacts.
"""
from __future__ import annotations
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import tempfile
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / 'browser-config'
TARGET = ROOT / 'd-i/forky/hooks/target'
EXPORT_DIR = TARGET / 'usr/local/share/browser-imports'
EXCLUDED = {'entertainment', 'imported'}
UBOL = 'ddkjiahejlhfcafbddmgiahcphecmpfh'
NOSCRIPT = 'doojmbjmlfjjnbmnoijecmcbfeoakpjm'
BADGER = 'pkehgijcmpdhfbdbbnkijodmdjhbjlgp'
PB_FILE = 'PrivacyBadger_user_data-9_6_2026_1_50_43_PM.json'
BASE_CAPS = ['frame', 'noscript', 'other']
APP_CAPS = ['script', 'frame', 'font', 'fetch', 'noscript', 'lazy_load', 'other']
# IDs verified against uBOL 2026.901.1442, NOT a list of arbitrary filter URLs.
DEFAULT_RULESETS = ['ublock-filters', 'easylist', 'easyprivacy', 'pgl', 'ublock-badware', 'urlhaus-full']
EXTRA_RULESETS = ['adguard-spyware-url', 'block-lan', 'swe-1', 'annoyances-cookies', 'annoyances-notifications']
KNOWN_RULESETS = set(DEFAULT_RULESETS + EXTRA_RULESETS)


def read_json(name: str):
    return json.loads((CONFIG / name).read_text(encoding='utf-8'))


def origin(url: str) -> str | None:
    """Canonical web origin; never turn browser/extension URLs into DNS hosts."""
    p = urlsplit(url)
    if p.scheme not in {'https', 'http'}:
        return None
    if not p.hostname or p.username is not None or p.password is not None:
        raise ValueError(f'Invalid/credential-bearing bookmark: {url!r}')
    host = p.hostname.encode('idna').decode('ascii').lower()
    if ':' in host:
        host = f'[{host}]'
    port = p.port
    suffix = '' if port in (None, 443 if p.scheme == 'https' else 80) else f':{port}'
    return f'{p.scheme}://{host}{suffix}'


def permission(caps: list[str]) -> dict:
    return {'capabilities': sorted(set(caps)), 'temp': False}


def generate() -> dict[Path, bytes]:
    bookmarks = read_json('bookmarks.json')
    ns = read_json('noscript-base.json')
    pb_settings = read_json('badger-settings-base.json')
    trackers = read_json('reviewed-trackers.json')
    provenance = read_json('provenance.json')
    rows = []
    origins = set()
    for item in bookmarks:
        excluded = sorted(EXCLUDED.intersection(x.casefold() for x in item['folders']))
        web_origin = origin(item['url'])
        status = 'excluded-folder' if excluded else ('configured-unverified' if web_origin else 'browser-internal-or-non-web')
        row = dict(item, origin=web_origin, status=status, excluded_by=excluded,
                   live_tested=False)
        if status == 'configured-unverified':
            origins.add(web_origin)
        rows.append(row)

    custom: dict[str, dict] = {}
    dependencies: list[dict] = []

    def grant(resource: str, context: str, caps: list[str], reason: str) -> None:
        # Origins are exact; the secure-domain marker is used only for reviewed
        # dedicated resource CDNs, and only with an explicit first-party context.
        entry = custom.setdefault(resource, dict(permission(BASE_CAPS), contextual={}))
        existing = entry['contextual'].get(context, permission([]))['capabilities']
        entry['contextual'][context] = permission(existing + caps)
        if resource != context:
            dependencies.append({'resource': resource, 'context': context,
                                 'capabilities': sorted(set(caps)), 'reason': reason,
                                 'evidence': 'compatibility-candidate-not-live-observed'})

    media_hosts = {'www.youtube.com', 'www.svtplay.se', 'zoom.us', 'discord.com', 'www.reddit.com', 'x.com'}
    graphics_hosts = {'www.figma.com', 'www.canva.com', 'stackblitz.com', 'codesandbox.io', 'replit.com'}
    for top in sorted(origins):
        caps = list(APP_CAPS)
        host = urlsplit(top).hostname
        if host in media_hosts:
            caps += ['media']
        if host in graphics_hosts:
            caps += ['wasm', 'webgl']
        grant(top, top, caps, 'exact bookmarked first party')

    # Reviewable small dependency groups, never globally TRUSTED CDNs or SSO.
    # Password, payment, CAPTCHA, media and SPA behavior still needs live tests.
    groups = [
        (('github.com','gist.github.com','docs.github.com'),
         {'https://github.githubassets.com': ['script','font','fetch'],
          'https://api.github.com': ['fetch'],
          'https://avatars.githubusercontent.com': ['fetch']}, []),
        (('chatgpt.com','platform.openai.com','developers.openai.com','openai.com'),
         {'https://cdn.oaistatic.com':['script','font','fetch'],
          'https://auth.openai.com': APP_CAPS,
          'https://challenges.cloudflare.com':['script','frame','fetch']}, ['https://auth.openai.com']),
        (('claude.ai','console.anthropic.com'),
         {'https://claude.ai': APP_CAPS,
          'https://console.anthropic.com': APP_CAPS,
          'https://challenges.cloudflare.com':['script','frame','fetch']}, []),
        (('docs.google.com','script.google.com','gemini.google.com','cloud.google.com','www.google.com'),
         {'https://accounts.google.com': APP_CAPS,
          'https://www.gstatic.com':['script','font','fetch'],
          'https://ssl.gstatic.com':['script','font','fetch'],
          'https://fonts.gstatic.com':['font'],
          'https://apis.google.com':['script','fetch']}, ['https://accounts.google.com']),
        (('learn.microsoft.com','m365.cloud.microsoft','www.microsoft.com','azure.microsoft.com','sharepoint.com'),
         {'https://login.microsoftonline.com': APP_CAPS,
          'https://login.live.com': APP_CAPS,
          'https://aadcdn.msauth.net':['script','font','fetch'],
          'https://aadcdn.msftauth.net':['script','font','fetch']}, ['https://login.microsoftonline.com','https://login.live.com']),
        (('atlassian.com','atlassian.net','trello.com'),
         {'https://id.atlassian.com': APP_CAPS,
          '\u00a7:atl-paas.net':['script','font','fetch'],
          'https://trello.com': APP_CAPS}, ['https://id.atlassian.com']),
        (('www.reddit.com',),
         {'\u00a7:redditstatic.com':['script','font','fetch'],
          'https://oauth.reddit.com':['fetch'],
          'https://www.redditstatic.com':['script','font','fetch']}, []),
        (('x.com',),
         {'https://abs.twimg.com':['script','font','fetch'],
          'https://api.x.com':['fetch'],
          'https://video.twimg.com':['media','fetch']}, []),
        (('www.linkedin.com',),
         {'https://static.licdn.com':['script','font','fetch']}, []),
        (('www.youtube.com',),
         {'\u00a7:ytimg.com':['script','font','fetch'],
          '\u00a7:googlevideo.com':['media','fetch'],
          'https://youtubei.googleapis.com':['fetch']}, []),
        (('discord.com',),
         {'https://cdn.discordapp.com':['fetch','media'],
          'https://gateway.discord.gg':['fetch'],
          'https://media.discordapp.net':['media','fetch']}, []),
    ]
    for suffixes, resources, login_tops in groups:
        active = {top for top in origins if any(urlsplit(top).hostname == suffix or
                  urlsplit(top).hostname.endswith('.' + suffix) for suffix in suffixes)}
        if not active:
            continue
        for login in login_tops:
            grant(login, login, APP_CAPS, 'explicit login redirect origin')
        for top in sorted(active | set(login_tops)):
            for resource, caps in resources.items():
                grant(resource, top, list(caps), 'scoped service/login resource; verify on use')

    ns['policy'].update(DEFAULT=permission(BASE_CAPS), TRUSTED=permission(APP_CAPS),
                        UNTRUSTED=permission([]), enforced=True, autoAllowTop=False,
                        sites={'trusted': [], 'untrusted': sorted(trackers),
                               'custom': dict(sorted(custom.items()))})
    ns['local'].pop('uuid', None)  # keep the destination installation's own identity
    ns['local'].update(showFullAddresses=True, debug=False)
    ns['sync'].update({'global':False, 'xss':True, 'clearclick':True,
                       'cascadePermissions':False, 'cascadeRestrictions':False})
    ns['contextStore'] = {'enabled':False,'policies':{}}

    ub = {'version': provenance['export_version_ubol'],
          'rulesets': ['+' + k for k in EXTRA_RULESETS],
          'filteringModes': {'none': [], 'basic': [], 'optimal': ['all-urls'], 'complete': []},
          'strictBlockMode': True, 'popupBlockMode': False, 'showBlockedCount': True}
    pb_settings.update(sendDNTSignal=False, checkForDNTPolicy=False,
                       learnLocally=False, learnInIncognito=False, disabledSites=[],
                       widgetReplacementExceptions=[], widgetSiteAllowlist={}, showCounter=True)
    # PB merges imports; explicit user actions are necessary for new tracker
    # entries without snitch history. Do not invent prevalence observations.
    pb = {'action_map': {h:{'userAction':'user_' + action, 'heuristicAction':'',
                           'dnt':False,'nextUpdateTime':0} for h,action in sorted(trackers.items())},
          'settings_map':pb_settings,'snitch_map':{},'tracking_map':{},'fp_scripts':{}}
    for row in rows:
        if row['status'] == 'configured-unverified':
            top = row['origin']
            row['noscript_capabilities'] = custom[top]['contextual'][top]['capabilities']
            row['ubol'] = 'global-optimal; no bypass'
            row['privacy_badger'] = 'enabled; upstream tracker data plus reviewed blocks; no first-party bypass'
            row['manual_checks'] = ['authentication', 'third-party dependencies', 'downloads', 'performance']
            if top.startswith('http://') or urlsplit(top).hostname == 'www.asusrouter.com':
                row['manual_checks'] += ['local-network/TLS policy; no blanket LAN or certificate bypass']
    coverage = {'schema_version':1, 'scope':'Configuration coverage, not verified site functionality',
                'counts':{'bookmark_entries':len(rows), 'included_web_entries':sum(r['status']=='configured-unverified' for r in rows),
                          'included_web_origins':len(origins), 'excluded_folder_entries':sum(r['status']=='excluded-folder' for r in rows),
                          'internal_or_non_web_entries':sum(r['status']=='browser-internal-or-non-web' for r in rows),
                          'live_tested_entries':0},
                'default_ubol_rulesets':DEFAULT_RULESETS,'additional_ubol_rulesets':EXTRA_RULESETS,
                'reviewed_tracker_count':len(trackers),'entries':rows,'dependencies':dependencies,
                'provenance':provenance}

    output: dict[Path, bytes] = {}
    def emit(path:Path, value:dict) -> None:
        output[path] = (json.dumps(value,ensure_ascii=False,indent=2,sort_keys=True)+'\n').encode()
    for name,value in [('noscript_data.txt',ns),('my-ubol-settings.json',ub),(PB_FILE,pb),('bookmark-coverage.json',coverage)]:
        emit(EXPORT_DIR/name,value)
    security = {'DeveloperToolsAvailability':1,'RemoteDebuggingAllowed':True,
                'ExtensionDeveloperModeSettings':0,'DefaultInsecureContentSetting':2,
                'SSLErrorOverrideAllowed':False,'DownloadRestrictions':1,
                'DisableSafeBrowsingProceedAnyway':True}
    telemetry = {'MetricsReportingEnabled':False,'CloudReportingEnabled':False,
                 'SafeBrowsingProtectionLevel':1,'SafeBrowsingExtendedReportingEnabled':False,
                 'UrlKeyedAnonymizedDataCollectionEnabled':False,'SpellCheckServiceEnabled':False}
    recommended = {'BackgroundModeEnabled':False,'BlockThirdPartyCookies':True,
                   'NetworkPredictionOptions':2,'SearchSuggestEnabled':False,
                   'AutofillAddressEnabled':False,'AutofillCreditCardEnabled':False,
                   'PasswordManagerEnabled':False}
    # Content-setting policies do not support recommended level. Leave them
    # unset so permissions remain user-adjustable; use initial profile defaults.
    for family in ['etc/vivaldi','etc/chromium','etc/opt/edge','etc/opt/chrome']:
        base=TARGET/family/'policies'
        family_security = dict(security)
        family_telemetry = dict(telemetry)
        if family == 'etc/opt/edge':
            # Edge uses Microsoft policy names, not Chrome Safe Browsing or UKM.
            family_security.pop('DisableSafeBrowsingProceedAnyway')
            family_telemetry = {'ConfigureDoNotTrack': False,
                                'SpellCheckServiceEnabled': False}
        emit(base/'managed/security.json',family_security)
        emit(base/'managed/telemetry.json',family_telemetry)
        emit(base/'managed/performance.json',{})
        emit(base/'recommended/defaults.json',recommended)
    extensions = {'ExtensionSettings':{k:{'installation_mode':'normal_installed',
                     'update_url':'https://clients2.google.com/service/update2/crx',
                     'toolbar_pin':'default_pinned','file_url_navigation_allowed':False}
                     for k in [UBOL,NOSCRIPT,BADGER]},
                  '3rdparty':{'extensions':{
                      UBOL:{'disableFirstRunPage':True},
                      BADGER:{'sendDNTSignal':False,'checkForDNTPolicy':False}}}}
    # Install the same reviewed extension set in the primary browser only.
    # Other Chromium-family browsers get debugging/privacy policy, not forced
    # redundant blockers or unexpected extension installs.
    emit(TARGET/'etc/vivaldi/policies/managed/extensions.json', extensions)
    for profile in ['chromium', 'microsoft-edge', 'vivaldi']:
        emit(TARGET/'etc/skel/.config'/profile/'Default/Preferences', {
            'browser': {'custom_chrome_frame': False},
            'enable_do_not_track': False,
            'profile': {'default_content_setting_values': {
                'notifications': 2, 'popups': 2, 'sensors': 2}}})
    return output


def main() -> int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check',action='store_true')
    args=parser.parse_args()
    changed=[]
    for path,data in generate().items():
        if path.exists() and path.read_bytes()==data:
            continue
        changed.append(str(path.relative_to(ROOT)))
        if not args.check:
            path.parent.mkdir(parents=True,exist_ok=True)
            fd,name=tempfile.mkstemp(prefix='.'+path.name+'.',dir=path.parent)
            try:
                with os.fdopen(fd,'wb') as f:
                    f.write(data)
                os.chmod(name,0o644)
                os.replace(name,path)
            finally:
                if os.path.exists(name):os.unlink(name)
    if args.check and changed:
        parser.exit(1,'Stale browser artifacts:\n'+'\n'.join(changed)+'\n')
    print('Browser artifacts current' if args.check else f'Updated {len(changed)} browser artifacts')
    return 0

if __name__=='__main__':
    raise SystemExit(main())
