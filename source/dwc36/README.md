# The service page (`dwc36/`)

The page of the plugin WorkshopService in DWC 3.6 (Vue 2.7, Vuetify, Vuex). Everything the person sees is built from this folder; the backend is
`dsf/`. Design and rules: `informes/rediseno-ui-service/` (`arquitectura/ARQUITECTURA-FRONTEND.md`, `GUIA-DISENO.md`, `FLUJOS.md`).

## Layers

Imports go from right to left only; `tests/layers.test.js` fails otherwise.

    core/      data layer, no .vue: calls, session, resources, actions, clock, live data, DWC access
      <-
    ui/        the kit: generic Sv*.vue pieces, no store, no API, no text of their own (see ui/README.md)
      <-
    sections/  one folder per section; sections never import each other
      <-
    app/       the shell (ServicePage.vue), the places (places.js) and the address (url-sync.js)

| Folder | What lives there |
|---|---|
| `core/api/` | `call.js` (the ONLY caller of the service, with retry and session loss), `files.js` (read and write JSON on the SD card, always `application/octet-stream`), `shapes.js` (how an answer is read), `errors.js` |
| `core/store/` | `session.js` (who I am, `can(op)`, `want(ops)`), `resource.js` and `paged.js` (a read with state), `action.js` (a change with its confirmation), `bridge.js` (state file of the G-code bridge), `access-focus.js` (a request to show an object of Access) |
| `core/actions/` | one file per section with its actions (`createAction`); a `.vue` cannot export them |
| `core/resources.js` | the reads every section shares |
| `core/dwc.js` | the ONLY file that touches DWC internals (store, routes, files, plugins) |
| `core/clock.js` | the ONLY clock: `every(seconds, fn)`; no `setInterval` anywhere else |
| `sections/<id>/` | `index.vue` (tabs, what is in view), one `.vue` per tab, `view.js` (pure functions that shape data) |
| `styles/` | `tokens.css`, `kit.css`, `page.css`; colours only as tokens, never in a `.vue` |
| `i18n/` | `es.json` and `en.json`: the same keys in both; no `*_en` siblings |

Sections today: home, health, machine, data, setup, links (connections), session, access, security. Access and Security host the screens that were
rebuilt with their own tests (`Access*.vue`, `Security*.vue`, `AuditCard.vue`, pure logic in `access-*.js`) and add the DWC password tab.

Rules the tests keep: files up to 400 lines, no `v-html`, no colours in `.vue`, texts as catalog keys, a new operation is gated with `can(op)`.

## How to add a screen

1. Add the section or tab to `app/places.js` (id, icon, tabs, whether it is for administrators).
2. Create `sections/<id>/index.vue` with props `active` and `tab`; start reads with `resource.show()` when `active`, stop them with `hide()`.
3. Reads: `createResource` in `core/resources.js`. Changes: `createAction` in `core/actions/<id>.js` (level `arm: 'none' | 'double' | 'dialog'`).
4. Draw with the kit: `SvZone` for a read, `SvActionRow` for a row, `SvConfirmDialog` for a level 3 or 4 confirmation, `SvHelp` for the four-line help.
5. Texts in a catalog area of `i18n/es.json` and `i18n/en.json` (plurals as `a | b`, same placeholders).
6. Register the section in `app/ServicePage.vue` (`seen<Id>` + `v-if` / `v-show`) and add a test `tests/section-<id>.test.js`.

## Tests and simulator

    python tools/run_tests.py -- node tests/<file>.test.js      # one file per process
    python tools/dev/run_sim.py --scenario users --build v4     # the page in a real DWC 3.6 against a simulated service
    python tools/dev/sim_build.py v4                            # fast build into dist/sim/v4 (needs a free clone: TALLER_DWC_SRC_36, > 4 GB free memory)

The simulator does not publish guard state, has no plugins installed and no bridge: see `tools/dev/README.md`, "Limits".

## Pieces that are candidates for the family

`ui/SvActionRow`, `SvZone`, `SvSheet`, `SvConfirmDialog`, `SvReason`, `SvHelp`, `SvBand`, `SvSectionNav`, `SvTabs`, `SvVerdict`, `SvSwitch`
(copying one to `TallerPlugins/vue/_shared36` means its files plus the classes it uses from `styles/kit.css`); `core/store/action.js`,
`resource.js` and `core/api/call.js` are the data layer a plugin page would share.
