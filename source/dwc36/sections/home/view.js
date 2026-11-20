'use strict'

// What the home says, worked out from plain data (pure: no store, no language, no clock). The same functions feed the verdict of the
// home, the status chip of the header and the counts of the navigation, so the three can never tell different numbers.
//
//   attentionRows(input, canOpen)  the ONE list of what needs a look: [{ id, level: 'error' | 'warn', key, n, params, service, to }]
//                                  key = text of the row (area `home`), n = its count when it has one (plural), service = a text the
//                                  service wrote ({ key, params }: shown as it is), to = the place that fixes it (null: informative).
//                                  A row whose place the person cannot open is neither drawn nor counted: canOpen(place) decides.
//   verdict(state, rows)           { level: 'ok' | 'warn' | 'error', key, n } by the fixed order: stopped, restarting, no data, fault,
//                                  attention, all fine. n = the rows of the list.
//   badges(rows)                   { sectionId: how many rows are fixed there }
//   movementKey(state)             the key of the word for who has the movement (seven states of the service)
//   minutesLeft(missingS)          the minutes shown for a countdown (never seconds: the text must not jump every tick)
//   timerMinutes(text)             the number a person typed for "power off in a while": 1..720 whole minutes, else null
//
// input: { processes: [{ level }], guard, risk, communication, health, box, modules, readinessPending (number | null),
//          session: { configured, usersOff, damaged }, chainBroken }  -- every part may be null (not published yet).

const place = (s, t, a) => ({ s, t: t || '', a: a || '' })

export const TO = Object.freeze({
	processes: place('health', 'processes'), shutdowns: place('health', 'shutdowns'), comms: place('machine', 'comms'), db: place('data', 'db'),
	backups: place('data', 'backups'), bridge: place('links', 'bridge'), setup: place('setup', 'status'), accessSettings: place('access', 'settings'),
	accessPeople: place('access', 'people'), accessProfiles: place('access', 'profiles'), securityActivity: place('security', 'activity')
})

export const BRIDGE_UNIT = 'workshop-gcode-bridge'
export const TIMER_MIN = 1
export const TIMER_MAX = 720

function processRows(states, add) {
	const stopped = states.filter(s => s.level >= 2).length
	const notice = states.filter(s => s.level === 1).length
	if (stopped) add('processes_stopped', 'error', TO.processes, { n: stopped })
	if (notice) add('processes_notice', 'warn', TO.processes, { n: notice })
}

function guardRows(guard, add) {
	if (!guard) return
	const down = Array.isArray(guard.down) ? guard.down.length : 0
	if (down) add('safety_down', 'error', TO.processes, { n: down })
	else if (guard.degraded || guard.enabled === false) add(guard.enabled === false ? 'guard_off' : 'guard_degraded', 'warn', TO.processes)
}

function dataRows(health, box, add) {
	const base = health && health.base
	if (base && base.check && base.check !== 'ok') add('database_damaged', 'error', TO.db)
	const backup = base && base.backup
	if (backup && backup.active === false) add('backups_off', 'warn', TO.backups)
	else if (backup && (backup.late || (Array.isArray(backup.failures) && backup.failures.length))) add('backups_late', 'warn', TO.backups)
	if (box && box.report) add('unclean_shutdown', 'warn', TO.shutdowns, { params: { when: box.report.last_datum || '' } })
	const bridge = health && Array.isArray(health.services) ? health.services.find(s => s && s.unit === BRIDGE_UNIT) : null
	if (bridge && bridge.active === false) add('bridge_stopped', 'warn', TO.bridge)
}

function accessRows(input, add) {
	const s = input.session || {}
	if (s.damaged) add('access_damaged', 'error', TO.accessProfiles)
	if (s.configured === false) add('no_people', 'warn', TO.accessPeople)
	else if (s.usersOff) add('roles_off', 'warn', TO.accessSettings)
	if (input.chainBroken) add('chain_broken', 'error', TO.securityActivity)
}

export function attentionRows(input, canOpen) {
	const x = input || {}
	const rows = []
	const add = (id, level, to, more) => {
		if (to && typeof canOpen === 'function' && !canOpen(to)) return
		rows.push(Object.assign({ id, level, key: 'attn_' + id, n: null, params: {}, service: null, to: to || null }, more || {}))
	}
	guardRows(x.guard, add)
	processRows(Array.isArray(x.processes) ? x.processes : [], add)
	;(Array.isArray(x.risk) ? x.risk : []).forEach((r, i) => add('risk', 'warn', null, { id: 'risk-' + (r.id || i), key: 'attn_risk', service: r.text || null, params: { until: r.until || null } }))
	// the service always sends a fixed warning about changing the channel by hand: only its NOTICES say that something is wrong now
	const com = x.communication
	if (com && Array.isArray(com.notices) && com.notices.length) add('communication', 'warn', TO.comms, { service: com.notices[0] })
	dataRows(x.health, x.box, add)
	const modules = x.modules || {}
	const pending = Object.keys(modules).filter(k => modules[k] && modules[k].pending_restart).length
	if (pending) add('pending_restart', 'warn', TO.processes, { n: pending })
	if (typeof x.readinessPending === 'number' && x.readinessPending > 0) add('setup_pending', 'warn', TO.setup, { n: x.readinessPending })
	accessRows(x, add)
	// the failures first, each group in the order above
	return rows.filter(r => r.level === 'error').concat(rows.filter(r => r.level !== 'error'))
}

export function verdict(state, rows) {
	const s = state || {}
	const list = rows || []
	if (!s.running) return { level: 'error', key: 'verdict_stopped', n: 0 }
	if (s.restarting) return { level: 'warn', key: 'verdict_restarting', n: 0 }
	if (s.noSession) return { level: null, key: 'verdict_nosession', n: 0 }      // nobody may look: nothing is known, so nothing is "in order"
	if (!s.hasData) return { level: 'warn', key: 'verdict_no_data', n: 0 }
	if (list.some(r => r.level === 'error')) return { level: 'error', key: 'verdict_fault', n: list.length }
	if (list.length) return { level: 'warn', key: 'verdict_attention', n: list.length }
	if (s.unchecked) return { level: 'warn', key: 'verdict_unchecked', n: 0 }      // a read that failed is not "nothing pending"
	return { level: 'ok', key: 'verdict_ok', n: 0 }
}

export function badges(rows) {
	const out = {}
	;(rows || []).forEach(r => { if (r.to) out[r.to.s] = (out[r.to.s] || 0) + 1 })
	return out
}

const MOVEMENT = ['free', 'stopped', 'file_job', 'file_paused', 'bridge_active', 'live_active', 'live_idle']

export function movementKey(state) {
	return MOVEMENT.indexOf(state) >= 0 ? 'move_' + state : 'move_unknown'
}

export function minutesLeft(missingS) {
	const s = Number(missingS)
	return isFinite(s) && s > 0 ? Math.ceil(s / 60) : 0
}

export function timerMinutes(text) {
	const raw = String(text === null || text === undefined ? '' : text).trim()
	if (!/^\d{1,3}$/.test(raw)) return null
	const n = Number(raw)
	return n >= TIMER_MIN && n <= TIMER_MAX ? n : null
}

// the total of steps of the start-up still to review, from readiness.list ({ plugins: { id: { pending, total } } }); null = not known
export function readinessPending(data) {
	const plugins = data && data.plugins
	if (!plugins || typeof plugins !== 'object') return null
	return Object.keys(plugins).reduce((n, id) => n + (Number(plugins[id] && plugins[id].pending) || 0), 0)
}
