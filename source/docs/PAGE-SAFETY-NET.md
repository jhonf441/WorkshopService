# Safety net of the service page (redesign, step 0)

Step 0 was tests only. Step 1 (the double tap, typed errors, `password.status` as an object, the role gate of Automations, dead code) changed the page and flipped the tests listed in "Known defects" below on purpose. The net goes green on the page as it is and stays green while the page is extracted into smaller
files (steps 1 to 8: nothing visible changes). Run each test alone, one per process (they share one fake clock and one identity per process):

    node tests/page-structure.test.js
    node tests/page-characterization.test.js
    node tests/page-actions.test.js
    node tests/page-inventory.test.js
    node tests/page-timers.test.js
    node tests/page-arm.test.js

All of them need the DWC 3.6 clone with `node_modules` (`$TALLER_DWC_SRC_36` or `~/Projects/dwc-src`); without it they say so and exit 0 (the structure test
still checks the line limits). No network, no real timer (a fake clock replaces setTimeout and setInterval, `fetch` is replaced where a card would read), each
runs in a few seconds.

## The harness: `tests/lib/page36.js`

Mounts the REAL `dwc36/WorkshopService.vue` in node. It builds on `stage36.js` (every .vue split with the real compiler) and `render36.js` (vnode walker;
a new option `markHidden` marks an element under a false `v-show` with `data-hidden="1"`, off by default so the other tests are unchanged).

- Real: the page, its mixins, `workshop-auth.js` (the role rule `workshopCan`, fed by a table built from `dsf/golden/api_contract.json`), the small components
  (header, notices, side bar, process rows, processes summary, black box card) and the pure modules.
- Stand-ins: the service client `workshop-api.js` (every call is recorded as `{op, args, opts}` and answered by the test; `ApiError` and `apiText` are copied
  from the real file at load time, so they cannot drift), the big cards that have their own tests (bridge, database, users, roles, keys, access, security, received
  commands, package, startup: drawn as an empty element that shows the props the page gives it), the access client, and i18n (`t()` answers the key, with its
  parameters as `|name=value`). The store state is reactive like DWC's.
- Roles: `visitor`, `viewer`, `operator`, `technician`, `admin`, `usersOff` (`page.open({ role })`). One identity per process: open a context, use it, open the next.
- `fakeTimers()`: `pending()` lists what is scheduled with the place that made it (`file#function`; a promise callback has only `#(callback)`), `tick(ms)` moves the clock.
- Texts are asserted as i18n KEYS; the tests check that every key the page draws exists in `dwc36/i18n/es.json` and `en.json`. No Spanish in the tests.

## What each test pins

| Test | Golden | Pins |
|---|---|---|
| `page-structure` | `tests/golden/page-structure.json` | The files of `dwc36/` over 400 lines with their lines (a file may only get shorter, a new file must be 400 lines or less). The numbers of `WorkshopService.vue`: lines, template, script and style lines, navigation sections (read from `page-nav.js`), data fields, watchers, computed, methods, imports (the redesign can only reduce them). No forbidden word and no emoji in the files of the net. |
| `page-characterization` | `page-characterization.json` | The navigation of each role (six sections for visitor, viewer, operator and technician; eight for the administrator and with users off, step 13), the header, and what each section draws (texts as keys, ids, controls with their disabled state, the cards that are mounted and their props) for the administrator, the other roles as a difference. Lazy mounting (`visited`) and `v-show`. Service stopped, no data, black box report, header chips, no-users notice. The anchors `svc-bridge`, `svc-base`, `svc-package`, `svc-proc-<id>` and how `irAcuando`, `goProcess`, `goA`, `?anchor=` and the events of a row reach them. `canDo` of the dangerous operations for every role, the password card per role. |
| `page-actions` | `page-actions.json` | The calls (operation, arguments, options) and the state kept by `readKey`, `sendTest`, `closeJob`, `changeMode`, `controlProcess`, `restartService`, `setChannel`, the channel unlock, `putKey`, `removeKey`, the one-call actions (`setShutdown`, `setMovMode`, `setMovRelease`, `setMovIdle`, `showBox`, `hideBox`, `loadApiOps`, `readVision`), and what opens the page (`mounted`). |
| `page-inventory` | `page-inventory.json` | Every operation named in a call in `dwc36/` exists in the contract; the dynamic `db.<op>` and `processes.<action>` are expanded and exist; the operations each file refers to; the operations the page asks per section. |
| `page-arm` | none | The double tap: `arm-levels.js` against the contract (every operation that is not a read asks, a stop never does, an unknown one asks), `ArmButton` and `ArmChips` rendered (arm, disarm by the timer, independent timers, Escape, attributes, destroy), and on the real page the controls that acted with one tap (shutdown at the end of the job, movement mode and times, module mode, the console) needing two taps. STOP is never wrapped; the dead code of the page is gone. |
| `page-timers` | `page-timers.json` | The `setInterval` / `setTimeout` call sites per file; what the page creates when it opens and when it is used; what is still scheduled after `beforeDestroy`; the polls that run while their section is hidden. |
| `automations-card` | none | Machine > Automations (P-14), the real page for the six identities: the five blocks and the eight rows in order, each control once (the settings of the air, the lights and the zones and the camera relay moved here from the process rows; Processes only shows a quiet link to this place, a navigation with no call to the service), ONE chip shape (an icon and a word in sentence case), one short sentence per row, "More detail" folded at first, 40 px targets, nothing decided by the screen size. The operations of the moved controls stay pinned by `page-actions`, `page-arm` and `process-settings`. |
| `catalog-case` | none | No message value of `dwc36/i18n` in capitals (acronyms aside; the two texts the service publishes are listed), no duplicate key (a strict parser, `tests/lib/json-strict.js`), the same keys and placeholders in es and en. |
| `bridge-card-characterization` | `bridge-card.json` | The bridge card (step 7b), mounted for real with its parts: every state it draws (texts as keys, controls, ids, a hash of the html with its white space collapsed), the calls it makes (`bridge.service`, `bridge.service.set`, `bridge.test` and the five files of the bridge on the SD, with arguments and when), its timers (the 3 s read with the 404 backoff, the 4 s double tap, the 1.5 s marks, nothing left after destroy), its interface (no props, no events, the session data) and that every text it draws exists in es and en. KNOWN BEHAVIOUR pinned on purpose: the read of the SD state keeps running while the section is only hidden (D7). It did not change while the card was split into `Bridge*.vue`, `bridge-*.js` and `bridge-*-mixin.js` (`tests/lib/bridge-source.js` gives the other bridge tests the card as one text). The pure modules have their own unit test, `bridge-view.test.js`. |

The access screens (`Access*`, `Security*`, `Activity*`, `AuditCard`, `access-*.js`) have their own tests and another stream of work: they are checked against the
contract but are not in the frozen lists of the inventory and the timers.

## Known defects (step 1 flipped D1, D2, D4, D5 and D10 on purpose)

The tests that pinned a defect carried the note `known defect, to be fixed in step N: this test will be changed on purpose`. Step 1 (the double tap, the typed errors,
`password.status` as an object, the role gate of Automations) fixed five of them and flipped those tests in the same commit: they now assert the fixed behaviour.

| Defect | Test | State | Step |
|---|---|---|---|
| D1 `readKey` regex on Spanish text | `page-actions`: readKey (D1 flipped) and the password card | FIXED: `password.status` answers `{set: true, false or null}`, the page reads `.set`, the button "Remove the password" shows when a password is set | 2 (done with step 1) |
| D2 one arm timer for the API tester | `page-actions`: D2 flipped | FIXED: every operation has its own `ArmButton` and timer | 1 |
| D3 the console asked the double tap for 75 of 324 operations | `page-arm`, `page-actions` (dangerous) | FIXED: every operation that is not a read (a stop never), an operation not described yet counts as dangerous | 1 |
| D4 `setChannel` has no catch | `page-actions`: D4 flipped | FIXED: a failed `comms.set` keeps the panel open and shows the real error; a cancel is no failure | 1 |
| D5 `apiText` turns failures into text | `page-actions`: closeJob, putKey, hideBox (D5 flipped) | FIXED for the actions of the page: `api()` and the typed error (`ErrorNotice`); `putKey` keeps the typed password when it fails | 1 |
| D10 no role gate on Automations | `page-characterization`: D10 flipped | FIXED: `canDo` and one lock reason per card for the shutdown at the end, close job, movement mode and times, the channel unlock, the black box | 1 (P-10) |
| Timer leaks after `beforeDestroy` | `page-timers`: KNOWN LEAKS | the arm timers are gone (they live in `ArmButton`, cleared on destroy); still scheduled: process answers 8.1 s and 20 s, the 250 ms interval of `irAcuando` | 3 (data layer) |
| Hidden polls (D7, D13) | `page-timers`: KNOWN HIDDEN POLL(S); `processes-redesign`: a hidden section rebuilds nothing | The 3 s clock still ticks (the header chip needs the freshness of RS485), but the list of the Processes section (words to search, groups, order, attention list) is built by `ProcessesPanel` only while the section is shown (`active`); the 5 s sampling and the 10 s Vision read run whatever section is shown; the bridge card reads the SD state every 3 s and the database card every 15 s while only hidden by `v-show` | 7 (sections report active or hidden) |

Honest notes: the 3 s clock (`nowSvc`), the bridge poll and the database poll are NOT leaks at destroy (all three are cleared in `beforeDestroy`, and the tests check
it); what is pinned is that they keep running while their section is hidden. `downloadBox` (a direct `fetch` and a file download) is not exercised.

## How to flip a known-defect test on purpose

1. Fix the defect in its step. The test fails on the line that carries the old behaviour (the message names the defect).
2. Change that assertion to the new behaviour, and replace the note `known defect, to be fixed in step N` with a plain description (or delete the test if a normal test now covers it).
3. Refresh the golden of that test: `PAGE_GOLDEN_WRITE=1 node tests/<test>.test.js`, read `git diff tests/golden/` and keep only the intended lines.

## How to refresh the frozen lists

- Goldens (`characterization`, `actions`, `inventory`, `timers`): run the test with `PAGE_GOLDEN_WRITE=1`, then review the diff. A step that moves code without
  changing behaviour must leave `page-characterization.json`, `page-actions.json` and the `pageBySection` part of `page-inventory.json` untouched; the
  per-file lists of the inventory and the timers move with the code (move the names, never add one without a reason).
- Structure: the frozen numbers only go down. When they do the test fails and tells you; lower them with `PAGE_GOLDEN_WRITE=1 node tests/page-structure.test.js`
  (it refuses to write a number that went up or a file that is not already in the list). To remove a file from the list, make it 400 lines or less and run the same
  command.
- 3.6 / 3.7: `tests/lines-frozen.test.js` (decision P-8) keeps `dwc-src/` frozen and no longer compares it with `dwc36/`; a step may add, rename or delete
  files and keys of `dwc36/` without any list (`docs/DWC-LINES.md`, "Tests").
- A new file under `dwc36/` must stay at 400 lines or less (the structure test enforces it).
