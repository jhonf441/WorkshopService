# Architecture debt that the frozen lists record on purpose

`dsf/golden/architecture_frozen.json` may only shrink (tools/freeze_architecture.py refuses to add or raise anything). Two moments are
exceptions that were accepted by hand, with the cause written here so they are not read as a regression.

## The import cycle grew by 8 modules in phase 5, group 1 (2026-11-10)

The five read handlers (activity_query, commands_query, blackbox, consumption_query, jobs_view) were loaded BY PATH, so no module imported
them and the cycle scanner could not see them. They are now importable modules (`activity_history`, `commands_history`, `black_box_view`,
`consumption_history`, `jobs_preview`) registered by L5 modules (`activity_ops`, `energy_ops`, `jobs_ops`). Because `api_ops` imports the
L5 modules and these touch `db` / `messages`, which are inside the big cycle, they joined it: `activity_history`, `activity_ops`,
`commands_history`, `black_box_view`, `consumption_history`, `energy_ops`, `jobs_preview`, `jobs_ops`. The runtime coupling was already there
(the handlers imported `db` and `messages` too); the scanner can see it now. Behaviour did not change.

Every later handler conversion of phase 5 will add its modules the same way until the cycle is broken. The real fix is to cut the upward
edges from lower layers into `api_ops` and the inner imports of `db` / `messages`:

- `camera_control.py:72` (`import api_ops` inside a function), `guard_api.py:10` (`api_ops._ctx`), `interlocks` and similar;
- the inner imports of `db.py` (`health_history`, `install_log`, `messages`) and of `messages.py` (`machine_state`).

Until then a new importable module that touches `db` or `messages` and is registered from `api_ops` lands in `cycles`. Add it with the
reason in this file; do not hide it.

## The import cycle grew by 6 more modules in phase 5, group 2 (2026-11-10)

The handlers of the "settings" group (consumption_tariff, notifications, service_modules, base) became typed modules registered by L5
modules, the same way as in group 1, and they joined the big cycle for the same reason (they touch `db`, `messages`, `activity` or
`notifier`, and `api_ops` imports their `*_ops` module): `consumption_tariff` (registered by `energy_ops`), `notifications_config` and
`notifications_ops`, `module_modes` and `db_admin` (registered by the new `service_ops`), and `service_ops`. Behaviour did not change.
The renamed debt lines are not new debt: `handlers/consumption_tariff->activity` is now `consumption_tariff->activity` and the inner import
of `machine_profile` in `consumption_tariff` became a top-level import. The cure is the same as for group 1.

## The import cycle grew by 2 more modules in phase 5, group 3 (2026-11-10)

The lights handlers (`lights`, `light`, `statuslight`) became typed modules: `lights_profile` (cleaning, state, lights.g, M950), `lights_edit`
(save, zone, scene, schedule, import, apply_m950), `lights_probe` (test, identify, animation, preview, test_state, Pi pins), `lights_macros`
(light.set, statuslight.set) and the L5 table `lights_ops`. Two of them joined the big cycle for the same reason as before: `lights_edit`
(it imports `activity`, which touches `db`) and `lights_ops` (imported by `api_ops`). Behaviour did not change. The renamed debt lines are not
new debt: `handlers/lights->activity` is now `lights_edit->activity`, the threads and the `os.replace` calls moved with their code, and the
inner imports of the old handler became top-level imports (the entries went away). The cure is the same as for group 1.

## The import cycle grew by 5 more modules in phase 5, group 4 (2026-11-10)

The power handlers (`shutdown`, `shutdown_all`, `reset_all`) became typed modules: `power_config` (power.after_job / timer / timer_cancel /
method), `power_off` (power.off) and `power_reset` (power.full_reset), registered by the new L5 table `power_ops`. They joined the big cycle
for the same reason as before (`activity` touches `db` / `messages`, and `api_ops` imports `power_ops`): `power_config`, `power_off`,
`power_reset`, `power_ops` and `shutdown_method` (it is now reached from `power_config`, which `shutdown_timer` imports at the top).
Behaviour did not change. The renamed debt lines are not new debt: `handlers/shutdown->activity`, `handlers/shutdown_all->activity` and
`handlers/reset_all->activity` are now `power_config->activity`, `power_off->activity` and `power_reset->activity`; the `subprocess` and
inner-import entries moved with their code (`power_off` keeps its inner imports and its lazy `tinytuya`, so importing `api_ops` still works on a machine without the Tuya library). `shutdown_timer` arms the power off
after a job through `power_config.after_job` instead of loading `handlers/shutdown.py`. The cure is the same as for group 1.
