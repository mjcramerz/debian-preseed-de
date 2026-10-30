# Managed appearance inputs

Edit `base.env`, `apps.env` and `office.env` before building the installer. These
three files are the sole default-value catalogs for managed appearance. The
adjacent schema defines ownership and native value types; it does not duplicate
colors or provide fallback values. The loader validates the complete catalogs
before rendering either templates or ordinary managed assets.

## Names and ownership

Use uppercase words separated by underscores:

```text
COMPONENT[_VARIANT]_ELEMENT[_STATE]_PROPERTY
```

An element can include a parent control and its child, such as
`WAYBAR_BUTTON_AUDIO_MICROPHONE_MUTED_ICON_COLOR`. Omit an inapplicable variant,
element or state; do not insert placeholders or duplicate the component name.
Use the actual consumer's meaning, not an automatic transcription of its file
path. In particular:

| Property or qualifier | Meaning |
| --- | --- |
| `BACKGROUND_COLOR`, `TEXT_COLOR`, `BORDER_COLOR`, `OUTLINE_COLOR` | A distinct native visual property; text and surface colors are not interchangeable. |
| `NORMAL`, `HOVER`, `SELECTED`, `DISABLED`, `ACTIVE` | The consumer's actual state. Not every component supports every state. |
| `ICON_NAME` | An icon-theme lookup name, not a filename. |
| `ICON_PATH` | A configured image path, using the schema's existing allowed path forms. |
| `ICON_GLYPH` | A font-rendered icon character, not an icon-theme lookup. |
| `ICON_COLOR` | The foreground of an independently recolorable glyph or supported symbolic icon. |
| `LAUNCHER_ICON_NAME` | The `Icon=` value of a desktop application launcher, including a rendered `.desktop.tmpl`. |
| `FONT_FAMILY` | A font selection; profile-dependent font sizes remain in profiles. |
| `STYLE` | A native composite style, such as a Taskwarrior or Starship style. |
| `BORDER_COLORS` | A native ordered list of colors, not one scalar color. |
| `SHADE_00`, `LEVEL_1`, `25_MINUTES`, `40_PERCENT` | A meaningful native tonal position, nesting level, duration or percentage, rather than an unexplained slot. |

Examples include `SHOW_DESKTOP_LAUNCHER_ICON_NAME`,
`TUTANOTA_LAUNCHER_ICON_NAME`, `WAYPAPER_LAUNCHER_ICON_NAME`,
`LABWC_TASKVIEW_ACTIVE_BORDER_COLOR` and
`FUZZEL_MENU_SELECTED_TEXT_COLOR`. A main-menu category named "Remote Desktop"
is still a category, not an application launcher; its name is not rewritten to
"Remote Launcher".

`base.env` contains desktop controls, compositor and taskview appearance,
background selections, launchers, terminals and desktop tools. `apps.env`
contains the managed general-application settings. `office.env` contains the
managed Obsidian, Sleek, Zathura, Gnumeric and FocusWriter settings. Section
headings group controls within each component. Ownership is unchanged by the
23 September naming revision.

## ANSI terminal palettes

Kitty, Foot and the VSCode terminal use named ANSI roles. `NORMAL` and `BRIGHT`
identify the palette bank; the hue names identify conventional roles, not a
restriction on a user's replacement color.

| Role | Kitty normal / bright key | Foot normal / bright key |
| --- | --- | --- |
| `BLACK` | `color0` / `color8` | `regular0` / `bright0` |
| `RED` | `color1` / `color9` | `regular1` / `bright1` |
| `GREEN` | `color2` / `color10` | `regular2` / `bright2` |
| `YELLOW` | `color3` / `color11` | `regular3` / `bright3` |
| `BLUE` | `color4` / `color12` | `regular4` / `bright4` |
| `MAGENTA` | `color5` / `color13` | `regular5` / `bright5` |
| `CYAN` | `color6` / `color14` | `regular6` / `bright6` |
| `WHITE` | `color7` / `color15` | `regular7` / `bright7` |

For example, `KITTY_ANSI_NORMAL_RED_COLOR` feeds Kitty's `color1`, and
`KITTY_ANSI_BRIGHT_RED_COLOR` feeds `color9`. Foot uses the corresponding
`FOOT_DARK_ANSI_NORMAL_RED_COLOR` and `FOOT_DARK_ANSI_BRIGHT_RED_COLOR` in its
existing dark palette. VSCode uses `VSCODE_TERMINAL_ANSI_NORMAL_RED_COLOR` and
`VSCODE_TERMINAL_ANSI_BRIGHT_RED_COLOR` for its native terminal ANSI settings.
The native option names themselves are not renamed. The third column in
`theme-schema.tsv` identifies the grammar accepted by the consumer parser; it
is used during installation validation and is not copied into the installed
desktop. The installed Appearance app instead uses its captured native field
registry and the mappings recorded for each rendered file.

Kitty and VS Code use their native hash color forms, while Foot retains its
native `rrggbb` values without a hash. Fuzzel uses bare `rrggbbaa` values,
Xournal++ toolbar colors use eight bare hexadecimal digits, and Crystal Dock
and FocusWriter use Qt color values. Zathura and Recoll use their CSS/GDK
color forms, and fzf uses its ANSI or `#rrggbb` color form. The default values,
palette order, opacity and selected application themes are unchanged.

Obsidian's `NEUTRAL_PALETTE_SHADE_00` through `SHADE_100` names deliberately
retain the native shared tonal scale. These shades can serve multiple widgets;
assigning each an invented widget role would be misleading. Separate native
component backgrounds, borders and text colors have their own descriptive names.
VSCode bracket and indentation guide levels likewise retain explicit `LEVEL_n`
qualifiers. Satty swatches retain their native list order, with names describing
the original swatch colors. Wayscriber boards and presets use their actual IDs
and tool names rather than anonymous slots.

## Fuzzel sizing belongs to the selected profile

Each desktop profile explicitly defines INTERNAL, EXTERNAL and DEFAULT geometry.
`FUZZEL_<CLASS>_*` owns font size, horizontal/vertical/inner padding, line height,
border width and border radius. `FUZZEL_LAUNCHER_<CLASS>_{WIDTH,LINES}` and
`FUZZEL_MENU_<CLASS>_{WIDTH,LINES}` own mode dimensions. Management menus reuse
menu geometry. DEFAULT is used only when no actual output is known.

`labwc-fuzzel` selects explicit `--output`, then `WAYBAR_OUTPUT_NAME`. Named
Waybar bars pass their INTERNAL or EXTERNAL class through the click service
because Waybar does not provide `WAYBAR_OUTPUT_NAME` to click handlers. Without
either an output or a bar class, the wrapper uses DEFAULT. A class hint selects
geometry without inventing an output name. All geometry is passed to the native binary;
the four configuration files share nested imports rather than monitor copies.
Fonts and line heights use points with `dpi-aware=yes`.

Waybar uses one config, two named bars and one stylesheet. Bar geometry is
independently scoped. Native GTK menus/tooltips are detached popup windows,
so paired popup values must match; validation rejects unsupported divergence.
The renderer binds the validated pair to `LABWC_WAYBAR_SHARED_*` placeholders
for popup assets, while `LABWC_WAYBAR_INTERNAL_*` and
`LABWC_WAYBAR_EXTERNAL_*` remain the profile inputs. The stylesheet does not
pretend popup widgets have a bar ancestor.

## Values and installation

Keep the literal `NAME="value"` format, without shell interpolation, command
substitution, inline comments, or multiline values. Follow each variable's
existing native format and schema grammar: not every application accepts the same
hex notation, alpha format, style string or boolean spelling. Validation fails
on unknown, duplicate, missing, misplaced or invalid values before publishing a
partial map. A name accepted by the publishing naming lint must still pass this
independent installation-time value validation.

The schema grammar identifiers used by the current native consumers are:

| Grammar | Native consumer | Accepted value forms |
| --- | --- | --- |
| `gtk3-css-color` | GTK3 CSS and GDK/Waybar styles | names, `transparent`, `currentColor`, `#rgb`, `#rrggbb`, `#rrrgggbbb`, `#rrrrggggbbbb`, and `rgb/rgba/hsl/hsla` functions |
| `gtk4-css-color` | GTK4 CSS, including Waycal | the GTK3 forms plus `#rgba`, `#rrggbbaa`, `#rrrrggggbbbbaaaa`, and GTK4 color functions |
| `pango-color` | Waybar JSON Pango markup | names and the four RGB hex widths accepted by Pango |
| `qt-color` | Qt QColor consumers such as Crystal Dock and FocusWriter | names, `transparent`, `#rgb`, `#rrggbb`, `#aarrggbb`, `#rrrgggbbb`, and `#rrrrggggbbbb` |
| `mako-color` / `mako-progress` | Mako notification config | `#rrggbb` or `#rrggbbaa`; progress values use the `over ` prefix |
| `fuzzel-rgba` | Fuzzel | bare `rrggbbaa` (no leading `#`) |
| `foot-rgb` | Foot | bare `rrggbb` (alpha is a separate Foot option) |
| `kitty-color` | Kitty | Kitty hash, `rgb:`, `rgbi:`, name, and optional `@alpha` forms |
| `vscode-color` | VS Code `workbench.colorCustomizations` | `#rgb`, `#rgba`, `#rrggbb`, `#rrggbbaa`, or the supported `default` sentinel |
| `fzf-color` | fzf `--color` values | ANSI names/numbers, `#rrggbb`, and optional foreground attributes |
| `zsh-color` | zsh prompts and zsh syntax highlighting | named colors, indexes `0`–`255`, or six-digit `#rrggbb` truecolor |
| `zathura-color` / `css-color` | Zathura/GDK and CSS based applications | HTML/CSS names and hex forms plus `rgb/rgba` (and CSS functions where the consumer supports them) |
| `xournalpp-color` | Xournal++ page-template colors | `#rrggbb` or `#rrggbbaa` |
| `xournalpp-hex` | Xournal++ toolbar color attributes | exactly eight bare hexadecimal digits |

These identifiers describe the staged native consumer grammar. They are used
to reject invalid installer inputs before rendering; they are not installed as
a theme database and the installed Appearance app does not read this file.

Wallpaper variables select repository-relative sources beginning with
`hooks/target/usr/share/backgrounds/`. Installation derives the corresponding
absolute target path by removing `hooks/target`; it does not execute the value
or treat it as shell syntax. The archive selection retains its bounded,
traversal-safe extraction. GTK and Qt selections continue through their native
settings rather than the `GTK_THEME` debugging override.

From the repository root, run:

```sh
make build
make check
make test
```

`tools/check_themes.py` also checks naming, reference coverage and the complete
profile geometry contract. The production AWK validator remains authoritative
for values. The naming tests check native palette mappings and mutate every
ANSI entry independently; the installation tests render all ten profiles.

Use the canonical identifiers in the adjacent theme schema; old identifiers
are rejected rather than silently ignored. Publish a rebuilt repository as one
snapshot: its payload, manifest and preseed checksum pins must agree.


## Independent icon colors

Icon glyphs and their foregrounds are separate inputs. For example,
`WAYBAR_BUTTON_SCREENSHOT_IDLE_ICON_GLYPH` and
`WAYBAR_BUTTON_SCREENSHOT_IDLE_ICON_COLOR` configure the idle screenshot icon;
its recording state has the corresponding `RECORDING` pair. Mixed labels keep
their text outside the icon's foreground span. Native dropdown/submenu icon
palettes remain distinct from their label palettes.

The 56 management fzf glyph colors default to `inherit`, which preserves native
normal, matching and selected-row colors. A literal `#rrggbb` overrides only
the associated glyph. No other ANSI text or fzf action is accepted as a color.

Theme artwork and app-supplied pixels are not universally recolorable. In
particular, Waybar taskbar images do not support a CSS foreground tint. The
tray foreground applies only to its native symbolic loader. Color emoji may
retain intrinsic colors; glyph selection remains explicit. Native report
indicators and spacing separators retain their shared native text styles.

The adjacent schemas define the supported values and state coverage. The
regression fixtures under `../../tests/fixtures/` retain the input data needed
to verify native palette mappings without shipping archived reports.
