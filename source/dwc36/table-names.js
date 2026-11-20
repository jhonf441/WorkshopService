'use strict'

// Readable names of the tables of the service database (Data > Database). PURE: it returns catalog keys (relative to plugins.WorkshopService), the page
// translates them. The raw table name is the identity the service lists (dsf/db.py database_state reads sqlite_master); it is only drawn as quiet code.
//
//   TABLES            every table the service can create (db.py, audit_chain.py, health_history.py, install_log.py)
//   tableLabel(name)  { key, what, code }: the key of the name, the key of its one-line description, the raw name. Unknown table: key and what are null

export const TABLES = Object.freeze({
	activity: { key: 'database.activity_jobs_modes_alerts', what: 'database.table_activity_what' },
	consumption: { key: 'database.energy_meter_readings', what: 'database.table_consumption_what' },
	commands: { key: 'common.received_commands', what: 'database.table_commands_what' },
	audit: { key: 'database.table_audit', what: 'database.table_audit_what' },
	audit_chain: { key: 'database.table_audit_chain', what: 'database.table_audit_chain_what' },
	audit_detail: { key: 'database.table_audit_detail', what: 'database.table_audit_detail_what' },
	audit_alarm_state: { key: 'database.table_audit_alarm_state', what: 'database.table_audit_alarm_state_what' },
	health_samples: { key: 'database.table_health_samples', what: 'database.table_health_samples_what' },
	install_runs: { key: 'database.table_install_runs', what: 'database.table_install_runs_what' },
	install_actions: { key: 'database.table_install_actions', what: 'database.table_install_actions_what' }
})

export function tableLabel(name) {
	const n = String(name === undefined || name === null ? '' : name)
	const t = Object.prototype.hasOwnProperty.call(TABLES, n) ? TABLES[n] : null
	return { key: t ? t.key : null, what: t ? t.what : null, code: n }
}
