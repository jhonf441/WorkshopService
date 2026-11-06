'use strict'

// "Processes and automations": how the processes are sorted into the five groups, filtered and counted. Pure functions, no Vue and no
// texts, so a test can feed them every case (tests/processes-groups.test.js). The page builds ONE list of items (the internal processes
// and the separate services: Vision, RS485, the bridge, the database) and these functions do the rest.
//
// An item is { id, group, locked, state: { level }, restarts, search, ... }:
//   group    'safety' | 'machine' | 'data' | 'support' | 'ext'; anything else (a service older than the groups) is 'support'
//   state    level 0 fine (idle included), 1 warning (late, no data, with errors), 2 problem (stopped); `idle` marks the resting ones
//   search   everything a person may type to find it (the page builds it, it holds translated words)

export const GROUP_IDS = ['safety', 'machine', 'data', 'support', 'ext']
export const FILTER_IDS = ['all', 'problems'].concat(GROUP_IDS)
export const PAUSED_FILTER = 'paused' // shown as a pill only while at least one process is paused (activeFilterIds)

export function groupOf(item) {
	const g = item && item.group
	return GROUP_IDS.indexOf(g) >= 0 ? g : 'support'
}

// the looks of a process: 'paused' (calm, set by a person, it ticks), 'ok', 'late' (orange: late, no data, with errors), 'bad' (red: stopped, a real failure), 'idle' (gray: no plugin needs it)
export function stateKey(item) {
	const s = (item && item.state) || {}
	if (s.level >= 2) return 'bad'
	if (pauseKey(item)) return 'paused'
	if (s.level === 1) return 'late'
	return item && item.idle ? 'idle' : 'ok'
}

// what the "with problems" filter keeps: a warning, a failure or a process that had to be relaunched
export function isProblem(item) {
	if (pauseKey(item) && !(((item.state || {}).level || 0) >= 2)) return false // paused on purpose: calm, not a problem
	return !!item && (((item.state || {}).level || 0) > 0 || (item.restarts || 0) > 0)
}

// does the item pass the filter ('all', 'problems' or a group id) and the text? `match(text, query)` is search.js matches()
export function passes(item, filter, query, match) {
	if (filter === 'problems' && !isProblem(item)) return false
	if (filter === PAUSED_FILTER && !pauseKey(item)) return false
	if (GROUP_IDS.indexOf(filter) >= 0 && groupOf(item) !== filter) return false
	return match ? match(item.search || '', query || '') : true
}

// The groups that have something to show, in the fixed order. `items` of each group is what passes the filter; `total` and `ok` count
// the whole group (how many are on time out of how many), so a filter does not change the numbers of the header.
export function buildGroups(items, filter, query, match) {
	const all = items || []
	return GROUP_IDS.map(id => {
		const own = all.filter(i => groupOf(i) === id)
		return {
			id,
			total: own.length,
			ok: own.filter(i => ((i.state || {}).level || 0) === 0).length,
			problems: own.filter(isProblem).length,
			items: own.filter(i => passes(i, filter, query, match))
		}
	}).filter(g => g.items.length)
}

// "n of m watched and on time" of the Safety tile; null when no safety process is reported (a service that does not know the groups yet)
export function safetyTally(items) {
	const own = (items || []).filter(i => groupOf(i) === 'safety')
	if (!own.length) return null
	const level = i => (i.state || {}).level || 0
	return { ok: own.filter(i => level(i) === 0).length, total: own.length, warn: own.filter(i => level(i) === 1).length, bad: own.filter(i => level(i) === 2).length }
}

// how many items each filter would leave (for the label of the buttons): 'all' and 'problems' and the groups
export function filterCounts(items) {
	const all = items || []
	const out = { all: all.length, problems: all.filter(isProblem).length, paused: pausedCount(all) }
	GROUP_IDS.forEach(id => { out[id] = all.filter(i => groupOf(i) === id).length })
	return out
}

// ---- phase 2: honest control of the mode switch -------------------------------------------------------------------------------------
// What the service publishes per process in `module` (all optional: an older service has only mode / active / reason):
//   configured 'auto'|'on'|'off' (the stored mode), effective 'running'|'idle'|'forced'|null (what the supervisor decided at launch),
//   live (the loop reacts to the mode without a restart), pending_restart (a thread runs that the stored mode would stop).
const MODES = ['auto', 'on', 'off']
const EFFECTIVE = ['running', 'idle', 'forced']

// the mode to show as selected: what is stored (configured), else the old key `mode`, else 'auto'
export function configuredMode(p) {
	const m = (p && p.module) || {}
	return MODES.indexOf(m.configured) >= 0 ? m.configured : (MODES.indexOf(m.mode) >= 0 ? m.mode : 'auto')
}

// the ONE line under the switch: { key, params } of a procDocs text. `live` must be exactly true; a service without the field behaves like phase 1
export function modeNote(p) {
	return { key: p && p.module && p.module.live === true ? 'ui_mode_live' : 'ui_mode_restart', params: {} }
}

// the orange note of a row whose stored mode only applies at a restart: null when nothing is pending, else { key, params: { mode } }
export function pendingNote(p) {
	if (!p || !p.module || p.module.pending_restart !== true) return null
	return { key: 'ui_mode_pending', params: { mode: configuredMode(p) } }
}

// what runs now, as the key of a text, or null when the service does not say
export function effectiveKey(p) {
	const e = p && p.module && p.module.effective
	return EFFECTIVE.indexOf(e) >= 0 ? 'ui_effective_' + e : null
}

// the items waiting for a restart, in list order, and how many
export function pendingList(list) {
	return (list || []).filter(p => !!pendingNote(p))
}
export function pendingCount(list) {
	return pendingList(list).length
}

// what a failed or refused modules.set shows next to the row: { kind: 'role'|'session'|'empty'|'error', text }. A role or session cause keeps its standard
// notice (text ''), a refusal of the service (ok:false, e.g. a protected process) is calm ('empty'), anything else that threw is a real failure ('error').
// `res` is the answer of the call (object or JSON text) or null when it threw `err`.
export function modeFailure(res, err) {
	if (err) {
		if (err.code === 'forbidden') return { kind: 'role', text: '' }
		if (err.code === 'login_required') return { kind: 'session', text: '' }
		return { kind: 'error', text: String((err && err.message) || err) }
	}
	let r = res
	if (typeof r === 'string') {
		try { r = JSON.parse(r) } catch (e) { r = null }
	}
	if (r && typeof r === 'object' && r.ok === false) return { kind: 'empty', text: String(r.error || '') }
	return null
}

// ---- phase 3: real control (pause / resume / restart a process, restart the service) ------------------------------------------------
// What the service publishes per process (all optional: an older service has none and the page behaves like phase 2):
//   pausable (the page may pause / resume / restart it), paused, restart_pending, restart_pending_s (seconds since the restart was requested).
export const STUCK_RESTART_S = 30 // a requested restart that waits longer than this says "it did not answer"

// may the row offer Pause / Resume / Restart? the service must say so (`pausable` exactly true); a locked or separate service never
export function canPause(p) {
	return !!p && p.pausable === true && !p.locked && !p.external
}

// 'paused' while a person has paused it (exactly true), else null; the row shows it as a calm tag, never as late
export function pauseKey(p) {
	return p && p.paused === true ? 'paused' : null
}

export function pausedList(list) {
	return (list || []).filter(p => !!pauseKey(p))
}
export function pausedCount(list) {
	return pausedList(list).length
}

// the filter ids to draw: all of FILTER_IDS plus 'paused' (after 'problems') only when something is paused
export function activeFilterIds(items) {
	const ids = FILTER_IDS.slice()
	if (pausedCount(items)) ids.splice(2, 0, PAUSED_FILTER)
	return ids
}

// a selected 'paused' filter with nothing paused any more falls back to 'all' (no empty page for a filter that has no pill)
export function effectiveFilter(filter, items) {
	return filter === PAUSED_FILTER && !pausedCount(items) ? 'all' : filter
}

// the note of a requested restart: null when none is pending, else { key: 'ui_restart_pending', params: { n }, stuck } (stuck: over STUCK_RESTART_S, the row adds the orange "did not answer")
export function restartNote(p) {
	if (!p || p.restart_pending !== true) return null
	const s = Number(p.restart_pending_s)
	const n = Number.isFinite(s) && s > 0 ? Math.round(s) : 0
	return { key: 'ui_restart_pending', params: { n }, stuck: Number.isFinite(s) && s > STUCK_RESTART_S }
}

function readJson(res) {
	if (typeof res === 'string') {
		try { return JSON.parse(res) } catch (e) { return null }
	}
	return res
}

// one reason of the refusal as a text: the service sends { code, message } with the message already in the page language (a plain string or
// an { es, en } pair are accepted too)
function reasonText(r, lang) {
	if (r == null) return ''
	if (typeof r === 'string') return r
	const m = r.message != null ? r.message : r
	if (typeof m === 'string') return m
	if (m && typeof m === 'object') return String(m[lang] || m.en || m.es || '')
	return ''
}

// what a failed or refused service.restart shows: { kind: 'role'|'session'|'blocked'|'error'|'cancelled', reasons: [text], text }. A role or session cause keeps the
// standard notice (text ''), a refusal because the machine is not at rest (409 conflict with error.reasons) is 'blocked' (orange, a calm list), a person who
// cancelled the dialog is 'cancelled' (no change, nothing shown), anything else is a real failure. null = it was accepted.
export function serviceRestartFailure(res, err, lang) {
	if (err) {
		if (err.code === 'cancelled') return { kind: 'cancelled', reasons: [], text: '' }
		if (err.code === 'forbidden') return { kind: 'role', reasons: [], text: '' }
		if (err.code === 'login_required') return { kind: 'session', reasons: [], text: '' }
		const body = (err.body && err.body.error) || {}
		const raw = Array.isArray(body.reasons) ? body.reasons : (Array.isArray(err.reasons) ? err.reasons : null)
		if (err.code === 'conflict' && raw) {
			const reasons = raw.map(r => reasonText(r, lang)).filter(Boolean)
			return { kind: 'blocked', reasons, text: reasons.length ? '' : String(err.message || '') }
		}
		return { kind: 'error', reasons: [], text: String((err && err.message) || err) }
	}
	const r = readJson(res)
	if (r && typeof r === 'object' && r.ok === false) return { kind: 'error', reasons: [], text: String(r.error || '') }
	return null
}

// has the service come back? the first reading after the request has another pid, or a smaller uptime, than the one before it
export function restartDone(before, now) {
	if (!now) return false
	if (!before) return true
	if (before.pid != null && now.pid != null && before.pid !== now.pid) return true
	return before.age_s != null && now.age_s != null && now.age_s < before.age_s
}
