# The Access section: one place, five tabs (DWC 3.6 page)

Steps 1 and 2 of `informes/rediseno-pagina/ROLES-Y-PERMISOS-DISENO.md`. Decisions of the owner: P-17 (one section, five tabs), P-18 (own roles and profiles are shown
together in the list of what a person has), P-19 (the templates are reviewed by the owner and none is given by itself); step 3 wrote the six templates.

## Tabs

| Tab id | Title (es) | Holds | Operations (unchanged) |
|---|---|---|---|
| `people` | Personas | `UsersCard` (accounts, PIN, role, modes, sessions) and `AccessPeople` (groups, profiles, ceiling of each person) | `users.*`, `access.person.get`, `access.groups.*`, `access.attach`, `access.detach`, `access.ceiling.set` |
| `profiles` | Perfiles | `AccessProfiles` and, under it, `RolesCard` (own roles: the matrix) | `access.profiles.*`, `roles.list`, `roles.effective` (the four base roles), `roles.set`, `roles.remove` |
| `templates` | Plantillas | five ready-made profile templates (a proposal, never given by itself: `access-templates.js`), the card of the Administrator (a role, not a profile) and the read-only plugin profiles | reads only: `access.profiles.list`, `roles.list`, `users.list`; copy opens the profile editor on a draft (`access.profiles.validate` / `set` are the editor's), give runs `access.attach.validate` and the dialog confirms `access.attach` |
| `can` | Qué puede hacer quién | the grid of people by areas and the detail of one person | `users.list`, `roles.list`, `access.person.get`, `access.groups.list`, `access.check` (batch) |
| `keys` | Llaves de acceso | `ApiKeys` (create, change, revoke) and `AccessKeys` (what each key reaches, last use) | `keys.*`, `access.report`, `access.review` |

The section is still for administrators only (`needs: 'admin'`, `docs/PAGE-NAV-LOCKS.md`). The People section of the page keeps one tab: My session (`UsersMySession`:
own PIN, sign out; any signed-in person) and the DWC password card, with a quiet pointer to Access for an administrator.

## Old places

`page-nav.js` keeps every old id resolving. `tests/access-one-section.test.js` has one check for each row.

| Old | New place |
|---|---|
| section `users` | `access/people` |
| section `api` | `access/keys` |
| section `access` | `access/profiles` |
| tab `people/users` | `access/people` |
| tab `people/roles` | `access/profiles`, anchor `svc-roles` (the block of the own roles) |
| tab `connections/keys` | `access/keys` |
| the other old sections, anchors and `svc-proc-<id>` | unchanged |

## Who can do what

`who-can-view.js` is pure. It builds the view of a person from the answers of the service and decides nothing:

1. `roles.list` gives the capabilities (title already translated by the service, class, risk, `delegable`, `ops`).
2. `access-areas.js` places each of the 65 capabilities in one of ten areas (`tests/who-can-view.test.js` reads `dsf/permission_caps.py` and fails when one is in no area or in two).
3. One request per capability: the first plain operation of `ops` (an override for the families written as patterns), asked with `access.check` and `items`, with
   the mode the machine is in now. A call carries at most 100 requests (`BATCH_MAX`); the 65 capabilities need 64 (hardware parameters has no operation), one call per person.
4. Each answer is a line: `can`, `stop` (stopping is always allowed), `cannot` (with the cause and what to do), `admin_only` (not delegable) or `unknown` (the service
   could not say: it is said, not guessed). An area is `can`, `view` (only what reads), `partial`, `cannot`, `admin_only` or `unknown`; stops do not count.
5. The reason of a line is the sentence of `access-people-view.js` `checkOutcome` (the same as the test panel); the profile, rule and role names come from
   `display-names.js`. No capability id, operation id or `cap:` entry is drawn; the technical operation stays folded in "Another technical action".

Areas and the capabilities each one uses:

| Area | Capabilities |
|---|---|
| movement | machine.move, machine.motors, machine.takeover, machine.height, machine.workarea, machine.procedures, machine.try, machine.stop |
| tuning | machine.view, machine.meshes, machine.maintenance, machine.config_view, machine.config_apply, machine.workstate, machine.guard, machine.hardware_params, machine.config_restore, system.bed_calibration, system.bedzones, system.pelletlayers, system.layerrecipes |
| jobs | jobs.view, jobs.run, jobs.manage, jobs.air |
| files | jobs.library, jobs.library_manage, config.database, config.database_admin |
| lights | lights.view, lights.use, lights.config, lights.m950 |
| energy | energy.view, energy.timers, energy.meter, energy.shutdown, energy.reset |
| camera | camera.view, camera.capture, camera.vision, camera.manage, camera.settings, camera.relay |
| activity | activity.view, activity.write, activity.settings, activity.delete |
| service | config.view, config.api, config.edit, config.bridge, config.critical, processes.control, service.restart, system.plugins, system.view |
| security | security.session, security.audit, security.audit_tools, security.users, security.roles, security.access, security.keys, security.passwords |

"Try as this person" only calls `access.check` for one action; it does not sign in as the person, uses no PIN and writes nothing.

## Needs service change (none is done)

| # | What | Why |
|---|---|---|
| S2 | `access.person.summary { user }`: the exact state of every capability of a person in one call | a capability with several operations where only some are allowed is shown by its representative operation; the area can then say "partly" exactly |
| S3 | `access.preview { document, user? }`: evaluate a draft profile against a person without saving | the preview of the guided editor (step 4) |
| S5 | a way to ask the hardware parameters (`machine.hardware_params` has no operation) | today it is "not known" for anybody who is not an administrator |
| S6 | `access.check` answering for the mode of the machine without the page passing `mode_now` per item | only a convenience; the page sends it in every item |
| S4 | the text of `roles.effective` should say "role only: no profiles, groups or ceiling" while that operation exists | other clients still use it; the page only asks it for the four base roles now |
