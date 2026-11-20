# The two DWC lines of WorkshopService

The service page is built for DuetWebControl 3.6 (Vue 2) and 3.7 (Vue 3) at the same time, from one repository. The Python backend (`dsf/`),
the bridge, the kiosk scripts, the tests and the docs exist once and ship identically in both lines. Only the page has two trees.
The TallerPlugins plugins use the same idea (`docs/DWC-LINES.md` of that repository).

| | DWC 3.6 | DWC 3.7 |
|---|---|---|
| Page sources | `dwc36/` (Vue 2, Vuetify 2, Vuex, webpack) = master's `dwc-src` | `dwc-src/` (Vue 3, Vuetify 4, Pinia, Vite, vue-i18n 11) |
| DWC clone that compiles it | `~/Projects/dwc-src` (`TALLER_DWC_SRC_36`) | `~/Projects/dwc-src-37` (`TALLER_DWC_SRC`) |
| Builder | `tools/build_36.py` | `tools/build_37.py` |
| Line zip (builder output) | `dist/WorkshopService-<ver>-dwc3.6.zip` | `dist/WorkshopService-<ver>-dwc3.7.zip` |
| Release zip | `dist/release/WorkshopService-<ver>-dwc3.6.zip` | `dist/release/WorkshopService-<ver>-dwc3.7.zip` |
| `dwcVersion` / `sbcDsfVersion` | `3.6` | `3.7` |
| Catalogs | `dwc36/i18n/*.json` (plain) | `dwc-src/i18n/*.json` (staged with `|`, `@`, `<` escaped) |

Both catalogs are the same bytes: `dsf/published_texts.py` writes `dwc-src/i18n`, and `dwc36/i18n` is a copy (the test fails if they differ). After
`python dsf/published_texts.py` or any text edit, copy `dwc-src/i18n/*.json` to `dwc36/i18n/`.

## The zip you install

TWO zips, one per DWC line, `dist/release/WorkshopService-<ver>-dwc3.6.zip` and `-dwc3.7.zip` (+ `SHA256SUMS.txt`). There is no universal zip any
more: a `dwcVersion` of "3" is accepted by every 3.x DWC, including unsupported ones (3.5, 3.8, later). Both DWC and DSF compare `dwcVersion` /
`sbcDsfVersion` by prefix of the dot-split version, so a manifest with `3.6` is installed by 3.6.x only and one with `3.7` by 3.7.x only; the other
DWC refuses it ("requires incompatible DWC version") and DSF refuses a mismatching `sbcDsfVersion`. The other plugins depend on WorkshopService
by id (`dwcDependencies`), and the service exists in both lines, so the dependency resolves in each.

| Your DWC / DSF | Install |
|---|---|
| 3.6.x | `WorkshopService-<ver>-dwc3.6.zip` |
| 3.7.x | `WorkshopService-<ver>-dwc3.7.zip` |
| anything else | not supported, DWC refuses both |

    python tools/build_release.py             # 3.6 build, 3.7 build, finalize, check, SHA256SUMS (about 10 minutes, mostly the 3.6 webpack build)
    python tools/build_release.py --reuse     # reuse the two line zips already in dist/ (finalize, check, sums)
    python tools/build_release.py --check     # only check dist/release

Steps it runs (each can be run alone): `tools/build_36.py`, `tools/build_37.py` (line zips in `dist/`), then `release_zips.finalize_zip` for each
line (the manifest values of the line, no source maps, a `.gz` next to every `.js`/`.css` of 32 KB or more, fixed timestamps) into `dist/release/`,
the checks of `release_zips.check_zip` and of `build_37.check_release`, and `SHA256SUMS.txt`. `tools/release_zips.py` is a copy of the file of the
same name in TallerPlugins (`tests/strict-zips.test.js` compares them); `tools/build_universal.py` and the merger are deprecated, not for release,
and no longer accept the line zips (their `sbcDsfVersion` differs).

How the manifest values are set: the source `plugin.json` keeps `dwcVersion` "3" and `sbcDsfVersion` "3" as neutral values and is never read as
the release value. `build_36.stage()` and `build_37.stage()` call `release_zips.line_manifest()`, which writes `3.6` / `3.7` in both fields;
`finalize_zip` does it again on the finished zip. Both stages also add `dwc-src/line-guard.js` and make the page's `index.js` import it first:
the run-time guard (the 3.6 page refuses to start on a page that has `window.DWC`, the 3.7 page unless `window.DWC.version` is 3.7.x; red
warning `data-workshop-line-guard` and a console error).

What the builders guarantee (learned from building the 3.6 zip by hand):

* Only git-tracked files listed in `plugin.json` `dsfFiles` are staged, so no tests, fixtures, golden files, `config.json` or secrets get in. The
  3.6 packager (`scripts/build-plugin.js`) would otherwise copy the whole `dsf/` folder (149 test and fixture files) and ship `config.json`.
  Because of "git-tracked", `git add` the changes (new files too) before building.
* The `dsfFiles` of both manifests is the same list in the same order (Windows directory order, names compared upper-case).
* The 3.6 line zip is rewritten after the build: `dwcFiles` filled with the js/css, only `plugin.json`, `dwc/` and `dsf/`.
* Each builder holds `<clone>.lock` (mkdir/rmdir), waits when it exists and never removes a lock it did not create.
* Build both lines from the same commit.

## Where fixes go

* Backend, bridge, kiosk, tests, docs, `plugin.json`: once.
* Page: in `dwc36` (3.6, the line that is installed and released). `dwc-src` (3.7) is paused and frozen: nothing is ported to it and nothing in it
  changes, apart from what the tools regenerate (`family.css`, the area `svc` of its catalogs).
* Version: `plugin.json` only (one number for both lines).

## Tests

`node tests/lines-frozen.test.js` (decision P-8 of the page redesign; it replaced `tests/lines-divergence.test.js` and `tools/lines-allowlist.json`, which
recorded every difference between the two trees and had to be edited for every new file or key of the 3.6 page) checks three things:

* `dwc-src/` is frozen: the same files with the same content as `tests/golden/dwc-src-frozen.json`. Left out of the hash on purpose, because tools
  still write them: `family.css` and the area `svc` of `i18n/es.json` / `en.json` (`python dsf/published_texts.py`);
* every operation named in a call under `dwc36/` (sub-folders included) exists in `dsf/golden/api_contract.json`;
* `dwc36/i18n/es.json` and `en.json` have the same keys.

The 3.6 page no longer mirrors the files, keys or operations of the 3.7 tree. Work on the 3.7 line is an owner decision; when it happens the golden
is refreshed on purpose (`LINES_FROZEN_WRITE=1 node tests/lines-frozen.test.js`) in the same commit. The render and template tests (`render`,
`vue-templates-compile`, `vue-i18n-syntax`) are 3.7 tests and read `dwc-src` only.

## Installing

`Projects/instalar-servicio.sh <version>` (outside the repos, the owner runs it) reads the `.py` files from the MAIN checkout of this repository and
the zip from `TallerPlugins/releases/WorkshopService/`. For the strict zips this machine (DWC 3.6.3) uses the 3.6 one. What the script needs
(the owner edits it, the repos do not): (1) `ZIP=` must name `WorkshopService-$VER-dwc3.6.zip`, copied from `dist/release/` of this repo
(or point `ZIP` at that folder); (2) the python block that updates `/opt/dsf/plugins/WorkshopService.json` must also copy
`d['dwcVersion'] = newm['dwcVersion']` and `d['sbcDsfVersion'] = newm['sbcDsfVersion']` (it only copied version, name, data and dwcFiles, so the
installed manifest would keep the old `3`); (3) the comment about the universal zip having no `css/` is obsolete (the 3.6 zip has `css/` again and
the `.gz` companions; the loops already copy both). Install with the machine idle.
`tools/install.sh` (generic installer, `docs/INSTALL.md`) is the alternative for another machine.
