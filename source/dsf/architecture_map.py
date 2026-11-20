"""
Layer of every production module of dsf/ (phase 0 of the redesign plan: architect's report, section 2.1).

No code reads this at run time: test_architecture.py does. It declares the layers the code is going to be moved towards, and
the test freezes today's violations so they can only go down. Nothing is moved and nothing behaves differently because of it.

Layers (a layer imports only from the ones below it):
  L0 kernel        paths, fs_atomic, messages (i18n), job_states, ports, dsf_compat
  L1 platform      the link to DSF (publisher, model subscription, communication), the stores (db, settings, users, roles, keys),
                   the bridge contract, small readers of the machine and the Pi
  L2 runtime       heartbeats, gating of the processes, counters, black box, who is looking
  L3 safety core   motion owner, laser guard, interlocks, protection guard, risk rules, configuration guard
  L4 features      jog, lights, camera, energy, motors, machine, printing, activity, health, startup + SD, live job
  L5 api           the transport, identity and permissions, the tables of operations
  L6 composition   main.py (wiring), bootstrap.py (the start-up sequence)

Keys are the file name without .py for dsf/*.py, and "handlers/<name>" for dsf/handlers/*.py (the internal implementation
of the operations, loaded by path, never imported by name). A production module that is not here makes the test fail.
FEATURE_OF names the feature of each L4 module (rule 2 of 2.1: features do not import each other).
"""

_LAYERS = {
    "L0": (
        "paths", "sd_paths", "fs_atomic", "service_log", "messages", "job_states", "ports", "dsf_compat", "mode_paths", "boards_table",
        "camera_proto", "gcodelib_geo", "net_guard", "architecture_map", "api_docs", "api_admin_reading", "access_rev", "clock", "gcode_classes", "os_gateway", "board_reply",
    ),
    "L1": (
        "publisher", "machine_state", "listener_channel", "communication", "db", "db_dates", "db_schema", "db_conn", "audit_chain", "audit_store", "audit_settings", "config_store", "settings_store", "service_settings", "users", "role_store", "api_keys",
        "bridge_contract", "real_mode", "cpu_meter", "capabilities", "capabilities_io", "machine_profile", "work_state",
        "sd_manifest", "native_merge", "health_history", "install_log", "published_texts", "gcode_temps", "tuya_meter",
        "bed_zones_mirror", "laser_correction", "focus_geometry", "lights_config", "gcodelib_files", "gcodelib_kind", "gcodelib_thumb",
    ),
    "L2": (
        "heartbeats", "ipc_stats", "black_box", "viewers", "service_modules", "process_catalog", "service_restart",
        "stopped_plugins", "origin_track", "lights_counters", "service_context", "process_registry",
    ),
    "L3": (
        "motion_owner", "laser_guard", "interlocks", "protection_guard", "guard_probes", "risk_rules", "config_guard",
        "intercept_watchdog",
    ),
    "L4": (
        # jog
        "jog_move", "jog_pure", "frame_ops", "big_piece", "modes_move", "handlers/jog", "handlers/big_piece",
        # lights and status
        "lights_runtime", "status_light", "lights_decide", "lights_board", "lights_frame", "lights_output", "lights_loop", "pi_leds", "lights_macros", "lights_profile", "lights_edit", "lights_probe",
        "handlers/airassist",
        # camera
        "camera_relay", "camera_access", "camera_assembly", "camera_captures", "camera_config", "camera_context",
        "camera_control", "camera_http", "camera_image", "camera_key", "camera_limits", "camera_load", "camera_notice",
        "camera_sources", "camera_timelapse", "timelapse_look", "handlers/camera_relay", "handlers/vision_call",
        # energy, shutdown
        "consumption_poller", "meters", "shutdown_method", "shutdown_timer", "handlers/consumption_meter",
        "handlers/consumption_period", "consumption_history", "consumption_tariff", "power_config",
        "power_off", "power_reset",
        # motors
        "motor_poller", "motor_status", "motors_enable", "handlers/motors",
        "tmc_decode", "m122_parse", "driver_reads", "motor_report",
        # machine (v2)
        "machine_bedcal", "machine_bedcal_plan", "machine_heater_save",
        "machine_bed_edit", "machine_beds", "machine_file", "machine_calc", "machine_config", "machine_cross", "machine_diff", "machine_gcode",
        "machine_geometry", "machine_height", "machine_heightmap", "machine_history", "machine_layout", "machine_level",
        "machine_limits", "machine_maint_poller", "machine_maintenance", "machine_measure", "machine_mesh", "machine_motion",
        "machine_odometer", "machine_offsets", "machine_ops", "machine_overview", "machine_parsers", "machine_patch",
        "machine_patch_motion", "machine_plans", "machine_plans_motion", "machine_power", "machine_probe",
        "machine_procedures", "machine_report", "machine_safety", "machine_sensors", "machine_shaping", "machine_store", "machine_testmove",
        "machine_tool", "machine_try", "machine_try_kinds", "machine_tune", "machine_verify", "machine_workarea",
        "pid_trace", "handlers/pid_zones", "handlers/config",
        # printing (zones, pellet, recipes, G-code library)
        "bed_estimates", "bed_zones", "bed_zones_config", "bed_zones_geometry", "bed_zones_intercept", "layer_recipes",
        "layer_recipes_file", "layer_recipes_plan", "layer_recipes_preview", "layer_recipes_run", "layer_recipes_state",
        "pellet_layers", "pellet_layers_run", "gcode_plan", "gcodelib_cache", "gcodelib_indexer", "gcodelib_parse",
        "gcodelib_samples", "zones_history",
        # activity and notices
        "activity", "event_watcher", "notifier", "extra_commands", "db_backup", "activity_history", "db_admin",
        "black_box_view", "commands_history", "handlers/log", "notifications_config", "handlers/risk", "handlers/beep",
        # health and services
        "health_poller", "bridge_service", "bridge_watchdog", "handlers/bridge_probe", "handlers/bridge_service",
        "handlers/communication", "handlers/processes", "module_modes", "handlers/password",
        # startup, SD, configuration package
        "startup_plan", "startup_summary", "sd_files", "sd_integrity", "sd_restore", "sd_view", "sd_pending", "examples", "config_package",
        "config_scan", "preflight", "preflight_cli", "handlers/examples",
        # live job and jobs
        "live_job", "live_job_stop", "job_poller", "job_trace", "trace_since", "handlers/job", "jobs_preview",
    ),
    "L5": (
        "workshop_api", "identity", "permissions", "permission_caps", "access_profile", "access_base", "access_eval", "access_store", "access_person", "access_targets", "access_context", "access_admin", "access_ops", "access_plugin_files", "access_plugin_manifest", "access_report", "access_review", "access_usage", "audit", "audit_alarms", "audit_reads", "audit_ops", "api_macros", "api_ops", "api_users", "handler_refusal",
        "roles_ops", "settings_ops", "profile_ops", "startup_ops", "bed_zones_ops", "bed_calibration_ops", "layer_recipes_ops", "gcodelib_ops",
        "pellet_layers_ops", "guard_api", "activity_ops", "energy_ops", "notifications_ops", "service_ops", "jobs_ops", "lights_ops", "power_ops",
    ),
    "L6": ("main", "bootstrap"),
}

# L4 module -> feature (the groups of the comments above)
_FEATURES = {
    "jog": ("jog_move", "jog_pure", "frame_ops", "big_piece", "modes_move", "handlers/jog", "handlers/big_piece"),
    "lights": ("lights_runtime", "status_light", "lights_decide", "lights_board", "lights_frame", "lights_output", "lights_loop", "pi_leds", "lights_macros", "lights_profile", "lights_edit", "lights_probe",
               "handlers/airassist"),
    "camera": ("camera_relay", "camera_access", "camera_assembly", "camera_captures", "camera_config", "camera_context",
               "camera_control", "camera_http", "camera_image", "camera_key", "camera_limits", "camera_load", "camera_notice",
               "camera_sources", "camera_timelapse", "timelapse_look", "handlers/camera_relay", "handlers/vision_call"),
    "energy": ("consumption_poller", "meters", "shutdown_method", "shutdown_timer", "handlers/consumption_meter",
               "handlers/consumption_period", "consumption_history", "consumption_tariff",
               "power_config", "power_off", "power_reset"),
    "motors": ("motor_poller", "motor_status", "motors_enable", "handlers/motors", "tmc_decode", "m122_parse", "driver_reads", "motor_report"),
    "machine": ("machine_bedcal", "machine_bedcal_plan", "machine_heater_save", "machine_bed_edit", "machine_beds", "machine_file", "machine_calc", "machine_config", "machine_cross", "machine_diff",
                "machine_gcode", "machine_geometry", "machine_height", "machine_heightmap", "machine_history", "machine_layout",
                "machine_level", "machine_limits", "machine_maint_poller", "machine_maintenance", "machine_measure",
                "machine_mesh", "machine_motion", "machine_odometer", "machine_offsets", "machine_ops", "machine_overview",
                "machine_parsers", "machine_patch", "machine_patch_motion", "machine_plans", "machine_plans_motion",
                "machine_power", "machine_probe", "machine_procedures", "machine_report", "machine_safety", "machine_sensors", "machine_shaping",
                "machine_store", "machine_testmove", "machine_tool", "machine_try", "machine_try_kinds", "machine_tune",
                "machine_verify", "machine_workarea", "pid_trace", "handlers/pid_zones", "handlers/config"),
    "printing": ("bed_estimates", "bed_zones", "bed_zones_config", "bed_zones_geometry", "bed_zones_intercept", "layer_recipes",
                 "layer_recipes_file", "layer_recipes_plan", "layer_recipes_preview", "layer_recipes_run",
                 "layer_recipes_state", "pellet_layers", "pellet_layers_run", "gcode_plan", "jobs_preview", "gcodelib_cache",
                 "gcodelib_indexer", "gcodelib_parse", "gcodelib_samples", "zones_history"),
    "activity": ("activity", "event_watcher", "notifier", "extra_commands", "db_backup", "activity_history",
                 "db_admin", "black_box_view", "commands_history", "handlers/log", "notifications_config",
                 "handlers/risk", "handlers/beep"),
    "health": ("health_poller", "bridge_service", "bridge_watchdog", "handlers/bridge_probe", "handlers/bridge_service",
               "handlers/communication", "handlers/processes", "module_modes", "handlers/password"),
    "startup": ("startup_plan", "startup_summary", "sd_files", "sd_integrity", "sd_restore", "sd_view", "sd_pending", "examples",
                "config_package", "config_scan", "preflight", "preflight_cli", "handlers/examples"),
    "live_job": ("live_job", "live_job_stop", "job_poller", "job_trace", "trace_since", "handlers/job"),
}


def _invert(groups):
    out = {}
    for group, modules in groups.items():
        for m in modules:
            if m in out:
                raise ValueError("module %s is declared twice (%s and %s)" % (m, out[m], group))
            out[m] = group
    return out


LAYER_OF = _invert(_LAYERS)
FEATURE_OF = _invert(_FEATURES)
LAYER_ORDER = ("L0", "L1", "L2", "L3", "L4", "L5", "L6")
