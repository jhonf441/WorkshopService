'use strict'

// Pure helpers of Security > Recorded activity (DISENO-PANTALLAS sections 2.6 and 5). No imports of the page, no DOM: the components only draw what these
// functions return and a test loads this file in node. Nothing here decides anything: the rows come from audit.list, the chain from audit.verify, the file
// from audit.export, the settings from audit.settings and the alarms from activity.list (type security_alarm). This file arranges them.
//
//   resultOf(row)                    'allowed' | 'denied' | 'error', the same rule as the service (ok, and the codes forbidden / login_required)
//   listArgs(filters, offset)        the arguments of audit.list for the filters of the screen (only what is filled)
//   rowView(row, readOps)            one row ready to draw: result, who decided, target, read chip
//   decidedBy(row)                   { key, params } of the sentence that says who decided (keys of the area `access`), or null
//   changeOf(row)                    { what, name, before, after } when the row is a change of access that kept its before and after, else null
//   chainReasonKey(code)             the key of the sentence of a reason of a broken chain
//   verifyChain(call, hooks)         walks audit.verify page by page: { ok, done, checked, links, cuts, pre, broken, cancelled }
//   assembleExport(call, hooks)          asks audit.export page by page and joins the lines: { text, rows, chained, cancelled }
//   exportFileName(range)            the name of the file
//   alertRows(answer, lang)          the alarms of an activity.list answer: { id, ts, text }
//   pageText(offset, shown, total)   "from", "to" of "1 to 50 of 312"
//   SETTING_CHOICES / settingsDraft / settingsPatch / settingsLines    the closed lists of the settings and the change between two drafts

export const PAGE_SIZE = 50
export const ALERT_TYPE = 'security_alarm'
export const ALERT_DAYS = 30
export const ALERT_SHOWN = 5
export const KEPT_DAYS = 90 // db.AUDIT_DAYS of the service (a test compares them)
export const DENIED_CODES = Object.freeze(['forbidden', 'login_required'])
export const RESULTS = Object.freeze(['allowed', 'denied', 'error'])
export const CHAIN_REASONS = Object.freeze(['chain_break', 'hash_mismatch', 'missing_row', 'missing_link'])
const MAX_LOOPS = 100000

export function resultOf(row) {
	if (row && row.ok) return 'allowed'
	return row && DENIED_CODES.includes(row.code) ? 'denied' : 'error'
}

// The filters in the address (?s=security&t=activity&f=...): only what differs from a fresh screen, as a short JSON; what comes back is cleaned (known keys, text, a range of a known shape)
const FILTER_TEXT = ['user', 'group', 'op', 'target', 'result']
export function filtersToQuery(f, fresh) {
	const x = f || {}
	const base = fresh || {}
	const out = {}
	FILTER_TEXT.forEach(k => { if (String(x[k] || '').trim()) out[k] = String(x[k]).trim() })
	;['denied', 'errors'].forEach(k => { if (x[k]) out[k] = true })
	if (x.detail === false) out.detail = false
	if (x.range && JSON.stringify(x.range) !== JSON.stringify(base.range)) out.range = x.range
	return Object.keys(out).length ? JSON.stringify(out) : ''
}

export function filtersFromQuery(text) {
	let o = null
	try { o = JSON.parse(String(text || '')) } catch (e) { return {} }
	if (!o || typeof o !== 'object' || Array.isArray(o)) return {}
	const out = {}
	FILTER_TEXT.forEach(k => { if (typeof o[k] === 'string' && o[k].length <= 200) out[k] = o[k] })
	if (out.result && !RESULTS.includes(out.result)) delete out.result
	;['denied', 'errors'].forEach(k => { if (o[k] === true) out[k] = true })
	if (o.detail === false) out.detail = false
	const r = o.range
	if (r && typeof r === 'object' && (r.type === 'relative' || r.type === 'absolute')) out.range = r
	return out
}

export function listArgs(f, offset) {
	const x = f || {}
	const out = { limit: PAGE_SIZE, offset: offset | 0 }
	;['from', 'to', 'user', 'group', 'op', 'target'].forEach(k => {
		const v = String(x[k] === undefined || x[k] === null ? '' : x[k]).trim()
		if (v) out[k] = v
	})
	if (RESULTS.includes(x.result)) out.result = x.result
	if (x.denied) out.denied = true
	if (x.errors) out.errors = true
	if (x.detail) out.detail = true
	return out
}

// the sentence of who decided; every key is written out so the i18n checks can see it
const DECIDED = Object.freeze({
	explicit_deny: 'reason_deny',
	ceiling: 'reason_ceiling',
	implicit_deny: 'reason_no_rule',
	not_delegable: 'reason_admin_only',
	stop: 'reason_stop',
	escalated: 'audit_decided_escalated',
	login_required: 'audit_decided_no_session'
})

export function decidedBy(row) {
	const d = row && row.detail
	if (!d || typeof d !== 'object') return null
	const reason = String(d.reason || '')
	if (reason === 'allow' || (reason === 'role' && d.decision === 'allowed')) return d.profile ? { key: 'audit_decided_rule', params: { profile: d.profile, rule: d.rule || '' } } : { key: 'audit_decided_base', params: {} }
	if (reason === 'explicit_deny') return { key: DECIDED.explicit_deny, params: { profile: d.profile || '', rule: d.rule || '' } }
	if (reason === 'ceiling') return { key: DECIDED.ceiling, params: { ceiling: d.ceiling || d.profile || '' } }
	if (Object.prototype.hasOwnProperty.call(DECIDED, reason)) return { key: DECIDED[reason], params: {} }
	if (d.decision === 'denied') return { key: 'audit_decided_role', params: {} }
	if (d.decision === 'error') return { key: 'audit_decided_failed', params: { code: reason } }
	return null
}

export function rowView(row, readOps) {
	const r = row || {}
	const d = r.detail && typeof r.detail === 'object' ? r.detail : null
	return {
		id: r.id,
		when: String(r.ts || '').replace('T', ' '),
		user: r.user || '',
		role: r.role || '',
		op: r.op || '',
		args: r.args || '',
		code: r.code || '',
		result: resultOf(r),
		read: !!readOps && (readOps instanceof Set ? readOps.has(r.op) : readOps.includes(r.op)),
		target: d && d.target ? String(d.target) : '',
		decided: decidedBy(r),
		hasDetail: !!d
	}
}

// the access operations leave the thing before and after as JSON in `args` (access_ops._detail); anything else is not a change
export function changeOf(row) {
	let o = null
	try {
		o = JSON.parse(row && row.args)
	} catch (e) {
		return null
	}
	if (!o || typeof o !== 'object' || !('before' in o) || !('after' in o)) return null
	const text = v => (typeof v === 'string' ? v : JSON.stringify(v === undefined ? null : v))
	return { what: String(o.access || ''), name: String(o.name || ''), before: text(o.before), after: text(o.after) }
}

const REASON_KEYS = Object.freeze({
	chain_break: 'audit_reason_chain_break',
	hash_mismatch: 'audit_reason_hash_mismatch',
	missing_row: 'audit_reason_missing_row',
	missing_link: 'audit_reason_missing_link',
	other: 'audit_reason_other'
})
export const REASON_KEY_LIST = Object.freeze(Object.values(REASON_KEYS))

export function chainReasonKey(code) {
	return CHAIN_REASONS.includes(code) ? REASON_KEYS[code] : REASON_KEYS.other
}

// call(after) -> the answer of audit.verify; hooks { progress(checked), cancelled() }
export async function verifyChain(call, hooks) {
	const h = hooks || {}
	let after = 0
	let checked = 0
	for (let i = 0; i < MAX_LOOPS; i++) {
		if (h.cancelled && h.cancelled()) return { ok: true, done: false, cancelled: true, checked, links: 0, cuts: 0, pre: 0, broken: null }
		const page = await call(after)
		checked += page.checked | 0
		if (h.progress) h.progress(checked)
		if (!page.ok || page.done) {
			return { ok: !!page.ok, done: true, cancelled: false, checked, links: page.links | 0, cuts: page.cuts | 0, pre: page.pre_chain_rows | 0, broken: page.broken || null }
		}
		if (!(page.next_after > after)) throw new Error('verify did not advance')
		after = page.next_after
	}
	throw new Error('verify did not end')
}

// call(after) -> the answer of audit.export for the range; the lines of every page are joined in the order they came
export async function assembleExport(call, hooks) {
	const h = hooks || {}
	let after = 0
	let rows = 0
	let chained = 0
	const parts = []
	for (let i = 0; i < MAX_LOOPS; i++) {
		if (h.cancelled && h.cancelled()) return { text: '', rows, chained, cancelled: true }
		const page = await call(after)
		parts.push(page.jsonl || '')
		rows += page.rows | 0
		chained += page.chained | 0
		if (h.progress) h.progress(rows)
		if (page.done) return { text: parts.join(''), rows, chained, cancelled: false }
		if (!(page.next_after > after)) throw new Error('export did not advance')
		after = page.next_after
	}
	throw new Error('export did not end')
}

export function exportFileName(range) {
	const r = range || {}
	const a = String(r.from || '').slice(0, 10)
	const b = String(r.to || r.from || '').slice(0, 10)
	return 'activity-' + (a || 'all') + (b && b !== a ? '_' + b : '') + '.jsonl'
}

// The text of an alert; the name of somebody who had no session comes from the service as "anonymous <address>": it is said as `anonymous` (and the
// address when there is one). `minute` is the minute of the alert ('YYYY-MM-DDTHH:MM'): the button "see the refusals" filters that minute and the one before.
export function alertRows(answer, lang, anonymous) {
	const rows = (answer && Array.isArray(answer.rows) ? answer.rows : []).filter(r => r.kind === ALERT_TYPE)
	const who = anonymous || 'anonymous'
	return rows.map(r => {
		const raw = (lang === 'en' && r.description_en) || r.description || ''
		const text = raw.replace(/\banonymous(?: ([0-9a-fA-F.:]+))?( \?)?/, (m, addr) => who + (addr ? ' (' + addr + ')' : ''))
		const ts = String(r.ts || '')
		return { id: r.id, ts: ts.replace('T', ' '), text, minute: /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}/.test(ts) ? ts.slice(0, 16) : '' }
	})
}

export function pageText(offset, shown, total) {
	return { from: shown ? offset + 1 : 0, to: offset + shown, total }
}

// ---- the settings (audit.settings): closed lists; the service checks the same ranges (audit_settings.LIMITS)
export const SETTING_CATEGORIES = Object.freeze(['camera', 'audit', 'config'])
export const SETTING_ALARMS = Object.freeze(['access_damaged', 'denial_burst', 'sensitive_change', 'chain_broken'])
export const SETTING_CHOICES = Object.freeze({
	read_sample: [1, 5, 10, 50, 100],
	read_daily_cap: [50, 100, 200, 500, 1000, 5000],
	burst_threshold: [3, 5, 8, 15, 30],
	burst_window_s: [30, 60, 120, 300, 600],
	alarm_quiet_s: [300, 900, 3600, 21600, 86400]
})
export const SETTING_NUMBERS = Object.freeze(Object.keys(SETTING_CHOICES))

// the list of a number setting; a value the file already holds is kept in the list so the screen can show it
export function choicesFor(key, current) {
	const base = (SETTING_CHOICES[key] || []).slice()
	if (Number.isInteger(current) && !base.includes(current)) base.push(current)
	return base.sort((a, b) => a - b)
}

export function settingsDraft(s) {
	const x = s || {}
	const d = { reads: {}, alarms: {} }
	SETTING_CATEGORIES.forEach(k => { d.reads[k] = !!(x.reads && x.reads[k]) })
	SETTING_ALARMS.forEach(k => { d.alarms[k] = !!(x.alarms && x.alarms[k]) })
	SETTING_NUMBERS.forEach(k => { d[k] = x[k] })
	return d
}

// the argument `settings` of audit.settings: only what changed ({} = nothing to save)
export function settingsPatch(before, draft) {
	const a = settingsDraft(before)
	const b = settingsDraft(draft)
	const out = {}
	;[['reads', SETTING_CATEGORIES], ['alarms', SETTING_ALARMS]].forEach(([group, names]) => {
		const ch = {}
		names.forEach(n => { if (a[group][n] !== b[group][n]) ch[n] = b[group][n] })
		if (Object.keys(ch).length) out[group] = ch
	})
	SETTING_NUMBERS.forEach(k => { if (a[k] !== b[k] && Number.isInteger(b[k])) out[k] = b[k] })
	return out
}

// the lines of the before and after table: { id, group, name, from, to } (booleans as 'on' | 'off' for the screen to translate)
export function settingsLines(before, draft) {
	const a = settingsDraft(before)
	const b = settingsDraft(draft)
	const lines = []
	SETTING_CATEGORIES.forEach(n => { if (a.reads[n] !== b.reads[n]) lines.push({ id: 'reads.' + n, group: 'reads', name: n, from: a.reads[n] ? 'on' : 'off', to: b.reads[n] ? 'on' : 'off' }) })
	SETTING_ALARMS.forEach(n => { if (a.alarms[n] !== b.alarms[n]) lines.push({ id: 'alarms.' + n, group: 'alarms', name: n, from: a.alarms[n] ? 'on' : 'off', to: b.alarms[n] ? 'on' : 'off' }) })
	SETTING_NUMBERS.forEach(k => { if (a[k] !== b[k] && Number.isInteger(b[k])) lines.push({ id: k, group: 'number', name: k, from: a[k], to: b[k] }) })
	return lines
}

// a read category switched on writes more to the SD card: true when the draft turns one on that was off
export function turnsOnReads(before, draft) {
	const p = settingsPatch(before, draft)
	return !!p.reads && Object.values(p.reads).some(v => v === true)
}
