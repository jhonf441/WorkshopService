'use strict'

// Diagnostics, worked out from plain data (pure: no store, no language, no clock).
//
//   itemsOf(input)        ONE list of what runs: the processes of the service and the separate services it depends on.
//                         input: { processes (servicesInternal.processes), modules (servicesInternal.modules), watches (guardStatus.watches),
//                                  services (healthPi.services), base (healthPi.base) }
//                         item: { id, kind: 'process' | 'separate', group, title, description (texts of the service, or null), word, level,
//                                 process (what the service published), module, pausable, safety, restartPending, restartS, mode }
//                         word: fine | resting | paused | unknown | late | errors | stopped | unchecked   (core/live/process-state.js decides
//                         it for a process: the home counts with the same rule)
//   counts(items)         { fine, notice, stopped, resting, total } of the PROCESSES (the separate services have their group, not a figure:
//                         these four always add up to the processes the service publishes, the number the home counts with)
//   needsLook(item)       a notice, a failure, a pause a person made or a restart that waits
//   defaultFilter(items)  'attention' when something needs a look, else 'all'
//   passes(item, filter)  filters: all | attention | stopped (not running: stopped or paused)
//   groupsOf(items, filter, query, textOf)   [{ id, total, look, word, items }] in the fixed order; a group with nothing to show is left
//                         out; textOf(item) = the words a person may type to find it (the screen builds them in its language)
//   reasonOf(item)        why it needs a look: { key, params, n } of the area `health`, or null
//   modeOf(item)          the stored way of running: 'auto' | 'on' | 'off'
//   readableId(id)        the name of a process the service did not name
//   loadOf(internal)      the load towards the board: { perMin, limit, over, subscription, areas: [{ id, n, pct, maxMs }] }

import { statesOf } from '../../core/live/process-state.js'

export const GROUPS = ['safety', 'machine', 'data', 'support', 'separate']
export const FILTERS = ['all', 'attention', 'stopped']
export const MODES = ['auto', 'on', 'off']
export const IPC_LIMIT = 300            // calls per minute towards the board the service is designed to stay under
export const RESTART_STUCK_S = 60
export const BRIDGE_UNIT = 'workshop-gcode-bridge'

const RANK = { stopped: 0, errors: 1, late: 1, unknown: 1, paused: 2, fine: 3, unchecked: 3, resting: 4 }

function groupOf(p) {
	const g = p && p.group
	return g === 'safety' || g === 'machine' || g === 'data' ? g : 'support'
}

function separate(id, title, state) {
	const word = state === 'ok' ? 'fine' : state === 'down' ? 'stopped' : state === 'rest' ? 'resting' : 'unchecked'
	return {
		id, kind: 'separate', group: 'separate', title: title || null, description: null, word, level: word === 'stopped' ? 2 : 0,
		process: null, module: null, pausable: false, safety: false, restartPending: false, restartS: 0, mode: ''
	}
}

// the name of a process the service gave no title to: its id as words ("bed_zones" -> "Bed zones"); an id is never shown as a name
export function readableId(id) {
	const words = String(id === undefined || id === null ? '' : id).replace(/([a-z0-9])([A-Z])/g, '$1 $2').replace(/[_\-.]+/g, ' ').trim().toLowerCase()
	return words ? words.charAt(0).toUpperCase() + words.slice(1) : ''
}

export function modeOf(item) {
	const m = (item && item.module) || {}
	return MODES.indexOf(m.configured) >= 0 ? m.configured : MODES.indexOf(m.mode) >= 0 ? m.mode : 'auto'
}

export function itemsOf(input) {
	const x = input || {}
	const modules = x.modules || {}
	const items = statesOf(x.processes || {}).map(s => {
		const p = s.process || {}
		const item = {
			id: s.id, kind: 'process', group: groupOf(p), title: p.title || null, description: p.description || null, word: s.word, level: s.level,
			process: p, module: modules[s.id] || null, pausable: p.pausable === true && !p.locked, safety: !!p.locked || p.group === 'safety',
			restartPending: p.restart_pending === true, restartS: Number(p.restart_pending_s) || 0, mode: ''
		}
		item.mode = modeOf(item)
		return item
	})
	;(Array.isArray(x.watches) ? x.watches : []).filter(w => w && (w.id === 'vision' || w.id === 'rs485')).forEach(w => items.push(separate(w.id, w.title, w.state)))
	const bridge = (Array.isArray(x.services) ? x.services : []).find(s => s && s.unit === BRIDGE_UNIT)
	if (bridge) items.push(separate('bridge', null, bridge.active === false ? 'down' : 'ok'))
	if (x.base && x.base.check) items.push(separate('database', null, x.base.check === 'ok' ? 'ok' : 'down'))
	return items
}

export function counts(items) {
	const out = { fine: 0, notice: 0, stopped: 0, resting: 0, total: 0 }
	;(items || []).filter(i => i.kind === 'process').forEach(i => {
		out.total += 1
		if (i.level >= 2) out.stopped += 1
		else if (i.level === 1) out.notice += 1
		else if (i.word === 'resting' || i.word === 'paused') out.resting += 1
		else out.fine += 1
	})
	return out
}

export function needsLook(item) {
	return !!item && (item.level > 0 || item.word === 'paused' || item.restartPending || !!(item.module && item.module.pending_restart))
}

export function defaultFilter(items) {
	return (items || []).some(needsLook) ? 'attention' : 'all'
}

export function passes(item, filter) {
	if (filter === 'attention') return needsLook(item)
	if (filter === 'stopped') return item.word === 'stopped' || item.word === 'paused'
	return true
}

const byRank = (a, b) => (RANK[a.word] - RANK[b.word]) || (a.id < b.id ? -1 : a.id > b.id ? 1 : 0)

export function groupsOf(items, filter, query, textOf) {
	const all = items || []
	const f = FILTERS.indexOf(filter) >= 0 ? filter : 'all'
	const words = String(query || '').toLowerCase().split(/\s+/).filter(Boolean)
	const found = i => !words.length || words.every(w => String(textOf ? textOf(i) : i.id).toLowerCase().indexOf(w) >= 0)
	return GROUPS.map(id => {
		const own = all.filter(i => i.group === id)
		const worst = own.some(i => i.level >= 2) ? 'stopped' : own.some(i => i.level === 1) ? 'notice' : own.some(i => i.word === 'paused') ? 'paused' : 'fine'
		return { id, total: own.length, look: own.filter(needsLook).length, word: worst, items: own.filter(i => passes(i, f) && found(i)).sort(byRank) }
	}).filter(g => g.items.length)
}

export function reasonOf(item) {
	if (!item) return null
	const p = item.process || {}
	if (item.kind === 'separate') return item.word === 'stopped' ? { key: 'reason_separate_down', params: {}, n: null } : item.word === 'unchecked' ? { key: 'reason_unchecked', params: {}, n: null } : null
	if (item.word === 'stopped') return { key: 'reason_stopped', params: {}, n: null }
	if (item.word === 'unknown') return { key: 'reason_unknown', params: {}, n: null }
	if (item.word === 'late') return { key: 'reason_late', params: { ageS: p.age_ok_s, expectedS: p.expected_s }, n: null }
	if (item.word === 'errors') return { key: 'reason_errors', params: { error: p.error || '', hour: p.error_hour || '' }, n: null }
	if (item.word === 'paused') return { key: 'reason_paused', params: {}, n: null }
	if (item.word === 'resting') return { key: 'reason_resting', params: {}, n: null }
	if ((p.restarts || 0) > 0) return { key: 'reason_relaunched', params: {}, n: p.restarts }
	return null
}

export function loadOf(internal) {
	const x = internal || {}
	const ipc = x.ipc || null
	const types = (ipc && ipc.types) || {}
	const byArea = {}
	Object.keys(types).forEach(k => {
		const area = k.indexOf('|') >= 0 ? k.split('|')[1] : k
		const a = byArea[area] || (byArea[area] = { id: area, n: 0, maxMs: 0 })
		a.n += Number(types[k].last_min) || 0
		a.maxMs = Math.max(a.maxMs, Number(types[k].max_ms) || 0)
	})
	const perMin = ipc ? Number(ipc.per_min) || 0 : null
	const total = Object.keys(byArea).reduce((n, k) => n + byArea[k].n, 0)
	const areas = Object.keys(byArea).map(k => Object.assign(byArea[k], { pct: total ? Math.round(byArea[k].n * 100 / total) : 0 })).filter(a => a.n > 0).sort((a, b) => b.n - a.n || (a.id < b.id ? -1 : 1))
	return { perMin, limit: IPC_LIMIT, over: perMin !== null && perMin > IPC_LIMIT, subscription: x.subscription || null, process: x.process || null, areas }
}

// "Chrome 120.0.0.0" of a user agent: Edge, Firefox, Chromium, Chrome, Safari (in this order: each one also says the next); '' when it is none of them
export function browserOf(ua) {
	const s = String(ua || '')
	const find = [['Edge', /Edg(?:e|A|iOS)?\/([\d.]+)/], ['Firefox', /Firefox\/([\d.]+)/], ['Chromium', /Chromium\/([\d.]+)/], ['Chrome', /Chrome\/([\d.]+)/], ['Safari', /Version\/([\d.]+).*Safari/]]
	for (const [name, re] of find) {
		const m = re.exec(s)
		if (m) return name + ' ' + m[1]
	}
	return ''
}

// what this screen is, for a report: size of the viewport, scale of the pixels, browser and the width class of the page (s | m | l)
export function screenOf(env) {
	const e = env || {}
	const round = n => Math.round(Number(n) || 0)
	const ratio = Math.round((Number(e.ratio) || 1) * 100) / 100
	return { width: round(e.width), height: round(e.height), ratio, browser: browserOf(e.ua) || '?', dataW: e.dataW || '?' }
}
