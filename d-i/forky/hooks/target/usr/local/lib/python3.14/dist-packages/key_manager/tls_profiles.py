"""Small X.509 recipes; custom purposes use validated OIDs, never config snippets."""
from __future__ import annotations

from dataclasses import dataclass, replace
import ipaddress
import re
from urllib.parse import urlsplit

from .core import choose, confirm, dns, number, prompt

KEY_TYPES = ('ECDSA P-384', 'ECDSA P-256', 'ECDSA P-521',
             'RSA 4096', 'RSA 3072', 'Ed25519', 'Ed448')
RSA = ('RSA 4096', 'RSA 3072')
RSA_EC = (*RSA, 'ECDSA P-256', 'ECDSA P-384', 'ECDSA P-521')
ML_DSA = ('ML-DSA-44', 'ML-DSA-65', 'ML-DSA-87')
KEY_USAGE = ('digitalSignature', 'nonRepudiation', 'keyEncipherment', 'dataEncipherment',
             'keyAgreement', 'keyCertSign', 'cRLSign', 'encipherOnly', 'decipherOnly')
EKU = ('serverAuth', 'clientAuth', 'codeSigning', 'emailProtection', 'timeStamping', 'OCSPSigning')


@dataclass(frozen=True)
class Profile:
    label: str
    keys: tuple[str, ...] = KEY_TYPES
    eku: tuple[str, ...] = ('serverAuth',)
    usage: tuple[str, ...] = ('digitalSignature',)
    san_required: bool = True
    rsa_encipherment: bool = False
    eku_critical: bool = False
    digest: str = 'sha256'
    days: int = 90
    container: str = 'modern'
    full_chain: bool = False
    external_ca: bool = False
    ca_keys: tuple[str, ...] = ()
    ocsp_no_check: bool = False
    policies: tuple[str, ...] = ()
    ocsp_urls: tuple[str, ...] = ()
    issuer_urls: tuple[str, ...] = ()
    crl_urls: tuple[str, ...] = ()
    constraints: tuple[str, ...] = ()
    must_staple: bool = False


PROFILES = (
    Profile('HTTPS / reverse proxy / DoT server', rsa_encipherment=True),
    Profile('mTLS / VPN / EAP-TLS client', eku=('clientAuth',), san_required=False),
    Profile('Internal server and client authentication', eku=('serverAuth', 'clientAuth'), rsa_encipherment=True),
    Profile('Kernel / module / Authenticode code signing', keys=RSA, eku=('codeSigning',), san_required=False, days=365),
    Profile('S/MIME email signing and encryption', keys=RSA, eku=('emailProtection',),
            usage=('digitalSignature', 'nonRepudiation', 'keyEncipherment'), days=365),
    Profile('RFC3161 timestamp authority', keys=RSA_EC, eku=('timeStamping',),
            san_required=False, eku_critical=True, days=365),
    Profile('Delegated OCSP responder', keys=RSA_EC, eku=('OCSPSigning',),
            san_required=False, ocsp_no_check=True),
    Profile('Windows smartcard logon / UPN identity', keys=RSA,
            eku=('clientAuth', '1.3.6.1.4.1.311.20.2.2'), days=365),
    Profile('Microsoft Entra application certificate', keys=RSA, eku=(), san_required=False, days=365),
    Profile('Azure App Service public TLS binding', keys=RSA, rsa_encipherment=True,
            container='azure-app-service', full_chain=True, external_ca=True),
    Profile('Azure App Service Environment private TLS', keys=RSA, rsa_encipherment=True,
            container='azure-app-service', full_chain=True),
    Profile('Azure Application Gateway listener', keys=RSA_EC, rsa_encipherment=True, full_chain=True),
    Profile('Azure Key Vault certificate import', keys=RSA_EC, eku=(), san_required=False),
    Profile('Azure P2S VPN client', keys=RSA, eku=('clientAuth',), san_required=False,
            ca_keys=RSA, full_chain=True, days=365),
    Profile('AWS ACM / load balancer', keys=RSA_EC, rsa_encipherment=True, container='pem-split'),
    Profile('AWS CloudFront', keys=(*RSA, 'ECDSA P-256'), rsa_encipherment=True, container='pem-split'),
    Profile('Google Cloud load balancer', keys=(*RSA, 'ECDSA P-256', 'ECDSA P-384'),
            rsa_encipherment=True, container='pem-split'),
    Profile('Experimental ML-DSA X.509 (consumer support required)', keys=ML_DSA),
)
PLATFORM_PROFILES = PROFILES[8:17]


def oid(value: str) -> str:
    if not re.fullmatch(r'[0-2](?:\.(?:0|[1-9][0-9]{0,9})){2,24}', value):
        raise ValueError('use a numeric ASN.1 object identifier')
    parts = list(map(int, value.split('.')))
    if parts[0] < 2 and parts[1] > 39:
        raise ValueError('invalid second OID arc')
    return value


def url(value: str) -> str:
    parsed = urlsplit(value)
    if (parsed.scheme not in ('http', 'https', 'spiffe', 'urn')
            or any(c in value for c in '\\$#;,"\'\n\r\t ') or not value.isascii()
            or len(value) > 2048 or parsed.username is not None or parsed.password is not None):
        raise ValueError('use a plain HTTP(S), SPIFFE or URN identifier without config delimiters')
    if parsed.scheme != 'urn' and not parsed.hostname:
        raise ValueError('URI requires a hostname')
    if parsed.scheme == 'urn' and not parsed.path:
        raise ValueError('URN requires a namespace and identifier')
    return value


def san_values(value: str) -> tuple[str, ...]:
    result = []
    for item in value.replace(',', ' ').split():
        prefix, _, body = item.partition(':')
        if prefix.upper() in ('DNS', 'IP', 'EMAIL', 'URI', 'UPN'):
            kind = prefix.upper()
        else:
            body = item
            try:
                ipaddress.ip_address(body)
                kind = 'IP'
            except ValueError:
                kind = 'DNS'
        if kind == 'IP':
            body = str(ipaddress.ip_address(body))
        elif kind == 'DNS':
            body = dns(body, wildcard=True)
        elif kind in ('EMAIL', 'UPN'):
            if not re.fullmatch(r'[A-Za-z0-9._+%-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,63}', body):
                raise ValueError('invalid email or UPN SAN')
        else:
            body = url(body)
        entry = kind + ':' + body
        if entry not in result:
            result.append(entry)
    if not result or len(result) > 100:
        raise ValueError('provide 1–100 SAN identities')
    return tuple(result)


def select() -> Profile | None:
    labels = [p.label for p in PROFILES]
    chosen = choose('X.509 purpose / consumer', labels + ['Advanced custom X.509 purpose'])
    if chosen is None:
        return None
    if chosen != 'Advanced custom X.509 purpose':
        return PROFILES[labels.index(chosen)]
    usages = tuple(v.strip() for v in prompt('Key usage (comma separated)', 'digitalSignature').split(','))
    if not usages or any(v not in KEY_USAGE for v in usages) or any(v in usages for v in ('keyCertSign', 'cRLSign')):
        raise ValueError('select leaf key usages; CA signing uses the CA menu')
    if any(v in usages for v in ('encipherOnly', 'decipherOnly')) and 'keyAgreement' not in usages:
        raise ValueError('encipherOnly/decipherOnly require keyAgreement')
    supplied = prompt('EKUs (names or numeric OIDs, comma separated; none omits)', 'serverAuth')
    values = () if supplied == 'none' else tuple(v.strip() for v in supplied.split(','))
    for value in values:
        if value not in EKU:
            oid(value)
    digest = choose('Certificate signature digest', ['sha256', 'sha384', 'sha512'])
    if digest is None:
        return None
    kinds = KEY_TYPES
    if any(v in usages for v in ('keyEncipherment', 'dataEncipherment')):
        kinds = RSA
    elif 'keyAgreement' in usages:
        kinds = ('ECDSA P-256', 'ECDSA P-384', 'ECDSA P-521')
    if 'keyAgreement' in usages and any(v in usages for v in ('keyEncipherment', 'dataEncipherment')):
        raise ValueError('use separate profiles for key agreement and RSA encipherment')
    profile = Profile('Advanced custom X.509 purpose', keys=kinds, eku=values, usage=usages, digest=digest,
                      san_required=confirm('Require SAN identities?'),
                      eku_critical=confirm('Mark the EKU extension critical?'))
    if 'timeStamping' in values and (values != ('timeStamping',) or not profile.eku_critical):
        raise ValueError('timestamp authority certificates require only critical timeStamping EKU')
    if 'serverAuth' in values and confirm('Require OCSP stapling (consumer must serve valid staples)?'):
        profile = replace(profile, must_staple=True)
    if confirm('Add certificate policy OIDs?'):
        profile = replace(profile, policies=tuple(oid(v.strip()) for v in prompt('Policy OIDs (comma separated)').split(',')))
    return additional_extensions(profile)


def additional_extensions(profile: Profile, *, ca: bool = False) -> Profile:
    values = {}
    for field, label in (('ocsp_urls', 'OCSP responder'), ('issuer_urls', 'Issuer certificate download'),
                         ('crl_urls', 'CRL distribution')):
        if confirm('Add ' + label + ' URLs to the certificate?'):
            supplied = tuple(url(v) for v in prompt(label + ' URLs (space separated)').split())
            if not supplied or len(supplied) > 20 or any(urlsplit(v).scheme not in ('http', 'https') for v in supplied):
                raise ValueError('certificate service URLs must use HTTP or HTTPS')
            values[field] = supplied
    if ca and confirm('Constrain CA DNS / IP namespaces?'):
        constraints = []
        for value in prompt('Constraints (e.g. permitted:DNS:.example.com excluded:IP:10.0.0.0/8)').split():
            rule, kind, body = value.split(':', 2)
            if rule not in ('permitted', 'excluded'):
                raise ValueError('constraint must be permitted or excluded')
            if kind == 'DNS':
                dns(body.removeprefix('.'))
            elif kind == 'IP':
                network = ipaddress.ip_network(body, strict=False)
                body = str(network.network_address) + '/' + str(network.netmask)
            else:
                raise ValueError('CA constraints support DNS and IP namespaces')
            constraints.append(rule + ';' + kind + ':' + body)
        if not constraints or len(constraints) > 100:
            raise ValueError('too many CA constraints')
        values['constraints'] = tuple(constraints)
    return replace(profile, **values)


def extensions(profile: Profile, identities: tuple[str, ...], kind: str,
               *, ca: bool = False, pathlen: int = 1) -> str:
    usage = ('keyCertSign', 'cRLSign') if ca else profile.usage
    if not ca and profile.rsa_encipherment and kind.startswith('RSA'):
        usage = (*usage, 'keyEncipherment')
    value = ('basicConstraints=critical,CA:TRUE,pathlen:' + str(pathlen) if ca
             else 'basicConstraints=critical,CA:FALSE') + '\n'
    value += 'keyUsage=critical,' + ','.join(dict.fromkeys(usage)) + '\nsubjectKeyIdentifier=hash\n'
    if profile.eku and not ca:
        value += 'extendedKeyUsage=' + ('critical,' if profile.eku_critical else '') + ','.join(profile.eku) + '\n'
    if profile.ocsp_no_check and not ca:
        value += 'noCheck=ignored\n'
    if profile.must_staple and not ca:
        value += 'tlsfeature=status_request\n'
    if profile.policies:
        value += 'certificatePolicies=' + ','.join(profile.policies) + '\n'
    if profile.crl_urls:
        value += 'crlDistributionPoints=' + ','.join('URI:' + u for u in profile.crl_urls) + '\n'
    access = ['OCSP;URI:' + u for u in profile.ocsp_urls] + ['caIssuers;URI:' + u for u in profile.issuer_urls]
    if access:
        value += 'authorityInfoAccess=' + ','.join(access) + '\n'
    if profile.constraints:
        value += 'nameConstraints=critical,' + ','.join(profile.constraints) + '\n'
    if identities:
        value += 'subjectAltName=@san\n[san]\n'
        for index, entry in enumerate(identities, 1):
            tag, body = entry.split(':', 1)
            if tag == 'UPN':
                value += f'otherName.{index}=1.3.6.1.4.1.311.20.2.3;UTF8:{body}\n'
            else:
                tag = 'email' if tag == 'EMAIL' else tag
                value += f'{tag}.{index}={body}\n'
    return value
