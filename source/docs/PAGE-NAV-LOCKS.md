# Navigation of the service page: fold, pin and lock marks

The navigation (`dwc36/PageNav.vue`, data in `dwc36/page-nav.js`) behaves and looks like the side bar of the other pages (`SideTabs.vue`) in its rail layout.

## Fold and pin (`dwc36/nav-fold.js`, pure state)

- 176 px open, 52 px folded with only the icons; sticky 64 px under the DWC bar; the head (pin and double arrow) stays on screen, only the sections scroll.
- The double arrow folds and opens it. Nothing opens or floats by hovering (there is no hover handler).
- The pin ("Fijar" / "Pin", icon plus its name) is drawn only while the rail is open. A pinned rail does not fold when a section is chosen; an unpinned one folds by itself.
- The pin is remembered per browser (`workshopPageNavPinned` in localStorage, every read and write inside try/catch).
- The `bar` layout (narrow or short screens) draws neither fold nor pin, as `SideTabs` at 900 px or less; the lock marks are drawn in both layouts.
- Layout choice: the rail/bar decision uses the width of the CONTAINER of the page and the height of the free room (`navLayout`); neither changes when the rail folds, so folding never flips rail and bar. The content (`.pn-body`) takes the room the rail leaves (`bodyRoom`: 124 px more when folded). The rail needs `railHeight` (head 32 plus 8 items) for every role because nothing is hidden.
- Texts: the shared `common.sidebar_*` keys and `shared.sidebar_needs_session`, `shared.notice_session_reason`, `shared.notice_role_needed`, `shared.lockrole_*`. No new key.

## Lock marks

All 8 sections are drawn for everyone. A section the person cannot open yet carries a small lock on the corner of its real icon, a line under its name (folded: only the mark), and a tooltip and aria-label that say why: `Inicia sesion` (blue account-lock mark) when nobody is signed in, or the role it needs (lock mark) for a signed-in person with a lower role. A locked section is still clickable and shows its own block (`session-notice`, cover) that says the same and offers to sign in.

The decision is data (`needs` in `page-nav.js`; `roles` is derived from it) and is pinned by `tests/page-nav-locks.test.js`. The state comes from the page (`navRole` and `navOut` of `page-nav-mixin.js`, both follow `identityTick`, so the marks change when the session changes while the bar is on screen). The service decides who is an administrator (`canDo('access.profiles.list')`, `roleForNav`).

`needs: 'visitor'` means: something in the section is readable by a person with no session, so it is not locked. The controls inside keep their own lock reason.

| Section | needs | Evidence |
|---|---|---|
| `state` | visitor | The home is drawn for the visitor role (`home-view.js`, `HomeSection.vue`: a visitor reads the service state and gets a sign-in block for the rest). |
| `machine` | visitor | Communication channel and automations: read-only data of the model; the buttons carry their lock reason (`comms.set` and others). |
| `processes` | visitor | The list and the load are read-only for a viewer; pause and restart need a technician (`OP_ROLES` `processes.pause` and `processes.restart`) and say so on the control. |
| `connections` | visitor | The bridge status and the API reference are readable (`api.describe` is viewer); the keys tab needs the administrator (`keys.list`) and says so inside. |
| `data` | visitor | `db.status` and `blackbox.status` are viewer; backups, the package export and the apply need a technician or the administrator (`db.backup`, `package.export`, `package.apply`) and the Configuration package draws its own sign-in block. |
| `people` (named My session; the id stays so every old link resolves) | visitor | Two tabs. My session (default): the card of who I am, sign out, change my own PIN (`auth.change_pin` is viewer), plus a quiet line with the button Go to Access for an administrator. DWC password: the machine password card (`password.set`, `password.clear`: administrator, double tap), which says it is administrator-only and shows ONE lock reason; a signed-out person gets ONE sign-in block in each tab. The list of users (`users.list`, administrator) is in Access, People. The tab `password` keeps its id. |

Group of the section (2.50.1): My session sits in the group of Status (no label, like that group today), not under Administration. Evidence: the label Administration is drawn only when a group shows several items, and the other two items (Access, Security) need the administrator while My session is for any session; under that label it read as an administrator thing for the people who need it least. A group of its own would add a separator and 9 px to the rail height (tests/page-nav.test.js pins 432 for the visitor) on the 10-inch screen; joining Status adds neither, and Status, My session read as "how things are, and who I am". The only name Personas / People left is the Access tab that lists the people; the first tab of My session is named Sesion y PIN / Session and PIN so a tab never repeats its section.
| `access` | admin | Every `access.*` operation in `dsf/permissions.py` `OP_ROLES` is administrator-only, including the first read the section makes, `access.profiles.list`; nothing in it is readable below. The page already gated it with the same operation. It has five tabs (People, Profiles, Templates, Who can do what, Keys): the people list, the own roles and the keys moved into it from People and Connections and keep their own gates (`users.list`, `roles.list`, `keys.list`: all administrator); "Who can do what" only reads (`access.check`, `access.person.get`, `roles.list`, `users.list`). |
| `security` | admin | Review, report and the recorded activity read `access.review`, `access.report` and `audit.list` (all administrator-only in `OP_ROLES`), plus `audit.verify` and `audit.export`. |

Only Access and Security were hidden before; now they are shown locked. Nothing else changes for any role.

## Machine icon

`mdi-robot-industrial-outline` (an industrial robot arm: a machine that can do several jobs), checked in the bundled MDI font of the DWC clone and unique among the 8 sections. It replaces `mdi-gamepad-variant-outline`. Runner-ups, to change by name in `SECTIONS` of `page-nav.js`: `mdi-cog-transfer-outline`, `mdi-toolbox-outline`.
