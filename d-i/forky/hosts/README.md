# Host environments

Every deployable profile is directly in `profiles/`; there are no `btrfs/`,
`f2fs/`, `vm/` or `override/` profile subdirectories. Original profile variables
and bytes are preserved and checked against the input-source hashes in
`docs/migration-map.json`.

A named profile class maps to `profiles/<class-name>.env`. The historical logical
name `override-<class-name>` is still accepted by the profile resolver. Fallback
logical profiles map to `profiles/<family>-desktop.env`.

## Composition order

The selected profile is concatenated first. Common environments follow in the
same order as in the input repository:

```text
profiles/<selected>.env
installer/identity.env
installer/runtime.env
installer/layout.env
installer/layout-btrfs.env OR installer/layout-f2fs.env
installer/boot.env
```

The VM family uses the Btrfs layout environment as before. Assignment semantics
and defaults in these files are not rewritten. `installer/account.env` is read
through the separate account configuration path, not silently appended to this
sequence. Server service-specific envs, when applicable, remain separate from
base account and profile composition.

Select valid original class combinations; profile `RequiresClasses`, rejected
classes and supported disk families are checked before proceeding. After any
profile/env change, run `python3 -B tools/build.py` from the repository root and
publish the complete result. Treat account and enrollment configuration as
sensitive even though a public Git repository makes its contents public.
