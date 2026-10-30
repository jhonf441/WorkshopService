# Building from source

Only the DWC 3.6 line is published. The release zip of this repository (`<Id>-<version>-dwc3.6.zip`) can be rebuilt from the folder `source/`.
Tested: a clean clone of `WorkshopMotors` builds the same JavaScript as the release, byte for byte (only the file name hash differs, because DWC puts the build path in it), and the macros are the same text (a Windows clone turns line endings into CRLF: set `git config core.autocrlf false` before cloning to get identical files).

## What you need

- Python 3.9 or newer.
- Node.js 18 or newer and git (only for plugins with a page written in Vue; plain-JS plugins need only Python).
- A checkout of [DuetWebControl](https://github.com/Duet3D/DuetWebControl) at the tag `v3.6.3`, with `npm install` already run. It is used only as a build tool, and `build.py` changes it while it builds (it adds the plugin under `src/plugins/` and edits `src/plugins/imports.ts`), so use a copy that is only for this and never run two builds at once.

## Build

```bash
git clone https://github.com/jhonf441/<Id>.git
cd <Id>/source
export TALLER_DWC_SRC=/path/to/DuetWebControl     # the v3.6.3 checkout (default: ~/Projects/dwc-src)
python3 build.py <Id> --completa --dwc 3.6
```

The result is `dist/<Id>.zip` (the strict DWC 3.6 zip: `dwcVersion` 3.6, files compiled, `.gz` copies, macros under `sd/`). Compare it with the zip of the release: same file list, same compiled code.

`build.py` also knows how to install on a Duet (`--install`, over SSH with `TALLER_SSH=user@host`) and to keep versions (`--bump`, `--rollback`); you do not need any of that to rebuild a release. If the build ends with an SSH error ("Fallo en la Pi ..."), it is the step that archives the release on a machine: the zip in `dist/` is already complete.

## The backend (`WorkshopService`)

The repository of the service has the Python backend (`source/dsf/`), its page (`source/dwc36/`) and the G-code bridge (`source/bridge/`). Its page is built with the same DWC checkout (`node scripts/build-plugin.js <folder of the plugin>`), and the strict zip is assembled by `tools/build_release.py`. The Python files need no build.

## Layout of `source/`

```
build.py           builds the plugin zip
design/            the shared CSS and theme of the family
tools/             helpers (macro translation generator, ...)
vue/<Id>/          the plugin (plugin.json, i18n, pages, sd/ macros)
vue/_shared*/      code shared by the Vue plugins (API client, texts)
src/               plain-JS plugins and their shared code (only in those repositories)
```

## Translations

Texts are keys in the code (`$t('plugins.<Id>.area.key')` in Vue pages, `i18nT('area.key')` in plain-JS pages) with the texts in `i18n/es.json` and `i18n/en.json` of each plugin. Macro messages are bilingual inside the macros.
