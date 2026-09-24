"""Exercise the production wrapper; replace only its executable/host boundaries."""
from pathlib import Path
import re
from payload_fixture import read_text
from theme_fixture import render_theme_defaults

FORKY = Path(__file__).resolve().parents[1]
TARGET = FORKY / 'hooks/target'

def geometry_environment(profile='btrfs-de.env'):
    text = (FORKY / 'hosts/profiles' / profile).read_text()
    values = dict(re.findall(r'^(FUZZEL_[A-Z_]+)="([0-9]+)"$', text, re.M))
    assert len(values) == 33, 'fixture must use the complete production geometry'
    prefixes = re.search(r'^LABWC_OUTPUT_INTERNAL_PREFIXES="([^"]+)"$', text, re.M)
    values['LABWC_OUTPUT_INTERNAL_PREFIXES'] = prefixes[1]
    return values

def wrapper_script(root, executable):
    root = Path(root)
    source = render_theme_defaults(read_text(TARGET / 'usr/local/bin/labwc-fuzzel'))
    source = source.replace('/etc/labwc/desktop.conf', str(root/'missing-defaults'))
    source = source.replace('/usr/local/bin/labwc-fuzzel-log', str(root/'missing-logger'))
    source = source.replace('/usr/bin/fuzzel', str(executable))
    wrapper = root / 'labwc-fuzzel'
    wrapper.write_text(source)
    wrapper.chmod(0o700)
    return wrapper
