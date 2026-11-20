'use strict'

// The commands the service received, as a pure view of history.list: the quick ranges, the arguments of a question, the fields of the origin
// of one command and the small helpers the table needs. No Vue, no texts (every word is a key of the area `commandsReceived`), no clock (the
// caller passes `now`).

export const PAGE = 50

// quick ranges: days back for the start and the end (0 = today)
export const SPANS = Object.freeze([
	{ id: 'today', key: 'today', since: 0, until: 0 },
	{ id: 'yesterday', key: 'yesterday', since: 1, until: 1 },
	{ id: '7', key: '7_days', since: 6, until: 0 },
	{ id: '30', key: '30_days', since: 29, until: 0 }
])

const two = n => (n < 10 ? '0' : '') + n

export function dayText(now, back) {
	const d = new Date(now - (back || 0) * 86400000)
	return d.getFullYear() + '-' + two(d.getMonth() + 1) + '-' + two(d.getDate())
}

// { from, to } of a quick range
export function rangeOf(id, now) {
	const s = SPANS.find(x => x.id === id) || SPANS[0]
	return { from: dayText(now, s.since), to: dayText(now, s.until) }
}

// a date typed in a field: 'YYYY-MM-DD' or null
export function validDay(text) {
	const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(text || '').trim())
	if (!m) return null
	const d = new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]))
	return d.getMonth() === Number(m[2]) - 1 && d.getDate() === Number(m[3]) ? m[0] : null
}

// the two typed dates as a range; null when one is not a date or the end is before the start
export function rangeFrom(from, to) {
	const a = validDay(from)
	const b = validDay(to)
	return a && b && a <= b ? { from: a, to: b } : null
}

// 'what' of the quick choice: 1 what changes something, 2 what only reads, 0 all
export const CLASSES = Object.freeze([{ id: 1, key: 'change_something' }, { id: 2, key: 'readings' }, { id: 0, key: 'all' }])

// the arguments of history.list for a question (the empty ones are not sent)
export function argsOf(q, range, offset, limit) {
	const a = { from: range.from, to: range.to, limit: limit || PAGE, offset: offset || 0, rw: Number(q.rw) || 0 }
	;['name', 'via', 'channel', 'kind', 'plugin', 'result', 'query'].forEach(k => { if (q[k]) a[k] = String(q[k]) })
	if (q.errors) a.errors = true
	return a
}

export const FILTERS = Object.freeze(['name', 'via', 'channel', 'kind', 'plugin', 'result'])

export function emptyQuestion() {
	return { rw: 1, name: '', via: '', channel: '', kind: '', plugin: '', result: '', query: '', errors: false }
}

// how many filters (beyond the class) are on
export function activeFilters(q) {
	return FILTERS.filter(k => q[k]).length + (q.query ? 1 : 0) + (q.errors ? 1 : 0)
}

// origin of a command: the key of its name and the icon
export const ORIGIN_KEYS = Object.freeze({ page: 'page', console: 'console', job_file: 'job_file', macro: 'macro', bridge: 'g_code_bridge', service: 'service', external: 'external_program', trigger: 'event', panel: 'board_display', queue: 'queue', plugin: 'another_plugin', unknown: 'unknown' })

export function originKey(kind) {
	return Object.prototype.hasOwnProperty.call(ORIGIN_KEYS, kind) ? ORIGIN_KEYS[kind] : ''
}

export const RESULT_KEYS = Object.freeze({ ok: 'ok', error: 'with_error_2', blocked: 'blocked' })

// the fields of the detail, in order: [field, key of its name]
export const FIELDS = Object.freeze([
	['kind', 'origin'], ['channel', 'channel'], ['label', 'channel_detail'], ['conn', 'connection'], ['plugin', 'plugin_or_page'], ['tagged', 'with_own_tag'], ['client', 'bridge_client'],
	['client_ip', 'bridge_client_ip'], ['addr', 'client_address'], ['agent', 'browser_or_program'], ['referer', 'source_page'], ['session', 'dwc_session'], ['job_file', 'job_file_2'],
	['line', 'line'], ['file_pos', 'position_in_the_file'], ['macro', 'inside_a_macro'], ['result', 'result'], ['reason', 'reason'], ['ms', 'took_ms'], ['wait_ms', 'waited_its_turn_ms']
])

// the fields of an origin that have a value: [{ field, key, value }] (the value of a boolean is true / false: the screen says yes / no)
export function fieldsOf(origin) {
	const o = origin || {}
	return FIELDS.filter(([f]) => o[f] !== undefined && o[f] !== null && o[f] !== '').map(([f, key]) => ({ field: f, key, value: o[f] }))
}

// the width of the bar of a time, 0..100 (a logarithmic scale from 1 ms to 10 s)
export function barOf(ms) {
	if (ms === null || ms === undefined) return 0
	return Math.min(100, Math.round(Math.log10(Math.max(1, ms)) / 4 * 100))
}

// a text that is JSON inside a JSON value (the `jsonl` of audit.export is lines of JSON in one string) as the value it holds, so that the block reads as one structure; any other text stays as it is
function opened(v, depth) {
	if (depth > 4) return v
	if (Array.isArray(v)) return v.map(x => opened(x, depth + 1))
	if (v && typeof v === 'object') {
		const out = {}
		Object.keys(v).forEach(k => { out[k] = opened(v[k], depth + 1) })
		return out
	}
	if (typeof v !== 'string' || !/^\s*[[{]/.test(v)) return v
	try {
		const one = JSON.parse(v)
		return typeof one === 'object' && one !== null ? opened(one, depth + 1) : v
	} catch (e) {
		const lines = v.split('\n').filter(l => l.trim())
		if (lines.length < 2) return v
		try { return lines.map(l => opened(JSON.parse(l), depth + 1)) } catch (e2) { return v }
	}
}

// a response as readable text: JSON indented (two spaces) when it is JSON, with the JSON that comes as text inside it opened; else as it came. What Copy copies is the original text.
export function niceResponse(text) {
	const s = String(text === undefined || text === null ? '' : text)
	try {
		const v = JSON.parse(s)
		return typeof v === 'object' && v !== null ? JSON.stringify(opened(v, 0), null, 2) : s
	} catch (e) {
		return s
	}
}

// the hour of a row: '2026-11-18T13:39:02' -> '13:39:02'
export function hourOf(ts) {
	return String(ts || '').slice(11, 19)
}

// the summary of the range as four figures
export function figuresOf(summary) {
	const s = summary || null
	if (!s) return null
	return { changes: (s.all || 0) - (s.readings || 0), readings: s.readings || 0, errors: s.errors || 0, avg: s.ms_avg === undefined ? null : s.ms_avg, max: s.ms_max === undefined ? null : s.ms_max }
}

// what to say about the origin of a row, short: "Page: Lights"
export function originLine(origin) {
	const o = origin || {}
	return o.kind ? { key: originKey(o.kind), raw: o.kind, plugin: o.plugin || '' } : null
}
