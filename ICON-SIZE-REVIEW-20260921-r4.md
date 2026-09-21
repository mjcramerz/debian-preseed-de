# R4: 18 x 18 logical-pixel Waybar icon correction

This revision continues from the complete R3 archive. It supersedes only R3's
24-pixel icon-size requirement. Prior revision reports are retained as historical
records, not current size specifications.

## Delivered configuration

All seven icons use `background-size: 18px 18px, 100% 100%;` in both normal and
hover states, for both internal and external bar layouts:

| Icon | Logical display size |
| --- | --- |
| Applications drawer button | 18 x 18 pixels |
| Wayscriber button | 18 x 18 pixels |
| Foot | 18 x 18 pixels |
| Thunar | 18 x 18 pixels |
| Tuta Mail | 18 x 18 pixels |
| FeatherPad | 18 x 18 pixels |
| Sleek | 18 x 18 pixels |

Explicit pixels ensure the requested size independently of profile font settings.
18 pixels equals 1.2em at a 15-pixel font. Only the icon layer is resized; the
second background layer continues to cover the full button. Click-target sizes,
padding, SVG artwork, Papirus paths, application logos, colors and hover effects
are unchanged. A source SVG's 24-unit viewBox is artwork geometry, not a 24-pixel
display requirement; no artwork conversion, helper or new dependency was added.

The installer verifier now decodes at 18 pixels and rejects incorrect size
rules for each individual icon and state, in skeleton and installed-user CSS.

## Scope and preservation

Only two production sources change: the Waybar CSS template and
`scripts/desktop/verify.sh`. Three related test files are updated. The existing
builder regenerates `payload.tar.gz`, `payload.manifest` and `preseed.cfg` together.
All 3,923 R3 regular files remain present. Exactly two of the 1,405 payload files
change. Atomic-KMS/output management, ZRAM, every host profile, private Xwayland,
menus, lifecycle, power flows and AppArmor policies remain byte-identical to R3.
The helpers removed in R2 remain absent.

## Validation

46 focused tests completed: **36 passed, 10 skipped, 0 failed**. The skips are
for missing Moo dependencies; none was converted to a pass. The checks include
182 profile/selector cases and 28 individual 24-pixel override rejection cases.
40 real GTK3/Cairo drawer-paint cases pass across both layouts, hover states and
1x/2x scale. Large 512-pixel source images remain bounded by 18 logical pixels.
The 2x solid-color interior can be 34 pixels rather than 36 due to edge
antialiasing; this is not an increased logical icon size.

The build/freshness check, unchanged browser artifact check, all 59 preseed files,
four debconf command-value round trips and 581 parser checks over 285 shell files
pass. Payload inventories and every payload hash are checked independently.

The initial batch harness hit its orchestration limit. Two additional, broader
native-menu-hover and repository-integrity module runs did not complete; their
results are not included or reported as passes. This is not a full-suite rerun
or a live Forky installation/Waybar test. Earlier reports describe earlier runs.

## Reproduce the focused checks

From the extracted repository root:

```sh
python3 -B tools/build.py --check
python3 -B tools/build_browser_config.py --check
python3 -B tools/check_preseeds.py
python3 -B tools/check_shells.py
python3 -B -m unittest discover -v -s d-i/forky/tests -p test_drawer_native_icons_20260920.py
python3 -B -m unittest discover -v -s d-i/forky/tests -p test_requested_repairs_20260920.py
python3 -B -m unittest discover -v -s d-i/forky/tests -p test_notifications_followup_20260920.py
```

Publish the complete extracted repository atomically. Keep its rebuilt preseed,
payload manifest and payload archive together. Do not mix R3 and R4 artifacts.
