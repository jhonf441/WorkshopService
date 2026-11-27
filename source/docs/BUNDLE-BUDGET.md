# Weight budget of the service page

DWC downloads the CSS and the JS of the service page on every load, on a Raspberry Pi over Wi-Fi. The page grew between 2.52.4 and 2.61.0 (JS about 9 percent, CSS about 13 percent), so its weight is capped.

- The only place that holds the numbers is `tools/bundle-budget.json` (`css_bytes`, `js_bytes`). They are measured on the compiled 3.6 zip: `dwc/css/*.css` and `dwc/js/*.js`, without `.gz` and `.map`.
- `python tools/build_release.py` (and `--check`) compares every release zip made with `--completa` or a reused bundle against them and refuses the release when it is over. A fast build is not measured (it is not minified like the real one).
- `node tests/bundle-budget.test.js [zip]` does the same on `dist/release` or `dist` for the version in `plugin.json`; with no compiled zip it skips and says so. The source-side estimate `tests/css-cap.test.js` stays as the early warning that needs no build.
- The values are the measured weight of the compiled release plus 2 percent of margin.

## How to change a number

Lowering one is free: after a release that weighs less, write the new measure plus 2 percent.

Raising one happens only by a decision of the project lead. Do not raise it to make a build pass: remove weight first (unused texts, unused rules, duplicated code). When the decision is taken, change the number, and write the reason and the new value in the `CHANGELOG.md` entry of that version.

## Known candidates

- Budget after the split (2.65.0): CSS 109 958 B (measured 107 802 B plus 2 percent), JS 2 034 091 B (measured 1 998 013 B).
- Done: the shared sheet is split in a core (`family.css`, the only one this page loads) and a plugins part (`family-plugins.css`, never loaded here): toast, side tabs and navigation, tabs, popover, state dots and the guide fold left this page (about 7.4 KB of CSS). The service keeps its own `theme.css` (the shared one without the import of the plugins part); `tests/family-split.test.js` in TallerPlugins fails when the page starts using a class that only the plugins part defines.
- The two language catalogs are about 523 KB of source (a quarter of the JS); they carry every text of the page in both languages.
