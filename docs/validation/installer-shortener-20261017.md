# Initial preseed shortener redirects — 2026-10-17

## Reported failure and correction

The installer stopped with `repository redirect leaves its approved authority`
when its selected preseed URL used TinyURL. `source_resolve_seed` fetched that
URL through the same origin-restricted path as repository assets. Consequently,
the shortener's redirect to the actual repository was rejected before contact.

`d-i/forky/scripts/common/source.sh` now gives that initial discovery request an
explicit `seed` scope. Cross-authority redirects are permitted in this scope,
with each next URL validated before contact. The final preseed URL determines
the persisted repository base. Ordinary source, manifest and payload transfers
retain the default `repository` scope and its authority restriction.

TLS verification, HTTPS downgrade rejection, embedded-credential rejection,
the ten-redirect limit, transfer size limits and the single monotonic deadline
across retries and redirects remain in place. No new configuration, packages,
source builds or migration behavior were added.

The bootstrap core is embedded in the generated preseed. The three generated
products were rebuilt together; publishing only `source.sh` cannot repair the
initial embedded fetch path. Publish the complete new installer generation,
including `preseed.cfg`, `payload.manifest` and `payload.tar.gz`, before retrying.
An already running installer using the previous preseed still has its previous
embedded command. No remote publication or installation was performed here.

## Source and fixture scope

The starting checkout was clean on `mcr/main` at
`4a85c047fd3a6e18820dd9b57924eb7705296949`.

Changed paths:

- `README.md`: describes initial discovery and subsequent repository transfers.
- `d-i/forky/scripts/common/source.sh`: explicit initial discovery scope.
- `d-i/forky/tests/test_repository_transport.py`: distinct shortener/repository
  authorities, relative redirects, persisted final base and subsequent transfer.
- `d-i/forky/tests/test_bootstrap_portability.py`: default repository authority
  rejection, unsafe discovery destinations rejected before contact, bounded
  cross-authority loops, and the generated BusyBox bootstrap path.
- `d-i/forky/{preseed.cfg,payload.manifest,payload.tar.gz}`: rebuilt products.
- This validation record.

The fixtures are **unexecuted**. Unsafe-destination cases use an explicit wget
fixture; HTTP cases use loopback endpoints inside the required disposable
environment. Neither proves live TinyURL, TLS or Debian Installer behavior.

## Executed serialization and static inspection

After reviewing the Makefile, `tools/build.py` and `tools/publication.py`:

```sh
/usr/bin/env -i PATH=/usr/bin:/bin LC_ALL=C.UTF-8 /usr/bin/make build 'PYTHON=/usr/bin/python3 -I' SHELL=/bin/sh
```

The command exited zero and serialized 1,805 regular payload members containing
34,634,380 source bytes. Independent standard-library archive/hash inspection
found the complete expected source set, exact source/manifest/archive byte
agreement, normalized member metadata and matching preseed pins. No archive
was extracted. Input fingerprints before and after generation matched.

Static inspection also parsed both modified Python fixtures as AST data,
compared the embedded lifecycle with its unchanged canonical source, and
lexically decoded all four generated `/bin/sh -c` commands to confirm that
each contains the current complete bootstrap core. `git diff --check`
completed successfully. These activities did not execute repository helpers,
test imports, shell snippets or native syntax/policy validators.

The source fingerprint hashes sorted `<file SHA-256>  <relative path>\n`
records under `d-i/forky`, including fixtures and excluding the three generated
products, private input names and interpreter caches.

| Item | SHA-256 |
| --- | --- |
| `source.sh` | `3483f03497725920fc33b14709674c8326b64ce37cac0271a022571b6d0734e2` |
| `d-i/forky` source fingerprint | `9ecb113d73ef30dc97d339e0d455a1f5eee3f78b80ce59492555fffbb4257df0` |
| `test_repository_transport.py` | `ba12858c32e6358000492b08e586b8b61f6f4d22d9d3c425b2196365e9087888` |
| `test_bootstrap_portability.py` | `b6edca085dfc39a8ab80b2a3d87af10e55ff99bc991f6d58408177ee2ce92510` |
| `payload.manifest` | `1972bf5052b1de5deb878081b59bcdb69c05805bf49dca58ff1ff3d26f653252` |
| `payload.tar.gz` | `a5b067f03c5523f41e3d0d532c34ceba719006a582ee0ddb3a585eb6a005eac9` |
| `preseed.cfg` | `5fbc4f0f5b1dd4154ad581f0ccde0f2888f7cf23498e3ef47390c3f1fad9b245` |

## Remaining acceptance

No prepared disposable target environment was available. No test suite, native
shell validator, installer boot, external HTTP request or live host operation
was executed. Run the focused transport and bootstrap fixtures in the approved
environment, followed by an installer-native HTTPS shortener-to-repository
boot using target packaged wget-udeb and BusyBox. Record image/package versions
with those results; static serialization is not native acceptance.

An independent read-only agent review was attempted, but its runtime rejected
the encrypted context before the review started. No agent review is claimed.
