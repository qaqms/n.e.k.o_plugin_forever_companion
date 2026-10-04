# Isolated Hosted UI QA

`hosted_ui_harness.mjs` renders the real plugin panel using the host's current
Hosted TSX linker and UI Kit. It does not replace the panel with React or a
mock component library. `hosted_ui_fixture.mjs` provides deterministic backend
responses and test-only image pixels.

The harness only reads the host checkout. It never installs dependencies into
the host, calls its backend, writes its plugin directory, or touches a Steam
installation. These development tools are excluded from `.neko-plugin` builds.
They are not an alternative to the final Steam import smoke test.

## Dependencies

Use Node.js with `playwright`, `sucrase`, and optional `typescript` dependencies
installed outside both the host and the plugin. The harness searches:

1. `--deps <node_modules>` or `NEKO_UI_TOOL_DEPS`.
2. `%TEMP%\neko-companion-ui-tooling\node_modules`.
3. The existing bundled Codex Node dependency directory on this development PC.

For example, isolated tooling can be installed with PowerShell:

```powershell
npm install --prefix "$env:TEMP\neko-companion-ui-tooling" --no-audit --no-fund sucrase typescript playwright
```

The harness launches Edge headless when installed. Use `--browser-executable`
or `NEKO_UI_BROWSER` to select another Chromium-compatible executable. It uses
a fresh Playwright context and no personal browser profile or login session.

## Runs

Run commands from the plugin root:

```powershell
# 192 screens: four widths, two themes, three wallpapers, eight tabs.
node tools\hosted_ui_harness.mjs --full --typecheck --out "$env:TEMP\neko-companion-ui-full"

# Interaction and reading/empty-state checks without the main screen matrix.
node tools\hosted_ui_harness.mjs --interactions-only --gallery --compact --details --widths 1280,390 --out "$env:TEMP\neko-companion-ui-interactions"

# Wallpaper palette linking, fallback, caching, and narrow swatch checks only.
node tools\hosted_ui_harness.mjs --theme-only --out "$env:TEMP\neko-companion-ui-theme"

# Eight-locale guide, real introductions, diary states and confirmations.
node tools\hosted_ui_harness.mjs --copy-only --out "$env:TEMP\neko-companion-ui-copy"

# Animated principle demos, eight-locale comparison matrix and lifecycle checks.
node tools\hosted_ui_harness.mjs --demo-only --typecheck --out "$env:TEMP\neko-companion-ui-demo"

# Motion/control checks without the comparison screenshot matrix.
node tools\hosted_ui_harness.mjs --demo-only --demo-dynamic-only --out "$env:TEMP\neko-companion-ui-demo-motion"

# Complete delivery run, including wallpaper theme regressions.
node tools\hosted_ui_harness.mjs --full --typecheck --interactions --gallery --compact --details --theme --calendar-diagnostics --copy --out "$env:TEMP\neko-companion-ui-delivery"

# Typecheck only, using a temporary copy of the host's supported scaffold.
node tools\hosted_ui_harness.mjs --typecheck --typecheck-only --out "$env:TEMP\neko-companion-ui-types"

# Read-only tooltip overflow diagnosis in two widths and two locales.
node tools\hosted_ui_harness.mjs --diagnostics-only --calendar-diagnostics --out "$env:TEMP\neko-companion-ui-calendar"
```

`--plugin-root` and `--host-root` override the sibling-checkout defaults.
Screenshot selection supports `--widths`, `--themes`, `--wallpapers`,
`--pages`, and `--locale`. Pages are `overview`, `calendar`, `diary`, `moment`,
`features`, `cycle`, `mood`, and `settings`. Wallpaper fixtures are `none`,
`bright`, and `dark`.

`--interactions` adds behavioral checks to a screen matrix. `--gallery` adds
gallery keyboard, preview/applied, upload, delete, zero-value styling, unified
save, delayed-image, and broken/failed-decode image tests. `--compact` adds
390x600 save-button and review-seal label-fit checks in all eight locales,
plus both books' footer/savebar non-overlap and pointer-hit checks across
1280/390 widths, 900/600 heights, and
light/dark themes. It also checks clearance and footer pointer hits after the
real five-second refresh and tab roundtrip, including observer cleanup on a
tab without a save bar. `--details` adds journal/review shelf and reading
screens, capability introduction screens, and empty diary screens.
`--compact-only` runs just the compact/footer checks without the main matrix
or general interaction suite.
`--theme` adds 34 theme checks. `--theme-only` runs these checks
without the main matrix. The suite uses olive/blue, rose/blue, gray, and white
pixel fixtures to verify linked primary/secondary CSS colors, default-blue
fallback, atomic image/theme transitions, cache reuse across polling and
filter edits, unchanged appearance-save fields, and deleted/reused image
request identity. It also measures colored-control contrast and keyboard
focus with zero mask/card opacity and checks swatch fit in all eight locales.
Four additional no-wallpaper checks measure actual composited text contrast
at rest and on hover, keyboard focus visibility/contrast, and the separation
of soft fill colors from readable ink in both themes and two widths.
`--calendar-diagnostics` measures calendar overflow with and without tooltip
boxes in the isolated DOM and captures the actual hovered tooltip.
`--copy` checks all six onboarding steps and all ten real introductions in
eight locales, two widths and both themes. It also checks diary empty states,
optional writing invitations, generated-review states and results, dependency
interpolation, master-switch confirmation/cancellation, destructive-operation
cancellation, and skipping the guide. `--copy-only` skips the base matrix;
`--copy-locales zh-CN,en` limits just this suite during development.
`--demo` adds the principle demo suite; `--demo-only` skips the base matrix.
The default demo matrix covers ten real capabilities, both comparison modes,
eight locales, two widths and both themes. Reduced-motion/manual-final-step
screenshots test reading and fit, not animation. Separate no-preference checks
verify visual motion, pause/resume/replay, steps, independent comparison modes,
journal choices, the privacy route, refresh persistence, runtime motion
preferences, real offscreen intersection and unmount cancellation.
`--demo-locales zh-CN,en` limits the screenshot locales; `--demo-static-only`
and `--demo-dynamic-only` select the respective phase. The explicitly named
synthetic child-document visibility test exercises event handling only; it
does not claim a real operating-system background transition.

Introduction fixtures come from the real `core/capabilities.py` and
`core/intros.py` declarations, loaded with Python's `runpy`, not placeholder
prose. The harness uses the plugin's development Python when present, or
`python` on PATH. This reads pure data modules only; it does not import or
start the plugin backend.

## Results And Limits

Every completed run writes `report.json` alongside its PNG screenshots. The
report includes the real source hash, runtime import graph and byte budget,
layout diagnostics, browser/runtime errors, interaction results, and optional
host-supported typecheck output. Failed interaction, typecheck, runtime, or
layout checks return a nonzero exit code. Content/document horizontal overflow
and clipped text are part of the layout gate.

The fixture uses the real sandboxed iframe and `postMessage` API transport, but
its backend responses are intentionally synthetic. Host file permissions,
Steam startup, persisted user settings, real LLM behavior, and production
image upload validation require separate integration or user smoke tests.
Layout diagnostics can flag an intentionally scrollable or off-screen tooltip;
review screenshots before classifying these as visible regressions.

## 1.3.5 Delivery Verification

The frozen delivery run completed on 2026-10-03 with 216 reported base/detail
screenshots, 85 passing interaction checks, four passing calendar diagnostics,
and a passing host-supported typecheck. Additional interaction/theme captures
bring the actual PNG count to 281. No render or interaction failures were
reported. The import graph contains 25 dependencies / 367,967 bytes, below
the host limits of 32 dependency files / 512 KiB.

UI source hash:
`c55405b35d5960a347c12e5a15ab2063f64f148a851a772f481993e9f7868efc`.
The plugin's separate Python regression suite passed all 522 tests.
These are isolated local checks, not a claim of Steam import or real-user-data
verification.

## 1.3.6 Delivery Verification

The 2026-10-03 delivery run used the new wallpaper defaults: blur 0, mask 0.4,
brightness/saturation/contrast 100, glass 0, card opacity 0, and text strength
100. It explicitly checked all eight slider values and the computed mask,
glass, and surface variables. The no-wallpaper checks verified that neutral
card backgrounds remain enabled while the theme stays blue. The gallery
roundtrip first saved nonzero glass/opacity, then verified returning both to
zero, so an already-zero default cannot make the save check vacuous.

The run passed 216 reported screenshots, 85 interaction checks, four calendar
diagnostics, and the host-supported typecheck, with 281 actual PNG captures.
The Python suite passed 527 tests. Dependencies total 25 files / 367,952 bytes.
UI source hash:
`6e8161bc78af2cfb21ca7133bbfe0df2bf7212b8b6cf4967208b68d2e541b482`.
These checks do not overwrite saved user appearance settings or replace a
Steam import smoke test.

## 1.3.7 Delivery Verification

The frozen 2026-10-03 delivery run passed 216 reported base/detail screenshots,
89 interaction checks, four calendar diagnostics, and the host-supported
typecheck, with 289 actual PNG captures. No render or interaction failures were
reported. All four new no-wallpaper light/dark and wide/narrow checks passed:
ordinary and hovered text contrast is at least 4.5, and keyboard focus contrast
is at least 3. The soft control fills remain separate from readable ink.

The existing wallpaper extraction, fallback, zero-opacity contrast, cache,
image-race, gallery, save, footer, and eight-locale checks remain passing.
Wallpaper defaults and extraction logic are unchanged from 1.3.6.
The Python suite passed all 530 tests. Dependencies total 25 files /
370,416 bytes, below the 32-file / 512-KiB limits.
UI source hash:
`8d09e385b03ade067006fe43dca0276643bb1552923c3a3c120c8cefec75665c`.

The official 1.3.7 package inspection verified the payload hash and ZIP CRC.
All 69 packaged source files match the plugin checkout byte-for-byte,
including 28 UI files and eight locales. No database, user-data directory,
test, tool, dependency directory, or cache is packaged. The host checkout is
clean, the isolated test processes have exited, and the previous 1.3.6 package
is unchanged. These isolated checks do not claim Steam import or production
user-data verification.

## Final 1.3.3 Release Number

At the author's request, the final public version is 1.3.3. The 1.3.4 through
1.3.7 headings above identify local development and import-package milestones,
not GitHub releases. Version metadata and the README were normalized without
changing UI source. The final pre-release run passed all 530 Python tests,
the CI-equivalent Ruff check, the official plugin check, the 26-module link
check, and the isolated host-supported typecheck. The frozen UI source hash
and full browser regression results above remain applicable.

## Unreleased Clear-Copy Verification (1.3.3)

The final 2026-10-03 run passed 528 reported screenshots, 201 interaction
checks, four calendar diagnostics, and the host-supported typecheck. Including
interaction captures, the output contains 601 PNG files. Check, render, and
layout failures are all zero. Content/document horizontal overflow and clipped
text are included in the layout gate.

The copy suite covers all six guide steps and ten real capability introductions
in eight locales, both themes and 1280/390 widths. It also covers diary empty
states, optional journal invitations, generated-review progress/results,
dependency interpolation, master-switch and destructive-operation cancellation,
and skipping onboarding. Narrow feature layouts were manually inspected after
fixing the grid's minimum width for longer Spanish, Portuguese and Russian text.
Wallpaper, gallery, compact reading/save bars, and existing theme checks remain
passing.

Dependencies total 25 files / 368,647 bytes, below the 32-file / 512-KiB limits.
UI source hash:
`39b6b7bbb5156ccef7b12a34449fba7572a53371e40d2e893a16ab9a084fbca4`.

The Python suite passed all 557 tests, including 27 copy-contract cases. Ruff,
the official plugin check, and the 26-module link check passed. The official
check's uncommitted-worktree warning is expected for this local test delivery.

Package: `forever_companion_1.3.3_clear_copy.neko-plugin`, 583,895 bytes /
72 entries. Official payload hash and ZIP CRC verification passed. All 67
packaged source files match the checkout byte-for-byte: 28 UI files, 23 Python
files, eight locales, and the remaining manifest/configuration/documentation
files. No user data, tests, tools, dependencies, or caches are included.
SHA-256:
`87ec474bc08472646407f2769804c57e79aee2b7f7e87067793623ad72e6edce`.

Runtime Python, manifest settings, permissions, tool descriptions and metadata
were separately checked for unchanged behavior. Guide version remains 2, so
existing users are not forced through onboarding again. The host checkout and
the original public 1.3.3 package remain unchanged. These are local fixture and
package checks, not Steam import, persisted-data, or real-model verification;
no commit, push, release, or market notification was performed.

## 1.3.4 Release Promotion

The author approved the clear-copy delivery for public version 1.3.4.
Only version metadata, the README's current-version note, and release records
change during promotion. The UI source is unchanged, so the frozen 528-screen /
201-interaction browser results and source hash above remain applicable.
The 1.3.3 clear-copy package remains a historical local test artifact and is not
overwritten; the public 1.3.4 package is rebuilt from the release commit.

The repository's reusable GitHub release workflow validates, tests, builds and
publishes a GitHub Release. Its market-release check enforces repository/tag
conventions and writes evidence only; no plugin-market registration, submission,
or notification endpoint is invoked.

After the version change, all 557 Python tests passed again, along with the
CI-equivalent pinned Ruff check, official strict plugin check, isolated
host-supported typecheck and 26-module link check. The UI source hash remains
`39b6b7bbb5156ccef7b12a34449fba7572a53371e40d2e893a16ab9a084fbca4`.

## Public 1.3.6 Feature-Introduction Release

The author approved the 2026-10-04 feature-introduction redesign for public
version 1.3.6. The older 1.3.6 wallpaper heading above describes a local
development milestone, not this public release. Promotion changes version
metadata and release documentation only; the accepted UI and copy stay frozen.

The completed isolated browser runs passed 508 screenshots and 1,257 checks
across eight locales, ten capability introductions, light/dark themes, wide and
narrow viewports, intermediate breakpoints, and short windows. There were no
render, clipping, overlap, horizontal-overflow, or interaction failures.
Demo animation and controls, privacy/journal choices, refresh preservation,
unmount cleanup, and absence of business mutations were also verified.

After the version change, all 586 Python tests passed again, along with the
CI-equivalent pinned Ruff check, official strict plugin check, isolated
host-supported typecheck, and 29-module link check. The frozen UI source hash is
`863553c29f42848c9aaa1fa3e250e41b5d4ad1d403b108680d2467f2698a17e2`.
The runtime graph contains 28 dependencies / 452,543 bytes, below the host's
32-file / 512-KiB limits. These fixture checks do not claim a Steam import or a
production-data/real-model test. Only the plugin repository is changed.

The reusable verify/release workflows and host checkout are pinned to the
audited host commit `9cdc4dfce7ae3203673ad4846a02ae1c7fbe8ad0`.
Their sync/check/build path does not call the CLI publish/market-notify path;
the market-release flag validates repository, tag and version conventions and
writes evidence only.

The prior `forever_companion_1.3.5_feature_intro.neko-plugin` remains an unchanged
local test artifact. A new 1.3.6 package is built from the release commit.
Publication is limited to GitHub; plugin-market submission and notification
remain the author's responsibility.
