'use strict'

// Pure helpers of the read-only screen Access > Profiles (DISENO-PANTALLAS sections 2.2 and 5). No imports, no DOM: the components only draw what these
// functions return, and a test loads this file in node. Nothing here decides access: the capabilities, their risk, class and lock come from the
// service (roles.list); "covered" is a presentation of what a document lists, the service evaluates the real decision.
//
//   profileRows(list, kind, text)        the rows of the profile table: base first, then own; kind 'all' | 'own' | 'base'; text filters by name
//   capabilityGroups(caps, cats, doc)    the capabilities by category, each with class, risk, lock, stop mark and how the document covers it
//   whenItems(when)                      the conditions of a rule as label key and value
//   ruleSummary(doc)                     how many operation entries the allow rules and the deny rules list
//   jsonText(doc)                        the document as text (two spaces)
//   stateOfError(e)                      the screen state an error of the service means
//   shortDate(at)                        "2026-11-11T10:42:07" -> "2026-11-11 10:42"

export const KINDS = Object.freeze(['all', 'own', 'base'])
export const RISK_COLORS = Object.freeze({ 1: '', 2: 'info', 3: 'warning', 4: 'error' })
const CAP_PREFIX = 'cap:'
const MODE_VARIABLE = '${person.modes}'

function holdersOf(row) {
	const h = (row && row.attached_to) || {}
	return { users: Array.isArray(h.users) ? h.users.slice() : [], groups: Array.isArray(h.groups) ? h.groups.slice() : [] }
}

function rowOf(r, base, list) {
	const h = holdersOf(r)
	return {
		name: String(r.name),
		base,
		rules: r.rules | 0,
		version: base ? 0 : (r.version | 0),
		users: h.users,
		groups: h.groups,
		neverAttached: Array.isArray(list.never_attached) && list.never_attached.includes(r.name)
	}
}

export function profileRows(list, kind, text) {
	const l = list || {}
	const rows = []
	if (kind !== 'own') (l.base || []).forEach(r => rows.push(rowOf(r, true, l)))
	if (kind !== 'base') (l.profiles || []).forEach(r => rows.push(rowOf(r, false, l)))
	const q = String(text || '').trim().toLowerCase()
	return q ? rows.filter(r => r.name.toLowerCase().includes(q)) : rows
}

// an entry of `operations` against one operation pattern of a capability: equal, or the entry is a pattern that covers it ("lights.*", "*", "<ns>:*")
export function entryCovers(entry, pattern) {
	if (entry === pattern || entry === '*') return true
	if (entry.startsWith(CAP_PREFIX) || entry.startsWith('tier:')) return false
	const ns = /^([a-z][a-z0-9_]*):\*$/.exec(entry)
	if (ns) return pattern.split('.')[0] === ns[1]
	if (!/[*?]/.test(entry)) return false
	const re = new RegExp('^' + entry.replace(/[.+^${}()|[\]\\]/g, '\\$&').replace(/\*/g, '.*').replace(/\?/g, '.') + '$')
	return re.test(pattern)
}

function coverage(cap, entries) {
	if (entries.includes(CAP_PREFIX + cap.id) || entries.includes('*')) return 'full'
	const pats = Array.isArray(cap.ops) ? cap.ops : []
	const hit = pats.filter(p => entries.some(e => entryCovers(e, p))).length
	if (!hit) return 'none'
	return hit === pats.length ? 'full' : 'partial'
}

function entriesOf(doc, decision) {
	const out = []
	;((doc && doc.rules) || []).forEach(r => {
		if (r.decision === decision) (r.operations || []).forEach(o => out.push(String(o)))
	})
	return out
}

export function capabilityGroups(caps, cats, doc) {
	const allow = entriesOf(doc, 'allow')
	const deny = entriesOf(doc, 'deny')
	const order = (cats || []).map(c => c.id)
	const byId = new Map()
	;(caps || []).forEach(c => {
		if (!byId.has(c.category)) byId.set(c.category, [])
		byId.get(c.category).push({
			id: c.id,
			title: c.title || c.id,
			klass: c.class,
			risk: c.risk | 0,
			locked: c.delegable === false,
			alwaysAllowed: c.deniable === false,
			allowed: coverage(c, allow),
			denied: coverage(c, deny) !== 'none'
		})
		if (!order.includes(c.category)) order.push(c.category)
	})
	return order.filter(id => byId.has(id)).map(id => ({ id, title: ((cats || []).find(c => c.id === id) || {}).title || id, items: byId.get(id) }))
}

const WHEN_LABELS = { mode: 'builder_when_mode', job_running: 'builder_when_job', machine_on: 'builder_when_on', via: 'builder_when_via', risk_max: 'builder_when_risk' }

// { labelKey, value } for a text value, { labelKey, yes } for a yes / no one; the variable of the modes of the person has its own sentence key
export function whenItems(when) {
	const w = when || {}
	return Object.keys(WHEN_LABELS).filter(k => k in w).map(k => {
		const v = w[k]
		if (typeof v === 'boolean') return { labelKey: WHEN_LABELS[k], yes: v }
		const list = Array.isArray(v) ? v : [v]
		if (list.length === 1 && list[0] === MODE_VARIABLE) return { labelKey: WHEN_LABELS[k], valueKey: 'builder_when_person_modes' }
		return { labelKey: WHEN_LABELS[k], value: list.join(', ') }
	})
}

export function ruleSummary(doc) {
	return { allow: entriesOf(doc, 'allow').length, deny: entriesOf(doc, 'deny').length }
}

export function jsonText(doc) {
	return JSON.stringify(doc || {}, null, 2)
}

// a refusal (403) or a missing session (401) is "no permission"; anything else is a failure to show with its sentence and "Retry"
export function stateOfError(e) {
	const code = e && e.code
	return code === 'forbidden' || code === 'login_required' ? 'no_permission' : 'error'
}

export function shortDate(at) {
	return String(at || '').replace('T', ' ').slice(0, 16)
}
