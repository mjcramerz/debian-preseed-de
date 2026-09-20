# Managed desktop fonts

This is the current font policy. The font section in the 14 September 2026
desktop integration incident report is retained as historical evidence and
does not describe the current two-tree publication layout.

All thirteen profiles pin MicrosoftAptosFonts and MicrosoftLocalFonts to
`microsoft-fonts-v0.0.1`; the supplied SHA-256 values are unchanged. The three
terminal archives remain on `terminal-fonts-v0.0.1`. Strict logical-name/URL
basename matching is retained; `microsoft-fonts` is no longer an archive name.

The trusted installer has two closed publication classes:

| Archives | Fixed XDG data tree |
|---|---|
| FiraCode, NerdFontsSymbolsOnly, ProFont | `icons/terminal-fonts` |
| MicrosoftAptosFonts, MicrosoftLocalFonts | `fonts/microsoft-fonts` |

Each has `releases/<full-policy-generation>/` and a relative `current` link.
The root cache continues to verify all five archives as one content/policy
generation. Both user-visible generations are prepared, sealed and checked
against root-cache content before either pointer is changed. One existing
installer lock covers both; errors before/after the second link rename restore
the old pointers. This is not a claim of global cross-directory atomicity on
power loss. Unreferenced historical generations are not blindly deleted.

Download SHA-256 checks, exact names/HTTPS policy, archive limits, member-type
and traversal controls, root-cache sealing, no-follow checks, privilege dropping
and safe atomic generation publication remain in `fonts-install.py`. Neither an
archive nor a profile can choose a publication path or group. Publication and
font-cache execution for a user run after permanently dropping to that account.

Fontconfig is owned only by the managed desktop skeleton:
`60-labwc-terminal-fonts.conf` registers `icons/terminal-fonts/current`, and
`61-microsoft-fonts.conf` registers `fonts/microsoft-fonts/current`. Both source
files are installed root:root 0644 in `/etc/skel-desktop`; the normal home-copy
pipeline gives the user-owned copies its established private 0600 mode. Python
does not create, replace or repair these configuration files.

The explicit fc-cache invocation covers both current trees without a broad home
scan. Verification checks exact archive membership, both contained current links,
matching full-policy identity, content hashes against the trusted cache,
readable fonts, ownership, safe modes, both static XML files and cache markers.
