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
