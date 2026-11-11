# Roles, capabilities and custom roles

Phases 1 and 2 of the design in `informes/permisos-por-rol/DISENO.md`. The server decides; the pages only hide what a role cannot do.

## The four base roles

`viewer`, `operator`, `technician`, `admin` are in code (`dsf/permissions.py`, table `OP_ROLES`) and cannot be changed. Each operation has the
lowest role that may call it. `power.off` (like the other stops) needs no role: stopping is never blocked.
`dsf/fixtures/permissions_golden.json` is the decision of the table before the capability model for every operation, role and context
(modes, camera, arguments of the escalated operations); `test_permissions_golden.py` proves the base roles still decide exactly the same.

## Capabilities

`dsf/permission_caps.py` groups the operations into about 55 named capabilities (not to be confused with `capabilities.py`, which is
what the board can do). Each has a category (the nine groups of the API page), a class (`read`, `write`, `motion`, `stop`, `power`,
`admin`) and a risk 1 to 4. A capability does NOT say which role may use it: it only names a group so a custom role can add it or remove
it. A test fails when a registered operation belongs to no capability or to two.

`machine.hardware_params` has no operations: it is the explicit key that lets a custom role write the hardware-risk parameters (M208, M92,
M906, M913, M917, M569, M584, prologue) that `ESCALATE_IN` asks an administrator for. A role with only the key and without the technician-level
operation still cannot write them.

## Custom roles

A custom role is `{name, base, description, grant, deny}`. `base` is `viewer`, `operator` or `technician`, never `admin`. `grant` / `deny` hold
capability ids, operation names or patterns such as `lights.*` (like the patterns of the API keys). Decision order (`permissions.decide`):

1. A stop operation is always allowed (a denial cannot block stopping; denying one is refused when the role is saved).
2. A denial wins.
3. The camera rule of a viewer (the person needs the camera flag) and the mode rules of an operator stay on top of any grant.
4. The base role, or a grant when the base role is too low. A grant never lifts what an argument escalated: the hardware-risk kinds need the
   `machine.hardware_params` key, and a change of camera / Vision settings needs a technician base.
5. An operation that is not classified, or that cannot be delegated, is never granted.

A role with no grants and no denials decides exactly like its base role.

Never granted to a role that is not an administrator: `users.*`, `roles.*`, `keys.*`, `password.*`, `auth.resolve`, `package.apply`,
`profile.set`, `config.restore`, `power.full_reset`, `comms.set`, `guard.set`, `db.folder`, `db.delete_previous`, `activity.delete`,
`activity.clear`, `history.delete`, `lights.apply_m950`. (`audit.list` can be granted.) The role file refuses them when saved and
`decide()` ignores them anyway.

## Storage

`workshop-roles.json` next to the users file (`/opt/dsf/conf`, outside the plugin folder; env `WORKSHOP_ROLES`), written atomically:

```json
{"version": 1, "roles": [{"name": "Operador con luces", "base": "operator", "description": "", "grant": ["lights.config"],
                          "deny": ["camera.capture"], "created": "2026-11-06T11:00:00", "updated": "2026-11-06T11:00:00", "updated_by": "Ana"}]}
```

Reading is strict. A file that is not exactly this shape is `damaged` and fails closed: no custom role is known, so the people who have one can
only stop, until an administrator repairs or deletes the file by hand. There is no older copy to fall back to (it could give more than was decided)
and the base roles keep working. There is no migration.

A person stores the exact name of the role in `workshop-users.json`. A role that cannot be found (file deleted or damaged) resolves to `none`:
nothing is allowed but stopping, and the person is not erased from the users file. A role in use cannot be deleted. The last administrator rule
and "nobody changes their own role" are unchanged.

## API

`roles.list`, `roles.get`, `roles.set`, `roles.remove`, `roles.effective` (administrator only, see `docs/api/README.md`). `roles.set` and
`roles.remove` ask for a confirmation; every change is in the audit with the role before and after (`base|grants|denials`). The change reaches the
people who have the role on their next call (the definition is read on every call, not copied into the session).

`auth.whoami` keeps `role` = the base role, so the pages installed before this keep computing the same permissions, and adds `role_name`, `allow`
and `deny` (the operations above / below the base role) for pages that honor them.

## API keys use the same capabilities (phase 5)

An external key (`dsf/api_keys.py`) has operation classes (`kinds`: read, write, motion, stop, power; never admin) and two lists, `ops` (allowed) and
`deny` (refused). Each entry of `ops` / `deny` is now one of:

- an operation name or an fnmatch pattern, exactly as before (`light.*`, `camera.capture`);
- `cap:<id>`: every operation of that capability of `permission_caps.py` (`cap:camera.capture`, `cap:lights.use`). The prefix keeps the two
  meanings apart: four names are BOTH an operation and a capability id (`machine.stop`, `machine.try`, `activity.delete`, `camera.capture`), and a
  bare `camera.capture` in a key has always meant the operation. `keys.create` / `keys.update` accept a bare id that is NOT an operation name
  (`lights.view`) and save it as `cap:lights.view`.

Rules (`api_keys.why_not`, the only implementation: `AuthRegistry._key_allows`, `keys.list` -> `allowed_ops` and `keys.preview` all call it):
1. An operation of kind `admin` is never allowed, by any road.
2. A matching `deny` entry (pattern, name or capability) refuses it. Deny wins. (Unlike a role, a key may deny a stop capability.)
3. A `strict` key never gets an operation that cannot be delegated (`NOT_DELEGABLE`), not by class, not by a pattern such as `*`.
4. Allowed when its class is in `kinds`, or a pattern / name matches, or a `cap:` entry covers it. A capability only gives delegable operations and
   is refused when saved if it is of the admin class or has nothing delegable (`cap:security.keys`, `cap:config.critical`,
   `cap:machine.hardware_params`, ...); an unknown id is refused with "'x' is not a capability". `deny` accepts any capability.

No migration. A key saved before this has no `strict` mark and decides EXACTLY as before (`fixtures/key_decisions_golden.json`: 98 keys x 257
operations, `test_key_golden.py`). That includes a leak that was already there: a key with the class `write` (preset `control` / `full`) reaches
eight operations of kind write that are not delegable, and one with `read` reaches the two of kind read (`activity.delete`, `activity.clear`, `history.delete`, `config.restore`, `db.folder`,
`db.delete_previous`, `power.full_reset`, `lights.apply_m950`; read: `password.status`, `auth.resolve`). A key created now, or whose `kinds` / `ops` / `deny`
are saved again, is `strict` and loses them (a rename alone does not change it). `keys.list` returns `strict` for each key so the page can say it.

`keys.list` returns for each key `allowed_ops` (the operations it may call now) and `cap_prefix`; `keys.preview` (kinds, ops, deny) returns the
same list for permissions not saved yet. The page keeps no copy of the rule.

## Where custom roles are NOT applied yet

The servers the pages call directly (camera relay :8090, Vision :8095, RS485) learn the person through `auth.resolve` and apply the BASE role;
`auth.resolve` also sends `allow` / `deny` so they can honor them later. Inside the service, `motion_owner` (take over) and `machine_config` /
`machine_history` read the role of the caller: `machine_config` follows the custom role, `motion_owner` still uses the base role.

## Groups, attached access profiles and ceilings (access control phase 2)

`workshop-access.json` (next to the users file, env `WORKSHOP_ACCESS`, mode 600, strict, fail closed) holds custom access profiles (up to 5 versions each, one
active), groups, what is attached to each person and the permissions ceiling of a person or a group (`dsf/access_store.py`). Nobody has anything
attached today: a person is governed by the evaluator (`dsf/access_person.py`, `access_eval`) ONLY when they have a profile, a group with profiles or a
ceiling; everybody else is decided by `permissions.decide` exactly as above. A governed person gets: the base profile of their base role + their
custom role as one profile + every attached profile (own and of their groups); every ceiling must allow the call; a deny anywhere wins; stopping
is allowed first; what cannot be delegated is conceded only by a base profile. The base profiles are `base.viewer`, `base.operator`, `base.technician`,
`base.administrator` and `base.viewer_camera`; the prefix `base.` is reserved. `base.administrator` is never attached. A damaged file means no
attachment is known and the base roles decide for everybody.

Operations (administrator only, not delegable, capability `security.access`): `access.profiles.list/get/set/remove`, `access.profile.versions/rollback`,
`access.groups.list/get/set/remove`, `access.attach`, `access.detach`, `access.ceiling.set`, `access.person.get`, `access.check`. Changes ask for a level 3
confirmation and are audited with before and after. Refused: a change that leaves ANY administrator unable to use `access.*`, changing your own
attachments or groups, deleting something in use. The custom roles are listed by `access.groups.*` as read-only groups with one profile (the roles file
is not migrated).

## Targets and conditions of the rules (access control phase 3)

Only for a person the evaluator governs (something attached: a profile, a group with profiles, a ceiling); everybody else is decided by `permissions.decide`, unchanged.

**Targets.** A rule may list `targets` such as `workshop:camera:camera/cam2`. The call must DECLARE its target: `dsf/access_targets.py` has one table, operation to the function that takes the target out of the arguments the caller sent. A call without an entry, or whose argument is missing, declares no target and is evaluated against `workshop:<namespace>:*`, so a `deny` limited to one target does NOT catch it and an `allow` limited to one target does not cover it (on purpose: a sensitive operation has to be in the table). Ids are case sensitive and percent-encoded (a `*` in an id is `%2A`, it never widens a rule); paths lose the drive, the leading slash and the dots, and a relative path is under `gcodes/`. Stopping is never denied, whatever the targets.

| Operations | Argument | Target |
|---|---|---|
| `camera.capture`, `burst`, `flash`, `image.get`, `image.set` | `camera` (empty: `main`) | `workshop:camera:camera/<id>` |
| `camera.edit`, `keep`, `remove`, `rename`, `rerender` | `file` | `workshop:camera:media/<file>` |
| `camera.schedule`, `camera.timelapse` | `name` | `workshop:camera:timelapse/<name>` |
| `lights.scene` | `scene` | `workshop:lights:scene/<id>` |
| `lights.zone` | `strip` (empty: `main`), `index` | `workshop:lights:zone/<strip>/<index>` |
| `lights.apply_m950`, `lights.test`, `lights.identify` | `strip` (empty: `main`) | `workshop:lights:strip/<n>` |
| `lights.test_state` | `state` | `workshop:lights:state/<id>` |
| `lights.pi_test` | `pin` | `workshop:lights:pin/<n>` |
| `layerrecipes.get`, `set`, `remove`, `preview`, `arm` | `name` | `workshop:printing:recipe/<name>` |
| `pelletlayers.get`, `set`, `remove`, `arm` | `name` | `workshop:printing:pellet/<name>` |
| `bedzones.setpoint` | `zone` (none: every zone, no target) | `workshop:printing:bedzone/<n>` |
| `jobs.preview`, `gcodelib.info`, `layers`, `thumbnail`, `forget`, `refresh` | `file` | `workshop:printing:file/<path>` |
| `gcodelib.list` | `dir` (default `gcodes`) | `workshop:printing:folder/<path>` |
| `livejob.interrupted.get`, `discard`, `hide`, `livejob.resume.arm` | `id` | `workshop:workbench:interrupted/<id>` |
| `energy.history`, `energy.period`, `meter.get`, `forget`, `save`, `settings`, `test` | `meter` (empty: no target) | `workshop:power:meter/<key>` |
| `power.timer`, `power.timer_cancel` | none | `workshop:power:timer/shutdown` |
| `power.after_job` | none | `workshop:power:timer/after_job` |
| `vision.get`, `vision.post` | `path` | `workshop:vision:path/<path>` |

Not covered yet: the camera relay on :8090 drops the camera id of the route (a camera cannot be denied there), Vision's own port, RS485 devices, meshes and history records.

**Conditions** (`when`, a closed list; no time, date or address). The context of a governed call is built in `dsf/access_context.py`: `mode` (the mode of the machine), `via` (always `session` on this path), `risk_max` (the risk of the capability of the operation, derived by the evaluator), and `job_running` / `machine_on`, read from `state.status` of the last object model (`job_running`: a file job is on, a paused one included; `machine_on`: the supply is not off, status `off`). With no model, no status, or a model older than `machine_state.WITHOUT_DATA_S`, the two are unknown: the condition does not hold for an `allow` and does hold for a `deny` (it fails closed both ways). `access.check` derives the target of the call from `operation` and `args` when no `target` is given.

## Plugin manifests, interface operation and plugin profiles (access control phase 5)

A plugin is not a namespace of operations: 18 operations are used by two or more plugins and the shared clients name 23 more in every plugin (inventory of phase
0, `Projects/informes/control-acceso/INVENTARIO-PLUGINS.md`). What belongs to a plugin is its SURFACE: opening its page, seeing it in the side bar, the pieces of
its interface. Every plugin therefore carries a `permissions.json` (in TallerPlugins, `src/<Id>/dsf/` or `vue/<Id>/dsf/`: `build.py` puts the whole `dsf/` folder
in the zip and lists it in `dsfFiles`; DSF installs it as `<plugins folder>/<Id>/dsf/permissions.json`; generated by `tools/gen_permissions.py`, never by hand):

```json
{"version": 1,
 "plugin": "WorkshopLights",
 "namespace": "lights",
 "prefixes": ["light", "lights", "statuslight"],
 "ui": "ui:lights:open",
 "operations": ["light.set", "lights.apply_m950", "lights.get", "lights.scene", "view.heartbeat"],
 "shared": ["view.heartbeat"],
 "restricted": ["lights.apply_m950"],
 "targets": ["lights:scene", "lights:zone"],
 "profiles": {
   "readonly": {"title": "LightsReadOnly", "capabilities": ["lights.view"]},
   "operator": {"title": "LightsOperator", "capabilities": ["lights.use", "lights.view"]},
   "admin":    {"title": "LightsAdmin",    "capabilities": ["lights.config", "lights.use", "lights.view"]}},
 "satellite": "vision_access.py"}
```

| Field | Meaning |
|---|---|
| `plugin`, `namespace` | the plugin Id (the folder name) and its access namespace (`[a-z][a-z0-9_]*`; not `cap`, `tier`, `ui`, `base`, `plugin`, `workshop`). `<namespace>:*` in a rule covers everything of the plugin, including its interface operation. |
| `prefixes` | the first segments of the API operations the plugin OWNS. A prefix and a namespace have one owner. |
| `ui` | the interface operation, always `ui:<namespace>:open`. Every base role holds `ui:*:open` (rule `OpenPages`: nobody is stopped from seeing a plugin today); one `deny` silences a plugin. |
| `operations` | every operation of the API the plugin calls (its pages and its own Python server). |
| `shared` | of those, the ones outside its prefixes (another plugin's, or the service's). Anything not under a prefix and not in `shared` is an error, except the COMMON operations. |
| `restricted` | of those, the ones only an administrator may do: not delegable (`permission_caps.NOT_DELEGABLE`) or not classified. They are in no profile. |
| `targets` | `<plugin>:<type>` target types (of `access_targets.TABLE`) the calls of the plugin work on. |
| `profiles` | three base profiles built on capabilities; each holds the capabilities of the lower ones. Titles are `<Plugin>ReadOnly`, `<Plugin>Operator`, `<Plugin>Admin`. |
| `satellite` | optional: the table of the plugin's own server, which keeps deciding what never reaches the API (not covered by this phase). |

COMMON operations (`access_plugin_manifest.COMMON_OPERATIONS`): the clients every plugin shares (session, reserved movement, settings, profile, start-up,
`activity.log`, `risk.*`, `view.heartbeat`). A plugin may call them without declaring them, and every plugin profile holds the ones of its level that can
be delegated, so a deny aimed at one plugin does not break the others.

**Levels.** The level of a capability is the more demanding of its lowest role in `OP_ROLES` and its class and risk: read and stop is `readonly` (always: a read
that asks for operator today, like the camera token, asks for it because of privacy; the plugin package is the deliberate way to give it); write, motion and
power of risk 1 or 2 is `operator`; the rest is `admin`. A capability may not sit in a lower profile than its level, and a capability that cannot be
delegated is in no profile.

**Validation** (`dsf/access_plugin_manifest.py`, pure; `dsf/access_plugin_files.py` reads the folder). Errors: the operation does not exist in the API; it is not
classified in `OP_ROLES` (it stays administrator-only, as before); it is outside the namespace and not declared shared; `shared` or `restricted` lists
something not called, or something that is the plugin's own or delegable; an unknown or non-delegable capability, a capability in a profile below its level,
a profile that does not hold the lower one, an operation no profile covers; a wrong title or interface operation; an unknown target type; a namespace or a prefix
with two owners; a file that is not JSON or is over 64 KB. Information (not an error): an operation that crosses plugins (`cross_plugin`) or belongs to the
service (`no_owner`).

**Operation** `access.plugins.validate` (administrator only, not delegable, no arguments, changes nothing stored): reads the manifests, validates them, and registers the
profiles of the valid ones as `plugin.<namespace>.readonly`, `.operator`, `.admin` (listed by `access.profiles.list` under `plugin`). They are read-only like the base
ones and can be attached to a person or a group, but they are not base profiles: they never concede what cannot be delegated, they cannot be a permissions
ceiling, and a custom profile cannot take the prefix `plugin.`. A manifest with an error registers nothing; a profile whose plugin goes away stays attached
(the file is not damaged) and grants nothing. The registry is refreshed when the access file is opened, on every `access.*` call and by this operation. Only
the people who have something attached are governed, as before.

Not covered by this phase (documented gap): the satellite servers keep their own tables and do not read the manifests: Vision (`vision_access.py`, port 8095),
the camera relay (`camera_access.py`, port 8090) and RS485 (`rs485_access.py`, its own `rs485.*` operations, which are not in the API contract). Neither
WorkshopConfig (stopped, never installed) nor WorkshopModelAgent (its own API, no operation of the service, no table of roles) has a manifest. G-code that
the pages send straight to DWC does not pass through the API, so no profile sees it.
## Last use, review of accesses, report of people and keys, checker (access control phase 6)

Read-only, administrator only, not delegable (capability `security.access`): `access.review`, `access.report`, and the checker `access.check` of phase 2.

**Last use** (`dsf/access_usage.py`). The last time each person used each capability, in `workshop-access-usage.json` next to the access file (env `WORKSHOP_ACCESS_USAGE`; a small JSON file, NOT a database table: `{"version": 1, "used": {"<person casefolded>": {"<capability>": <epoch seconds>}}}`). `identity.AuthRegistry` records an ALLOWED call of a named person, under the capability of its operation, for people governed by the evaluator and for the rest (a refused call, a stop that passed without identity and operations outside every capability leave nothing). Memory first: a pair is stamped at most once a minute and the whole file is written at most once a minute (by the call that finds the interval over, no thread), and at the clean shutdown (`main._clean_stop` -> `access_usage.flush_all`). A missing, damaged or unwritable file never breaks or changes a decision: the dates start empty, the problem is logged once, and the next write replaces the file. At most 3000 pairs. Removing a person forgets their dates.

**Review of accesses** (`dsf/access_review.py`, operation `access.review`). A pure function over a snapshot (`access_report.snapshot`) that returns findings `{code, severity, subject, params, message}`, high severity first. One test per finding (`test_access_review.py`):

| Code | Severity | When |
|---|---|---|
| `profile_grants_risk4` | high | an allow rule of a custom profile names `cap:machine.hardware_params` (or another risk 4 capability with a delegable operation) or matches a delegable operation of risk 4 inside its `risk_max`. Today the hardware key is the one real case |
| `deny_never_matches` | medium | a deny rule that cannot hold: no known operation matches its entries, `risk_max` is below the risk of everything it names, or `via` leaves out `session` (the only way the evaluator decides today). Entries `<ns>:<name>` may be plugin operations the table does not know and are not judged |
| `profile_unattached` | low | a custom profile that nobody and no group has |
| `person_without_access` | info | a person with no group and no profile (the base role alone decides: it is the normal state today) |
| `key_wide_unused` | high | an enabled, unexpired key with 5 or more entries (operation entries plus classes) that was not used for 30 days (a never used key counts from its creation) |
| `admin_no_recent_login` | medium | an administrator who did not sign in for 30 days (never: counted from when they were created) |

With a damaged access file the profile and attachment findings are left out (they cannot be known). The thresholds come back in `limits`. Alerts: the notice system of the service writes activity rows from the code that sees an event; a review is a read on demand and there is no scheduler, so nothing is turned into a notice by itself: the high severity findings are in `access.review` (`high` is their count) for the page of phase 7 to show. No database change.

**Report of people and keys** (`dsf/access_report.py`, operation `access.report`): per person the role, groups, profiles, whether the evaluator governs them, last sign-in, sessions, date and age of the PIN (a PIN never changed counts from the creation of the person), seconds left of a lock (`users.UserStore.lockouts`), the last use of each capability; and each key with creation, last use, uses, expiry, breadth and idle days. Never a PIN, a hash or a key.

**Checker** (`access.check`): returns `allowed`, the `reason` code, `deciding` (the rule that decided, with its profile and id) and `rules`: every rule looked at with `matched` and, for those that did not match, `why` (`operation`, `target` or `condition:<key>`); `legacy` is what the base roles alone would have answered.
