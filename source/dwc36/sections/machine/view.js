'use strict'

// Machine, as a pure view of what the service publishes: the choices a segment offers, the rows of the guard, the 14 channels, the
// arguments of the bed zones save. No Vue, no texts (the screens say the words), no clock.

const IDLE_BASE = [15, 30, 60]       // seconds; 0 ("never") always goes last
const DELAY_BASE = [0, 2, 5, 10, 20]
export const DELAY_MAX_S = 60
export const IDLE_MAX_S = 3600

// the base choices plus the value in use when it is not one of them (so the current value always has its own button)
function withCurrent(base, current) {
	const list = base.slice()
	if (typeof current === 'number' && list.indexOf(current) < 0 && current !== 0) list.push(current)
	return list.sort((a, b) => a - b)
}

export function idleChoices(current) {
	return withCurrent(IDLE_BASE, current).concat([0])
}

export function delayChoices(current) {
	return withCurrent(DELAY_BASE, current)
}

// "7,5" / "7.5" / " 12 " -> a number from 0 to 60, or null (empty, negative, over the limit, text)
export function parseDelay(text) {
	const s = String(text === undefined || text === null ? '' : text).trim().replace(',', '.')
	if (!/^\d+(\.\d+)?$/.test(s)) return null
	const n = Number(s)
	return n >= 0 && n <= DELAY_MAX_S ? n : null
}

// a time in seconds as the short choice text parts: { n, unit: 's' | 'min' }
export function secondsParts(s) {
	return s >= 60 && s % 60 === 0 ? { n: s / 60, unit: 'min' } : { n: s, unit: 's' }
}

const WORD = { ok: 'fine', rest: 'resting' }
const FIRST = ['fire', 'servo']

// what the guard watches, fire and servo first: [{ id, protects, word: 'fine' | 'resting' | 'down', level: 'ok' | 'rest' | 'error', title }]
export function guardRows(guard) {
	const list = ((guard && guard.watches) || []).map((w, i) => {
		const word = WORD[w.state] || 'down'
		// the service says WHY it rests when it knows: no device of the plugin is configured (grey, not an alarm)
		return { id: w.id, protects: w.protects || '', word, why: w.state === 'rest' && w.why ? w.why : null, level: word === 'fine' ? 'ok' : word === 'resting' ? 'rest' : 'error', title: w.title || null, at: i }
	})
	const rank = r => { const k = FIRST.indexOf(r.protects); return k < 0 ? FIRST.length : k }
	return list.sort((a, b) => rank(a) - rank(b) || a.at - b.at)
}

export function guardSummary(rows) {
	const out = { total: rows.length, down: 0, resting: 0, fine: 0 }
	rows.forEach(r => { out[r.word] += 1 })
	return out
}

// the first (up to) two protections, named, for the summary of the fold ("Fire (Vision), servo (RS485) and 8 more")
export function guardLead(rows) {
	return rows.slice(0, 2).map(r => r.protects)
}

// the 14 channels as the table draws them: state word key, whether it can be chosen, who uses it now
export function channelRows(comm) {
	const c = comm || {}
	return ((c.channels || []).filter(x => x && x.exists !== false && x.state !== 'no_exists')).map(x => ({
		id: x.id, state: x.state || 'free', eligible: x.eligible === true, usage: x.usage || null, reason: x.reason || null,
		service: x.id === c.channel, jog: x.id === c.channel_jog
	}))
}

export function channelCounts(rows) {
	const out = { free: 0, busy: 0, shared: 0, reserved: 0 }
	rows.forEach(r => { if (out[r.state] !== undefined) out[r.state] += 1 })
	return out
}

// the choices of a channel select: Automatic and the ones that can be chosen now (the one in use is kept so the select never shows a blank)
export function channelChoices(rows, current) {
	const ids = rows.filter(r => r.eligible).map(r => r.id)
	if (current && current !== 'auto' && ids.indexOf(current) < 0) ids.push(current)
	return ['auto'].concat(ids)
}

// bedzones.set arguments that change only `enabled` and keep the rest as it was read; `rev` overrides the revision (keep mine after a conflict)
export function zonesArgs(read, enabled, rev) {
	if (!read || typeof read !== 'object' || !read.config) return null
	return { config: Object.assign({}, read.config, { enabled: !!enabled }), base_rev: String(rev === undefined || rev === null ? (read.rev === undefined || read.rev === null ? '0' : read.rev) : rev) }
}

export function zonesInfo(read) {
	if (!read || !read.config) return null
	const c = read.config
	return { enabled: c.enabled === true, zones: Array.isArray(c.zones) ? c.zones.length : 0, problems: Array.isArray(read.problems) ? read.problems.length : 0 }
}

// what the relay is, for a person who may not read camera.status: the camera process of the service (servicesInternal.processes.camera)
// 'running' | 'resting' | 'stopped' | 'unknown'
export function relayState(status, processWord) {
	if (status) return status.running ? 'running' : status.configured === false ? 'nocam' : 'stopped'
	if (processWord === 'resting') return 'resting'
	if (processWord === 'stopped') return 'stopped'
	return processWord ? 'running' : 'unknown'
}
