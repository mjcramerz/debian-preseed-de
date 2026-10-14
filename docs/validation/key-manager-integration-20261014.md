# Key-manager integration and development-tool ownership

## Installed contract

`key-manager` is an interpreted Python command installed as root:root mode 0755
at `/usr/local/bin/key-manager`. Its modules are root-owned mode 0644 under
`/usr/local/lib/python3.14/dist-packages/key_manager/`. The isolated Python
entrypoint imports only the installed module directory. No Go application build,
copied Makefile, `install.sh`, `.env`, private configuration, or compiler download
is part of this integration.

The desktop role stages the command, modules, shared descriptor-based filesystem
module, configuration and renewal units. Direct package additions are `openssl`,
`certbot`, `python3-certbot-dns-cloudflare` and
`python3-certbot-dns-rfc2136`. Existing `gpg`, `gpg-agent`, `pinentry-qt`, OpenSSH,
Python and fzf selections are retained. There is no additional pinentry backend.

### Existing interfaces and storage

- Terminal selections and confirmations follow the existing gitbuild fzf pattern.
- GPG passphrase prompts use the existing desktop **pinentry-qt** policy. The
  installer stages the canonical `etc/skel-desktop/.gnupg/gpg-agent.conf` verbatim
  as `/usr/local/share/key-manager/gpg-agent.conf` for new stores and previews.
  No separate cache or smartcard policy is invented. Existing desktop keyring
  configuration is retained.
- `/etc/key-manager/settings.json` is rendered from `DIR_DATA_PKI` and the desktop
  account. Privileged TLS reads only this installer-owned layout, not a
  user-writable root override or settings file from the copied application.
- The existing `/data/pki` root and `ssh/.keys`, `ssh/ca`, `ssh/config.d` and
  `ssh/control` layout are used. No second top-level key-pair tree is created.
  GPG, PQC, TLS and exports derive from that same root.
- The installer Git identity remains in `~/.local/share/ssh/private` and `~/.ssh`.
  Its public fingerprint is available in key-manager. The existing desktop
  `~/.gnupg` remains directly available as the `desktop` store.
- SSH uses the existing `/run/user/<uid>/openssh_agent`, `ssh-agent.socket` and
  `ssh-agent.service`. No additional SSH agent service or shell startup hook is
  installed. Existing Git host configuration retains its precedence.
- The SSH config Include is rendered from the same `DIR_DATA_PKI` as key-manager.

### Redesigned GPG stores

Additional stores are explicitly created by the user under `PKI_ROOT/gpg/<name>`.
There are no implicitly created `git/private/release/verify` stores. Names and
policies are validated, and both registration and active selection are persisted
atomically in `PKI_ROOT/config/gpg-stores.json`. An unregistered existing directory
is never silently adopted. A missing registered store is an error.

| Policy | Available operations |
| --- | --- |
| Existing desktop | Existing identity and trust state; general operations |
| General | Generate signing/certification primary with encryption and authentication subkeys; signing, encryption and trust management |
| Signing | Signing identities, signatures, revocation, backups and trust management; encryption operations disabled |
| Public | Public-key import, inventory and signature verification; secret import/export, generation, signing, encryption and trust writes disabled |

Store policies are application guards. All user stores are owned by the same
desktop UID; they are not an operating-system isolation boundary between programs
running as that UID. Each store has independent GnuPG keys and ownertrust.

Imports are previewed in a private temporary keyring; secret material is detected
before a public-only store is modified. The preview agent is stopped for that
specific homedir. Identity selection uses full primary fingerprints. Exports
filter ownertrust to the selected identity. Verification reports cryptographic
validity separately from identity trust and rejects expired/revoked signature
status records. File signing, encryption and hashing stream bounded data rather
than loading the entire input into memory. Cache clearing targets the selected
store's agent only.

### SSH and TLS

SSH supports Ed25519, RSA 4096, ECDSA P-384 and native FIDO2 key generation;
imports, passphrase changes, private backups, host fingerprint confirmation,
connection policies, managed agent caching, and user/host SSH certificates.
SSH CA signing uses a bounded validity period, explicit principals, restricted
default extensions and optional source-network/forced-command restrictions.

TLS uses a small immutable profile table and shared native OpenSSL flows. Root
and intermediate CAs, local issuance, self-signed identities, external CSRs and
signing of supplied CSRs use purpose-specific extensions. CA generation and
restore encrypt signing keys. Local signing checks every issuer's remaining
lifetime and verifies the chain, including CA depth/name constraints, before
publication.

| Certificate purpose / consumer | Material and restrictions |
| --- | --- |
| HTTPS, public/internal web apps, reverse proxies and DoT | serverAuth, DNS/IP SANs, algorithm-appropriate key usage |
| mTLS, VPN and EAP-TLS clients | clientAuth; optional identity SANs |
| Combined internal server/client | serverAuth + clientAuth |
| Kernel/module and Authenticode signing | RSA, codeSigning; DER output |
| S/MIME | RSA, emailProtection, signing/encryption usages, EMAIL SAN |
| RFC3161 timestamp authority | Only critical timeStamping EKU |
| Delegated OCSP responder | OCSPSigning and OCSP no-check extension |
| Windows smartcard logon | clientAuth and smartcard-logon OID; UPN SAN |
| Microsoft Entra application | RSA signing identity; public PEM/DER CER export |
| Azure App Service public binding | Conservative RSA recipe, serverAuth, external issuer, complete-chain password-protected PFX |
| Azure App Service Environment private TLS | Private-CA server certificate and complete-chain PFX |
| Azure Application Gateway listener | RSA/EC, complete-chain PFX; deliberately selected valid self-signed identity also supported |
| Azure Key Vault import | RSA/EC; single certificate plus unencrypted PKCS8 key in combined PEM, without metadata |
| Azure P2S VPN client | RSA leaf and CA chain, clientAuth, PFX; public CA DER/base64 export |
| AWS ACM/load balancer | RSA/EC; separate PEM certificate, unencrypted key and chain; key import size check |
| AWS CloudFront | RSA or P-256; separate PEM material |
| Google Cloud load balancer | RSA or P-256/P-384; separate PEM material |
| Experimental ML-DSA X.509 | ML-DSA-44/65/87 only when packaged OpenSSL exposes it; consumer support required |
| Advanced custom leaf purpose | Validated key usages/EKU OIDs, critical EKU, SHA256/384/512, policy OIDs, optional Must Staple, AIA/OCSP/CRL URLs |

Generation offers RSA 3072/4096, P-256/P-384/P-521 and Ed25519/Ed448 where the
chosen purpose permits them. Existing RSA 2048 imports remain usable for RSA
targets. No RSA 1024, obsolete DSA, SHA1 certificate signatures or downloaded PQC
provider is introduced. The issuer's signature digest is SHA256 by default;
custom SHA384/SHA512 and native EdDSA/ML-DSA digests follow the signing key.
Optional organization/location fields support external CA requests. DNS,
wildcard, IP, EMAIL, URI/SPIFFE and UPN SANs are validated; CA DNS/IP name
constraints are optional. Custom extensions accept typed values, not arbitrary
OpenSSL configuration snippets.

PEM/DER, PKCS7/P7B and PKCS12/PFX imports verify the matching key. The external
CSR return flow imports the issued certificate against its existing key.
Supplied issuer chains must include the root; they are ordered by subject/issuer,
checked by OpenSSL, and reject incomplete/ambiguous chains. PKCS12 imports select
the leaf by its key, not bag order. Imported keys must be owned by root or the
configured desktop UID, mode 0600. Inputs are copied into root-owned staging
before native processing. Validity checks cover both notBefore and notAfter.

Exports include PEM, full chain, DER, PEM CRT, DER CER, PKCS7/P7B, encrypted/plain
PKCS8, traditional RSA/EC PEM and password-protected PKCS12/PFX. Normal PFX uses
AES256, SHA256 and 200,000 iterations. Only the explicitly selected App Service
export uses Microsoft's documented 3DES/SHA1 compatibility envelope; certificate
signature digests and other exports retain their defaults. PFX and encrypted
PKCS8 passwords are confirmed, nonempty and passed through an anonymous
descriptor. Unencrypted key exports require explicit confirmation.
Generated encrypted TLS/PQC keys, restored CA keys and PKCS12-imported keys use
AES256 PKCS8 with HMAC-SHA256 PBKDF2 and an explicit 200,000-iteration count.

These recipes describe certificate material. RSA App Service generation is a
conservative implementation choice; Azure is not universally RSA-only. Cloud
service acceptance, DV/OV/EV identity validation, public CA policy, Secure Boot
enrollment and consumer algorithm support remain external decisions. No local
generation can confer public issuer trust or EV status. CRL/OCSP/TSA extensions
and identities do not start a CRL publisher, OCSP responder or timestamp service.

TLS entered from the main menu is authenticated with sudo and runs in a unique
transient system service with a controlling terminal, `KillMode=control-group`,
`RuntimeMaxSec=2h`, a stop timeout, disabled core dumps and private file umask.
Cancellation targets that exact generated unit. Native commands also have
bounded process-group lifetimes and output. Passphrases are not placed in argv,
environment variables, logs or named password files.

ACME supports Let's Encrypt staging/production and custom HTTPS directory URLs;
manual DNS-01, Cloudflare, RFC2136, HTTP-01 webroot and standalone challenges.
RSA 3072/4096 or P-256/P-384 keys and explicit ACME profiles are available.
IP issuance uses HTTP-01 and Let's Encrypt's required `shortlived` profile.
External Account Binding uses a private temporary Certbot configuration, never
secret command-line arguments. Revocation/deletion use Certbot lifecycle
commands and explicit certificate confirmation. DNS credentials
are copied into root-owned private ACME storage for renewal. HTTP-01 automatic
renewal uses root-owned webroots under `/var/www` or `/srv`. Internal ACME server
certificates must be trusted by the installed system. TLS state is root-owned
mode 0700; shared PKI parents stay root-owned and non-writable by the desktop user.

The installer disables the packaged default-state `certbot.timer` and enables
the PKI-specific timer through the existing target service staging helpers.
The staged system timer checks renewal twice daily with one-hour jitter. The
oneshot service has a 30-minute lifetime, private temporary files and a private
Certbot configuration. It does not execute until its renewal-state directory
exists. Manual DNS challenges remain interactive and are not automatically
renewable. Standalone validation requires free, publicly reachable port 80 and
does not stop another web service automatically. Certificate consumers must use
the resulting paths and arrange their
required reloads. Trust installation and Secure Boot enrollment are separate
administrator operations. Local file deletion is not certificate revocation.

PQC generation uses native packaged OpenSSL ML-KEM/ML-DSA support after checking
the installed algorithm list. It installs no provider from source. ML-KEM keys
are not signing keys, and generated PQC material requires consumer support.

### Development tools

Go remains the Debian system package. DevOps provisioning checks actual target
UIDs, rejects root/root HOME, and executes tools through the existing account
runner. The desktop DevOps shell checks USER/HOME against the current account.

| Variable | Account-owned path |
| --- | --- |
| GOPATH | `/pool/build/<account>/go` |
| GOBIN | `/pool/build/<account>/go/bin` |
| GOMODCACHE | `/pool/cache/<account>/go-mod` |
| GOCACHE | `/pool/cache/<account>/go-build` |
| GOENV | `/pool/db/<account>/go/env` |
| GOTMPDIR | `/pool/build/<account>/go/tmp` |

The containing directories are provisioned to the desktop account and devops
group, mode 2770. `GOTOOLCHAIN=local` uses the packaged toolchain; inherited
GOROOT and Go state overrides are removed in the DevOps shell. An installer
inspection checks `go env` under the desktop account and requires a system
GOROOT. It performs no compilation. Root can deliberately invoke system
compilers outside these managed flows; these changes do not claim to constrain
the root account's operating-system authority.

## Changed source paths

- `d-i/forky/hooks/target/usr/local/bin/key-manager`
- `d-i/forky/hooks/target/usr/local/lib/python3.14/dist-packages/key_manager/__init__.py`
- `d-i/forky/hooks/target/usr/local/lib/python3.14/dist-packages/key_manager/core.py`
- `d-i/forky/hooks/target/usr/local/lib/python3.14/dist-packages/key_manager/cli.py`
- `d-i/forky/hooks/target/usr/local/lib/python3.14/dist-packages/key_manager/ssh.py`
- `d-i/forky/hooks/target/usr/local/lib/python3.14/dist-packages/key_manager/gpg.py`
- `d-i/forky/hooks/target/usr/local/lib/python3.14/dist-packages/key_manager/tls.py`
- `d-i/forky/hooks/target/usr/local/lib/python3.14/dist-packages/key_manager/tls_profiles.py`
- `d-i/forky/hooks/target/usr/local/lib/python3.14/dist-packages/key_manager/pqc.py`
- `d-i/forky/hooks/target/etc/key-manager/settings.json.tmpl`
- `d-i/forky/hooks/target/etc/key-manager/certbot.ini`
- `d-i/forky/hooks/target/etc/systemd/system/key-manager-acme-renew.service.tmpl`
- `d-i/forky/hooks/target/etc/systemd/system/key-manager-acme-renew.timer`
- `d-i/forky/hooks/target/etc/tmpfiles.d/10-runtime-storage-roots.conf.tmpl`
- `d-i/forky/hooks/target/etc/skel-desktop/.profile.d/71-devops-de.sh`
- `d-i/forky/classes/class-select/role/desktop.cfg`
- `d-i/forky/scripts/desktop/components/target-assets.sh`
- `d-i/forky/scripts/desktop/components/services.sh`
- `d-i/forky/scripts/common/ssh.sh`
- `d-i/forky/ssh/config`
- `d-i/forky/scripts/late/devops/validation-base.sh`
- `d-i/forky/scripts/late/devops/account-execution.sh`
- `d-i/forky/scripts/late/devops/main-orchestration.sh`
- This validation report.

Generated products: `d-i/forky/payload.tar.gz`, `d-i/forky/payload.manifest` and
`d-i/forky/preseed.cfg`.

## Validation boundary

`AGENTS.override.md` and `docs/test-isolation.md` prohibit host test execution.
No prepared disposable image is available in this session. No test runner,
native crypto command, shell syntax runner, systemd validator, package operation,
host service action or installed management helper was executed. No installed
host's Go layout or failure was inspected or repaired.

Permitted verification consists of reading the source and diffs, AST parsing
without repository imports, comparing installer maps/staging paths and package
changes as data, the reviewed serialization-only `make build`, and inspecting
the resulting archive and hashes as data. These activities do not prove native
OpenSSH/GnuPG/OpenSSL acceptance, Qt/fzf interaction, transient service lifecycle,
ACME issuance/renewal or installed compiler behavior. Executable acceptance
remains to be established in the prepared disposable Forky environment.

Primary references used for native contract review: [GnuPG key management](https://gnupg.org/documentation/manuals/gnupg/OpenPGP-Key-Management.html),
[OpenSSL request options](https://docs.openssl.org/3.6/man1/openssl-req/),
[Certbot workflows](https://eff-certbot.readthedocs.io/en/stable/using.html),
[kernel module signing](https://docs.kernel.org/admin-guide/module-signing.html),
and [Go toolchain selection](https://go.dev/doc/toolchain).
The transient service options were compared with the
[systemd 262 systemd-run reference](https://github.com/systemd/systemd/blob/v262/man/systemd-run.xml).

Platform references: [App Service certificate requirements and PFX format](https://learn.microsoft.com/en-us/azure/app-service/configure-ssl-certificate),
[Application Gateway certificates](https://learn.microsoft.com/en-us/azure/application-gateway/ssl-overview),
[Key Vault import formats](https://learn.microsoft.com/en-us/azure/key-vault/certificates/certificate-scenarios),
[Azure P2S OpenSSL certificates](https://learn.microsoft.com/en-us/azure/vpn-gateway/point-to-site-certificates-linux-openssl),
[AWS ACM import prerequisites](https://docs.aws.amazon.com/acm/latest/userguide/import-certificate-prerequisites.html),
[Google Cloud certificate key types](https://docs.cloud.google.com/load-balancing/docs/ssl-certificates),
[Let's Encrypt IP/shortlived Certbot flow](https://letsencrypt.org/2026/03/11/shorter-certs-certbot.html),
and [OpenSSL X.509 extensions](https://docs.openssl.org/3.6/man5/x509v3_config/).

The public Debian Forky package pages, checked on 2026-10-14, list
[Python 3.14.7-3](https://packages.debian.org/forky/python3),
[OpenSSL 3.6.5-1](https://packages.debian.org/forky/openssl),
[Certbot 5.5.0-3](https://packages.debian.org/forky/certbot), and
[golang-go 2:1.26~1](https://packages.debian.org/forky/golang-go).
These are repository metadata, not installed-host version observations. Native
acceptance must use the actual package versions resolved in the disposable image.

### Checks actually completed

- `python3 -I -B` with standard-library AST parsing: all eight new modules and the
  entrypoint parse; relative module exports, source binding inventory, self-method
  calls and keyword contracts resolve. Repository modules were not imported.
- Source-as-data inspection compared the eight-module staging inventory,
  canonical Qt policy, representative rendered JSON settings, SSH placeholder
  mapping, PKI tmpfiles ownership, ACME paths/timer ownership and Go environment
  variables. Existing `pinentry-qt` is the only selected pinentry package.
- A `git show HEAD:...` / current-source package comparison found exactly four
  direct TLS package additions and no removed packages. Shared development
  package/tool ownership and the unchanged Xwayland paths were reviewed as data.
- Source permissions remain non-executable, matching this checkout. Installed
  CLI and public-module modes are explicitly staged as 0755 and 0644.
- `git diff --check`: completed without whitespace errors.
- `make build PYTHON=python3`: completed after the final key-encryption change;
  output was `built 1768 payload files`. This command performs serialization.
- Standard-library archive/hash inspection: every one of the 1,768 regular 0644
  entries matched its canonical source bytes and manifest SHA256; normalized
  ownership/timestamps, all eight modules, the required assets, private-input
  exclusions and the three bootstrap hash pins were checked as data. No archive
  contents were extracted or executed.

| Generated product | SHA256 |
| --- | --- |
| `payload.tar.gz` | `118e7c667ec1a71b0ef5e6d41603ad5cbef9e018d6b902380e5c231129d76d7b` |
| `payload.manifest` | `1acb5cd52910cc4a72aa2a54ad9582efbf82807b54f3455f9a9f97f2556a12a3` |
| `preseed.cfg` | `4d57236c61516997ad9c6ab8cb0d7c915e5294cd384a4a1e3593b93f2cbe11ca` |

These hashes record the key-manager snapshot before the subsequent MOK repair.
The following MOK snapshot is recorded in the
[APT MOK repair report](apt-mok-prehook-20261014.md); the later
[PKI traversal repair](key-manager-pki-permissions-20261014.md) corrects the
directory-read permission mismatch discovered on the installed system.
The [desktop CrowdSec report](crowdsec-desktop-relevance-20261014.md) records the
current combined snapshot.

No unit, mock, isolated integration or live-host test was run. Independent
sidecar review attempts failed before work because the agent runtime could not
refresh its authentication; their output was not used as review evidence. The
coordinator performed the source and integration review described above.
