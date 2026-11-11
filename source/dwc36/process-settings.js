'use strict'

// One owner per setting (design of 2026-11-07, informes/ui-capturas-26/E-servicio.md section 3): a rule that only ONE process uses lives in
// the row of that process on the "Processes and automations" page; the card "Automations" keeps what affects several processes or the
// whole machine (shutdown when the job ends, protected movement, the live job, the load on the board) and, for what moved, one summary
// line with the state and a link to the row (no second switch). Pure functions, no Vue, no texts (tests/process-settings.test.js).
//
//   interceptor   -> 'air'       the automatic air with the laser (switch + delay after M5): operations air.auto / air.delay (operator)
//   status_light  -> 'lights'    the status lights: read only here, the owner is the Lights and status page (link)
//   bed_zones     -> 'bed_zones' the bed zones on / off (`enabled` of the configuration): bedzones.get / bedzones.set (technician)
//   camera        -> 'relay'     the camera relay: RelayCard.vue already lives in the row (the model this follows)

export const SETTING_OF = { interceptor: 'air', status_light: 'lights', bed_zones: 'bed_zones', camera: 'relay' }
export const GLOBAL_RULES = ['poweroff', 'motion', 'live_job', 'board_load']
// the operation whose role gates the control of each setting and the role it needs (for the ONE reason under the group)
export const SETTING_OPS = { air: { op: 'air.auto', need: 'operator' }, bed_zones: { op: 'bedzones.set', need: 'technician' } }
export const DELAY_BASE = [0, 2, 5, 10, 30]

// the setting a process row holds, or '' (most rows hold none)
export function settingOf(p) {
	return (p && SETTING_OF[p.id]) || ''
}

// the setting a row of the page draws by itself (not 'relay': RelayCard.vue is already there)
export function rowSetting(p) {
	const s = settingOf(p)
	return s === 'relay' ? '' : s
}

// the air rule as the service publishes it (plugin data airAssist, airAssistAuto, airAssistDelay): a missing value means the old default
export function airView(data) {
	const d = data || {}
	const delay = d.airAssistDelay == null ? 2 : Number(d.airAssistDelay)
	return { on: !!d.airAssist, auto: d.airAssistAuto == null ? true : !!d.airAssistAuto, delay, options: delayOptions(delay) }
}

// the delays offered: the fixed ones plus the one in use when it is not among them (so the chip of the current value always exists)
export function delayOptions(current) {
	const base = DELAY_BASE.slice()
	return base.includes(current) ? base : base.concat(current).sort((x, y) => x - y)
}

// the status lights as the service publishes them (statusLightAuto) and whether the Lights plugin is there (the link only exists then)
export function lightsView(data, pluginActive) {
	const d = data || {}
	return { auto: d.statusLightAuto == null ? true : !!d.statusLightAuto, active: !!pluginActive }
}

// what bedzones.get answered -> { enabled, rev, zones, problems }; null while nothing was read
export function zonesView(res) {
	if (!res || typeof res !== 'object' || !res.config) return null
	const c = res.config
	return { enabled: c.enabled === true, rev: String(res.rev == null ? '0' : res.rev), zones: Array.isArray(c.zones) ? c.zones.length : 0, problems: Array.isArray(res.problems) ? res.problems.length : 0 }
}

// the arguments of bedzones.set that only flip `enabled` and keep the rest of the configuration as it was read (base_rev = the rev read)
export function zonesToggle(res, enabled) {
	if (!res || typeof res !== 'object' || !res.config) return null
	return { config: Object.assign({}, res.config, { enabled: !!enabled }), base_rev: String(res.rev == null ? '0' : res.rev) }
}

// what a failed save shows next to the control, from what api() resolved (its result or message; an old handler may answer "Error: ...")
// or the error it threw (its code says the cause): { kind: 'role'|'session'|'conflict'|'error', text } or null when it went fine
export function saveFailure(text, err) {
	if (err) {
		if (err.code === 'cancelled') return null
		if (err.code === 'forbidden') return { kind: 'role', text: '' }
		if (err.code === 'login_required') return { kind: 'session', text: '' }
		if (err.code === 'conflict') return { kind: 'conflict', text: String(err.message || '') }
		return { kind: 'error', text: String((err && err.message) || err) }
	}
	const s = String(text == null ? '' : text).trim()
	if (/^Error:/i.test(s)) return { kind: 'error', text: s.replace(/^Error:\s*/i, '') }
	return null
}
