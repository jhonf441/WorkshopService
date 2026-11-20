# Wiring plan: the new navigation and the new home (redesign step 13)

Status: APPLIED (branch `plan-rel8`, on top of master 2.46.0 with plan-nav and plan-page1). What was done, and where it differs from the plan below:

- Tabs were done now (not left for "stage B") for the sections whose cards are separate blocks: Machine (channel, automation), Connections (bridge, keys, reference),
  Data (database, package, commands) and People (users, roles, password). Processes keeps list and load in one card (no tab strip); Connections has no camera tab
  (the relay is a row of the processes list; the tab id stays in `page-nav.js` for the day it has a block). Second level: `dwc36/SectionTabs.vue`.
- The model of section and tab applied to the page lives in `dwc36/page-nav-mixin.js` (computed of the home and the header chip, `goTo`, `showPlace`, `setTab`,
  `tabNow`, `tabIs`, `tabOn`); `dwc36/nav-kit.js` is its one import (like `arm-kit.js`). `irAcuando` stays in the page (its timer is pinned by the net) and is
  the one function that shows a place and scrolls: `goTo`, `goA`, `goProcess`, the route watcher and `?anchor=` all end there.
- A section is mounted when it is first opened and each tab of it when it is first shown (then only hidden). Status and Processes are drawn from the first paint.
- The header chip is the status of the home (`headerStatus`), `:loading="true"` keeps the bar's own health chip off; version (and contract when there is one) is
  quiet text next to it; `PageHeader` has a `compact` prop (lower bar, one-line lead).
- `startup_pending` is left out (needs an event from the start-up steps; `ConfigPackagePanel` now holds the one total, `package-view.js` `summarize`); `contract` stays empty until the service publishes it.

New files (all under 400 lines, tested by `tests/page-nav.test.js` and `tests/page-nav-render.test.js`):

| File | What it is |
|---|---|
| `dwc36/page-nav.js` | The 8 sections in 5 groups as data (a group label must add information: only the groups of several items are named, Operation and Administration; a group with one item for the role has no label); roles; the map of every old section id and old anchor to its new place; `resolvePlace`, `navLayout`, `navKeyTarget`, `roleForNav`. |
| `dwc36/PageNav.vue` | The ONE navigation level (rail on wide and tall windows, bar on narrow or short ones). |
| `dwc36/home-view.js` | What the home says: attention kinds and their links, header status, uptime, machine state, armed rows, badges. |
| `dwc36/HomeSection.vue` | The new Estado, read only. Emits `go` (a place) and `sign-in`, nothing else. |
| `dwc36/SignedOutNotice.vue` | The single "sign in to see this" block. Emits `sign-in`. |
| `dwc36/i18n/{es,en}.json` | New area `pageNav` (no key of the old areas changed). |

## 1. The two stages

Stage A (this document, one commit): swap the navigation and the home, keep every card as it is. The cards are only regrouped under the new section ids and
stacked, so nothing disappears and nothing changes behind a click. Stage B (steps 14 and later, one section at a time): each new section gets its own
component with tabs (the tab ids are already in `page-nav.js`), and the stacked cards become tabs. Stage A must not wait for stage B.

### Where each block of the page goes (stage A)

| New section | Blocks it shows (old place, lines at 6e8a82b) |
|---|---|
| `state` | `<home-section>` (new). Nothing else: no card of the old Summary stays here. |
| `machine` | the channel card (Summary, from the comment "Communication with the Duet", about lines 82-165); the Automations column of Processes (`<v-col cols="12" md="5">`, lines 289-424). |
| `processes` | the processes list and the load on the board (`<v-col cols="12" md="7">`, lines 170-288). |
| `connections` | the bridge (468-471) and the API section (502-end of that block: keys, reference, console). |
| `data` | database + package (478-483), received commands (473-476), the start-up section (line 65) and the black box card (line 69). |
| `people` | users + roles (485-490) and the DWC password card (426-466). |
| `access`, `security` | unchanged (491-500). |

Why the start-up section and the black box card leave the home: both have buttons that change things (accept a change of a file, download, hide the report).
The home is read only (decision P-3), so they move to Data, and the home only points at them (`startup_pending` -> `svc-startup`, `unclean_shutdown` ->
`svc-blackbox`). Give the two wrappers those ids: `<div id="svc-startup"><config-package-panel .../></div> (2.49: the cards StartupSection and ConfigPackage became ONE panel, `ConfigPackagePanel`, inside `<div id="svc-package">`)` and `<div id="svc-blackbox"><black-box-card .../></div>`.
Both anchors are declared in `page-nav.js` (tabs `package` and `database` of `data`); the test fails if a link points at an anchor no tab holds.

## 2. Changes to `WorkshopService.vue`

1. Imports (line 621-622): remove `import SideTabs from './SideTabs.vue'`; add
   `import PageNav from './PageNav.vue'`, `import HomeSection from './HomeSection.vue'`, and
   `import { resolvePlace, roleForNav } from './page-nav.js'`, `import { attentionBadges, attentionItems } from './home-view.js'`.
   In `components` (line 695): remove `SideTabs`, add `PageNav, HomeSection`.
2. Template, lines 34-36: replace
   `<div class="st-layout"><side-tabs v-model="section" :items="sections" /><div class="st-body">` with
   `<div class="pn-layout"><page-nav v-model="section" :role="navRole" :badges="navBadges" /><div class="pn-body">`.
   The closing `</div></div>` stay. (`.pn-layout` and `.pn-body` are defined in the style of `PageNav.vue`: a bar takes the first row, the content goes under it.)
3. Template, the blocks: change each `v-show="section === 'old'"` as in the table above, and the `visited` keys with it (data line 699: the keys become
   `machine, processes, connections, data, people, access, security`; `state` and `processes` are drawn from the first paint as today for `summary` and
   `processes`). Because `watch: { section(v) }` (line 740) marks a section visited only when the id is a key of `visited`, keep that rule.
4. Template, lines 37-166 (the Summary block): replace the whole block with
   `<div v-show="section === 'state'"><home-section :session="homeSession" :state="homeState" :service="homeService" :counts="count" :attention="homeAttention" :now="homeNow" :armed="homeArmed" @go="goTo" @sign-in="signIn" /></div>`.
   The processes chips, "backend started on", the channel card, the start-up section and the black box card leave this block (see the table).
5. Template, lines 23-32 (the `v-alert` for "no users created"): delete it. The same fact is the `users_off` row of the attention list (and the `now`
   line "No users: everybody is an administrator"); its two buttons were `section = 'users'`, now the link of the row.
6. Template, lines 10-19 (the header chips): keep ONE chip. The slot keeps `headerChip` only; delete the two `v-if="chainBroken"` and `v-if="accessDamaged"` chips
   (they become rows of the attention list and badges of Security and Access). Also remove the attribute `loading` of `<page-header>` if the owner wants the
   health chip back (today it is a boolean `true`, so the header never draws its own health chip: a separate finding, not part of this step).
7. Data (line 698): `section: 'state'` instead of `'summary'`.
8. Computed `sections` (lines 791-806): delete. Add:
   - `navRole()`: `roleForNav(workshopRole() /* from workshop-auth.js */, this.accessVisible)` (keep `accessVisible` as it is: `canDo('access.profiles.list')` is the one source
     of truth, `PageNav` never decides who is an administrator).
   - `homeAttention()`: the list of `{ kind, params }`, built from what the page already has:
     `processes_down` {n: count.bad}, `processes_warn` {n: count.notice} (only when `count`), `channel_warning` {detail: communication.warning} (only when set),
     `files_damaged` (healthPi.base.check is not 'ok'), `unclean_shutdown` {when: lastDrop.detected} (when `boxReport`, an unseen report),
     `chain_broken` (data `chainBroken`), `access_damaged` (data `accessDamaged`), `users_off` (`identity && identity.compat`),
     `startup_pending` {n} (see "Open points").
   - `navBadges()`: `attentionBadges(attentionItems(this.homeAttention))`.
   - `homeSession()`: `signedOut() ? 'visitor' : sessionState() === 'resolving' ? 'resolving' : 'signed'` (the same functions `PageHeader` already imports from `workshop-auth.js`).
   - `homeState()`: `'loading'` while `!$store.getters.isConnected`, `'error'` only if reading the plugin data throws (wrap `homeAttention` in try/catch and set a data flag), else `'ready'`.
   - `homeService()`: `{ up: this.connected, restarting: !this.connected && !!this.svcRestart.phase, uptimeS: processInfo && processInfo.age_s, version: pluginModel && pluginModel.version, contract: '', startedAt: serviceStarted }`.
     `contract` stays empty until the service publishes it as a plain value; the home shows it only when present.
   - `homeNow()`: `{ status: $store.state.machine.model.state.status, mode: model.state.machineMode, job: { active: job.active, name: jobName, since: hourShort(job.since) }, who: identity && identity.user ? { name: identity.user.name, role: identity.role } : null }`.
   - `homeArmed()`: `{ afterJob: powerOffOnFinish, movement: { mode: movMode, releaseS: movRelease, idleS: movIdle } }`.
9. Methods: add `goTo(request)` and `signIn()`; rewrite `irAcuando(id)` and the `ANCHOR_SECTION` table (line 663) on top of `resolvePlace`:
   ```
   goTo(request) {                      // a place, an old id, an old anchor or a new section id
     const place = resolvePlace(request)
     if (!place) return
     this.section = place.section
     this.sectionTab = Object.assign({}, this.sectionTab, place.tab ? { [place.section]: place.tab } : {})   // data: sectionTab: {} (read by the section in stage B)
     if (place.anchor) this.scrollToWhenRendered(place.anchor)     // the 250 ms x 20 loop of irAcuando, unchanged
   }
   signIn() { askLogin() }              // askLogin from workshop-api.js, the same dialog as the header chip
   ```
   `irAcuando(id)` becomes `this.goTo(id)`; `goA(id)` the same; `goProcess(id)` becomes `this.procFilter = 'all'; this.procSearch = ''; this.goTo('svc-proc-' + id)`
   (the row id is `svc-proc-<id>`, so it lands on `processes/list`; today it relies on `this.section = 'processes'`).
   Delete `const ANCHOR_SECTION` (line 663).
10. Route: nothing to rewire. `mounted` (line 1331) and the watcher `'$route.query.anchor'` (line 749) already call `irAcuando`, which now is `goTo`.
    Old links keep working through `resolvePlace`: `?anchor=svc-base` -> `data/database#svc-base` (the phone notice that points at `svc-base` is unchanged),
    `svc-bridge` -> `connections/bridge`, `svc-package` -> `data/package` (today it does NOT change the section: a known defect fixed here),
    `svc-proc-<id>` -> `processes/list#svc-proc-<id>`, and the old section ids (`summary`, `users`, `base`, ...) too.
11. Other `this.section = '...'` assignments: line 747 (`accessVisible` watcher: `'summary'` -> `'state'`), line 1349 (`goAccess`: `'access'`, same), lines 494 and 499
    (`@go-users="section = 'users'"` -> `@go-users="goTo('users')"`, `@go-api="section = 'api'"` -> `@go-api="goTo('api')"`), line 65 (`@section="id => { section = id }"` ->
    `@section="goTo"`, it emits the old id `users`).
12. `SideTabs.vue` stays for the other pages that use it (Vision-style bars live in other plugins); no change to it. Remove its import only here.
13. The pin and fold of the old bar disappear with it: `localStorage` key `workshopSideTabsPinned:` is left alone (harmless).

## 3. Goldens that change, and why

Refresh each with `PAGE_GOLDEN_WRITE=1 node tests/<test>.test.js`, read `git diff tests/golden/` and keep only the intended lines. Everything below is intended.

| Golden | What changes | Why |
|---|---|---|
| `page-characterization.json` `sidebar` | Each role: 10 (admin) or 8 (others) items become 8 (admin) or 6 (others), the new ids and the new label keys (`pageNav.nav_*`); the group labels exist now. | The bar is `page-nav.js` now. |
| `page-characterization.json` per-section drawing | Re-keyed by the new ids; the Summary lines move: the channel card to `machine`, the start-up and black box to `data`, `count` chips to the home. Lazy mounting and `v-show` of `visited` re-keyed. | P-1, P-3. |
| `page-characterization.json` `anchors` | `svc-bridge` -> `connections`, `svc-base` and `svc-package` -> `data` (`svc-package` now changes the section; the line that pins "svc-package does not change the section" flips), `svc-proc-*` -> `processes`; `goProcess` and `goA` land on the new ids; `?anchor=` opening and the route watcher. The characterization test that reads `ctx.vm.section` expects new ids. | The old ids no longer exist. |
| `page-characterization.json` header | The two chips `chainBroken` and `accessDamaged` leave the header; the no-users `v-alert` leaves the page. | One prominent chip; the facts are attention rows. |
| `page-characterization.json` `canDo` and password card | No change. | No operation or gate moves. |
| `page-structure.json` `workshop_service` | `sidebar_sections` is no longer measured in the page (the `sections` computed is gone): change `measurePage` to read `SECTIONS.length` of `page-nav.js` (8) and the check "the page has ten sections" to eight. `computed`, `lines`, `template_lines`, `imports` go DOWN (the tool refuses to raise them). | Deleted computed `sections`, the Summary block and the alert. |
| `page-structure.json` `over_400` | No change (the new files are all under 400). | |
| `page-inventory.json` | Only `pageBySection` is re-keyed by the new ids. The operation lists per file do not change. | No operation is added or moved to another file. |
| `page-actions.json` | None. | No call changes. |
| `page-timers.json` | None, unless the removed Summary block held a timer (it did not). | |
| `tools/lines-allowlist.json` | Gone (decision P-8): `tests/lines-frozen.test.js` only keeps `dwc-src/` frozen, the operations in the contract and es / en with the same keys. | The 3.7 line is paused; new files and keys of `dwc36/` need no list. |

Tests that change by hand (not goldens): `tests/render.test.js` expects the texts `Comunicaci`, `svc-startup-master`, `svc-res-tile`, `6 al dia` in the
Summary: they move to the tests of the section that now holds them (Machine, Data), as the architect's step 13 says.

## 4. Props of `HomeSection`, with the page data each comes from

| Prop | Shape | From |
|---|---|---|
| `session` | `'visitor' \| 'resolving' \| 'signed'` | `signedOut()`, `sessionState()` of `workshop-auth.js` |
| `state` | `'ready' \| 'loading' \| 'error'` | store connection, and a guard around the plugin data |
| `service` | `{ up, restarting, uptimeS, version, contract, startedAt }` | `connected`, `svcRestart.phase`, `processInfo.age_s`, `pluginModel.version`, `serviceStarted` |
| `counts` | `{ ok, notice, bad } \| null` | computed `count` |
| `attention` | `[{ kind, params }]` | `homeAttention` above; kinds in `home-view.js` `ATTENTION_KINDS` |
| `now` | `{ status, mode, job, who }` | DWC `model.state.status`, `machineMode`, `job`, `identity` |
| `armed` | `{ afterJob, movement: { mode, releaseS, idleS } }` | `powerOffOnFinish`, `movMode`, `movRelease`, `movIdle` |

Events: `go` with `{ section, tab, anchor }` -> `goTo`; `sign-in` -> `askLogin()`. Nothing else leaves the component, and the test clicks every button of every
state to prove it.

## 5. Open points (decisions or data the wiring still needs)

- Access and Security badges and rows (`access_damaged`, `chain_broken`) are known only after the person opens those sections: they are mounted lazily and
  report through `@damaged` and `@chain`. Until the service publishes both facts (a plugin data key, like the other published states), the home shows them only
  once the sections have been visited. Do not mount the sections hidden to get them: they poll.
- `startup_pending` needs the number of steps still pending; today only the panel of the Configuration package knows it (`ConfigPackagePanel`, from the `@state` of its blocks). Give `ConfigPackagePanel` an
  `@pending` event for the page, or leave the kind out until then (the home ignores kinds it is not given).
- Decision P-4 (nothing hidden because of the kiosk): `PageNav` changes the SHAPE with the window (rail or bar), never the items; the thresholds are
  `NAV_BAR_BELOW_WIDTH = 900` and `NAV_BAR_BELOW_HEIGHT = 560` in `page-nav.js`. The kiosk height under the DWC panels was not measured (no browser here).
- Emergency stop and stop controls: none of them is in the navigation or the home (a test checks the data). They stay where they are, outside the sections.
- With 6 sections for everyone and 8 for the administrator the design's "7 without administrator" does not hold: Access and Security are both administrator only
  (as today), so the rest see 6.

## 6. Second review (11-nov): one number, one chip, a layout chosen from the real free room

- One number: `homeView(service, list, role)` in `home-view.js` returns the rows, the status and the badges. The header chip, the status text of the home, the badges of
  the navigation and the Attention block all read it (the page through `homeView`, `HomeSection` through the same function). A visitor's rows are only the service
  line (`VISITOR_KINDS`); anybody else gets a row only when the section that fixes it is one of hers. `tests/section-home.test.js` and `tests/app-shell.test.js` prove it on the new page (the old home is gone).
- One prominent status: the header chip (`StatusChip.vue`, a 40 px button that emits `explain`, the page goes to `state` and the anchor `hs-attention`). The status in
  the home block is plain text.
- Layout: `PageNav` measures the free room of its container (`nav-measure.js`: container width; height of the nearest scrolling ancestor, else the window; minus 72 px
  for the sticky rail) with a ResizeObserver and the window events. `navLayout(box, role)` gives the rail only when `railHeight(role)` fits (40 px items, 18 px labels,
  9 px between groups, 8 px padding: 374 px for 6 items, 454 px for 8) and the box is at least `NAV_BAR_BELOW_WIDTH` (720 px) wide; else the bar (44 px items).
