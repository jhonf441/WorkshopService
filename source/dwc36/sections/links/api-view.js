'use strict'

// The reference of the API as a pure view of what api.describe says: the operations, their category (by the name of the group), the filters, the
// batches the list is drawn in, and the example of each (the request, the curl and the macro line). No Vue, no texts (a category carries the key
// of its name), no clock.

export const FIRST = 40
export const MORE = 60

// the categories in the order they are drawn; `name` is a key of the page catalog, `re` decides by the first word of the operation
export const CATEGORIES = Object.freeze([
	{ id: 'machine', icon: 'mdi-gamepad-variant', name: 'servicePage.cat_machine', re: /^(machine|jog|motion|motors|movement|frame|pid|safety|guard|readiness|preflight|workstate)\./ },
	{ id: 'jobs', icon: 'mdi-briefcase-outline', name: 'servicePage.cat_jobs', re: /^(job|livejob|bigpart|air|laser)\./ },
	{ id: 'lights', icon: 'mdi-lightbulb-outline', name: 'servicePage.lights_and_status', re: /^(light|lights|statuslight)\./ },
	{ id: 'energy', icon: 'mdi-flash-outline', name: 'servicePage.energy', re: /^(power|energy|meter)\./ },
	{ id: 'activity', icon: 'mdi-history', name: 'servicePage.cat_activity', re: /^(activity|notifications|history|risk|blackbox|trace|sound)\./ },
	{ id: 'camera', icon: 'mdi-cctv', name: 'servicePage.cat_cameras', re: /^(camera|vision)\./ },
	{ id: 'security', icon: 'mdi-shield-account-outline', name: 'servicePage.cat_security', re: /^(auth|users|password|keys|audit|roles)\./ },
	{ id: 'config', icon: 'mdi-tune', name: 'servicePage.cat_config', re: /^(config|settings|profile|package|modules|bridge|comms|db|api|examples|state|view)\./ },
	{ id: 'system', icon: 'mdi-cog-outline', name: 'servicePage.system', re: /./ }
])

export function categoryOf(name) {
	return CATEGORIES.find(c => c.re.test(String(name || ''))) || CATEGORIES[CATEGORIES.length - 1]
}

// "access.profiles.list" -> "access": the group is the FIRST segment (the deeper levels are found with the search)
export function subOf(name) {
	return String(name || '').split('.')[0]
}

// the chips shown at first in the row of groups; the rest waits behind "More"
export const SUBS_SHOWN = 12

const EXAMPLE = { int: 0, num: 0, bool: true, obj: {}, list: [], any: '' }

// the operations of api.describe as the screen reads them (`reads` is the service's answer to "does it only read?": an ADMIN operation can only read)
export function opsOf(described) {
	return ((described && described.ops) || []).filter(o => o && o.op).map(o => {
		const args = Object.keys(o.args || {}).map(k => Object.assign({ name: k }, o.args[k]))
		return { name: o.op, kind: o.kind || '', desc: o.desc || '', args, macro: !!o.macro, confirm: o.confirm || null, motion: o.motion || '', slow: !!o.slow, extra: !!o.extra_args, role: o.role || '', read: typeof o.reads === 'boolean' ? o.reads : o.kind === 'read' }
	})
}

// the arguments an example carries: only the required ones, the first choice or a value of the type
export function exampleArgs(op) {
	const out = {}
	op.args.forEach(a => {
		if (!a.required) return
		out[a.name] = a.choices && a.choices.length ? a.choices[0] : EXAMPLE[a.type] !== undefined ? EXAMPLE[a.type] : 'text'
	})
	return out
}

export function requestText(op) {
	return JSON.stringify({ op: op.name, args: exampleArgs(op), origin: 'external:my-service' }, null, 2)
}

export function curlText(op, host) {
	return "curl -s -X POST http://" + (host || 'duet3.local') + "/machine/WorkshopService/api \\\n  -H 'X-Workshop-Key: wk_...' -H 'Content-Type: application/json' \\\n  -d '" + JSON.stringify({ op: op.name, args: exampleArgs(op) }) + "'"
}

export function macroText(op) {
	const ex = exampleArgs(op)
	const kv = Object.keys(ex).map(k => k + '=' + (typeof ex[k] === 'object' ? '...' : ex[k])).join(',')
	return 'M98 P"0:/sys/workshop/macros/system/service-call.g" S"' + op.name + '"' + (kv ? ' A"' + kv + '"' : '') + ' Q1'
}

// the rules of an argument as short words: one of, minimum, maximum, default
export function rulesOf(a) {
	const r = []
	if (a.choices && a.choices.length) r.push({ key: 'one_of', text: a.choices.join(' | ') })
	if (a.min !== undefined) r.push({ key: 'min', text: '>= ' + a.min })
	if (a.max !== undefined) r.push({ key: 'max', text: '<= ' + a.max })
	if (a.default !== undefined) r.push({ key: 'default', text: JSON.stringify(a.default) })
	return r
}

// a read and a stop go with one touch (a stop is never delayed); everything else asks the second touch
export function needsSecondTouch(op) {
	return !!op && op.kind !== 'read' && op.kind !== 'stop'
}

export function countsOf(ops) {
	return CATEGORIES.map(c => ({ id: c.id, icon: c.icon, name: c.name, n: ops.filter(o => categoryOf(o.name).id === c.id).length })).filter(c => c.n > 0)
}

export function subsOf(ops, cat) {
	const by = {}
	ops.filter(o => categoryOf(o.name).id === cat).forEach(o => { const k = subOf(o.name); by[k] = (by[k] || 0) + 1 })
	return Object.keys(by).sort().map(k => ({ id: k, n: by[k] }))
}

// mode: 'all' | 'read' (only what reads) | 'write' (what changes something)
export function filterOps(ops, f) {
	const q = String((f && f.q) || '').toLowerCase().trim()
	const mode = (f && f.mode) || 'all'
	return ops.filter(o =>
		(mode === 'all' || (mode === 'read' ? o.read : !o.read)) &&
		(!f || !f.cat || categoryOf(o.name).id === f.cat) &&
		(!f || !f.sub || subOf(o.name) === f.sub) &&
		(!q || (o.name + ' ' + o.desc).toLowerCase().indexOf(q) >= 0))
}

// the first sentence of a description, for the line of the list
export function summaryOf(desc) {
	const s = String(desc || '')
	const i = s.search(/[.:] /)
	return (i > 0 ? s.slice(0, i) : s).slice(0, 110)
}

// how many are drawn: the first ones, and `limit` more each time the person asks
export function shownCount(total, limit) {
	return Math.min(total, limit)
}
