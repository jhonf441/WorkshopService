'use strict'

// The view model of the tab "Who can do what" (Access): what a person can do, by area, in plain words, and why. PURE: no imports of the page, no DOM, no
// translator. It decides NOTHING: every "can" or "cannot" is the answer of the service to access.check (the one engine: profiles, groups, ceiling and the
// table of roles for a person that is not governed by profiles). This file only chooses the operation that stands for each capability, groups the
// answers in the ten areas of access-areas.js and names the cause of each refusal (access-reason.js knows the causes).
//
//   BATCH_MAX                     100: the most requests of ONE access.check call (the service refuses more)
//   askPlan(caps, context)        { items, capIds }: one request per capability that has an operation to ask (never more than the capabilities)
//   chunk(list, size)             the list in pieces of at most `size` (BATCH_MAX by default): the calls to make
//   rowsByCap(plan, answers)      capability id -> the answer of its request (answers = the `items` of every call, in order)
//   lineOf(cap, row, role)        one capability as a line: { id, title, class, risk, state, cause, sentence, hint, go }
//   areaView(area, capsById, rows, role, person)   one area: { id, icon, state, counts, lines, unknown }
//   personView(input)             { name, role, governed, sources, areas, summary }
//   gridRows(views)               [{ name, role, cells: { <area id>: state } }]
//   restrictedAreas(cells, n)     the n areas of a row that are most restricted, worst first: [{ id, state }] (the phone shows them on the card of a person)
//   sourcesOf(input)              what the person has, in ONE list: role, own roles, profiles, groups, ceiling, each with the key of its reason
//   LINE_STATES / AREA_STATES     the words a line / an area can be in (each one is an icon and a word on screen)
//
// Line states:  can (allowed) | stop (stopping is always allowed) | cannot | admin_only (not delegable: only an administrator) | unknown (the service could not say)
// Area states:  can | view (only things that read) | partial | cannot | admin_only | unknown

import { AREAS, representativeOp } from './access-areas.js'
import { checkOutcome, isBaseRole, viaGroups } from './access-people-view.js'

export const BATCH_MAX = 100
export const LINE_STATES = Object.freeze(['can', 'stop', 'cannot', 'admin_only', 'unknown'])
export const AREA_STATES = Object.freeze(['can', 'view', 'partial', 'cannot', 'admin_only', 'unknown'])

// explicit keys (not built at run time) so the i18n checks see that each one is used
const HINT_KEYS = Object.freeze({
	profile: 'who_todo_profile',
	ceiling: 'who_todo_ceiling',
	no_rule: 'who_todo_no_rule',
	role: 'who_todo_role',
	not_delegable: 'who_todo_admin_only',
	condition: 'who_todo_condition',
	session: 'who_todo_session',
	unknown: 'who_todo_unknown'
})

function list(x) {
	return Array.isArray(x) ? x : []
}

export function chunk(items, size) {
	const n = size > 0 ? size : BATCH_MAX
	const out = []
	for (let i = 0; i < list(items).length; i += n) out.push(items.slice(i, i + n))
	return out
}

// context: what the requests assume ({ modeNow: true } = the mode the machine is in now); the same for every request
export function askPlan(caps, context) {
	const items = []
	const capIds = []
	list(caps).forEach(cap => {
		const operation = representativeOp(cap)
		if (!operation) return
		items.push(Object.assign({ operation }, context || {}))
		capIds.push(cap.id)
	})
	return { items, capIds }
}

export function rowsByCap(plan, answers) {
	const out = {}
	const rows = list(answers)
	plan.capIds.forEach((id, i) => { out[id] = rows[i] || null })
	return out
}

function hintOf(cause, legacy) {
	const c = legacy && cause !== 'condition' && cause !== 'session' && cause !== 'not_delegable' ? 'role' : cause
	return HINT_KEYS[c] || HINT_KEYS.unknown
}

// where a person can go to change the cause: the profile that denied, the person (their role, profiles and ceiling)
function goOf(cause, outcome, person) {
	if (cause === 'profile' && outcome.deciding) return { tab: 'profiles', name: outcome.deciding.profile }
	if (cause === 'profile' || cause === 'ceiling' || cause === 'no_rule' || cause === 'role') return { tab: 'people', name: person }
	return null
}

export function lineOf(cap, row, role, person) {
	const base = { id: cap.id, title: cap.title || cap.id, class: cap.class || '', risk: cap.risk || 0, cause: '', sentence: null, hint: '', go: null, error: '' }
	if (!representativeOp(cap)) {
		// no operation stands for it (the hardware parameters): an administrator has it, for anybody else the answer cannot be asked
		if (role === 'admin') return Object.assign(base, { state: 'can' })
		return Object.assign(base, { state: 'unknown', hint: HINT_KEYS.unknown, cause: 'unknown' })
	}
	if (!row || row.error) {
		return Object.assign(base, { state: 'unknown', cause: 'unknown', hint: HINT_KEYS.unknown, error: row && row.error ? String(row.error.text || row.error.detail || '') : '' })
	}
	const outcome = checkOutcome(row)
	if (outcome.stop) return Object.assign(base, { state: 'stop' })
	if (outcome.allowed) return Object.assign(base, { state: 'can' })
	const cause = outcome.sentence.cause || 'unknown'
	// not delegable: whatever the refusal says, only an administrator may
	const adminOnly = cap.delegable === false || cause === 'not_delegable'
	const shown = adminOnly ? 'not_delegable' : cause
	return Object.assign(base, {
		state: adminOnly ? 'admin_only' : 'cannot',
		cause: shown,
		sentence: outcome.sentence,
		hint: hintOf(shown, outcome.legacy),
		go: goOf(outcome.legacy && shown !== 'condition' ? 'role' : shown, outcome, person || '')
	})
}

// the state of an area from its lines. Stopping is always allowed, so it does not count: an area that only has stops is "can".
function areaState(lines) {
	const core = lines.filter(l => l.state !== 'stop')
	if (!core.length) return 'can'
	const allowed = core.filter(l => l.state === 'can')
	const n = core.length
	if (allowed.length === n) return 'can'
	if (core.filter(l => l.state === 'unknown').length === n) return 'unknown'
	if (!allowed.length) return core.filter(l => l.state === 'admin_only').length === n ? 'admin_only' : 'cannot'
	return allowed.every(l => l.class === 'read') ? 'view' : 'partial'
}

export function areaView(area, capsById, rows, role, person) {
	const lines = area.caps.filter(id => capsById[id]).map(id => lineOf(capsById[id], rows[id], role, person))
	const counts = { can: 0, stop: 0, cannot: 0, admin_only: 0, unknown: 0 }
	lines.forEach(l => { counts[l.state] += 1 })
	return { id: area.id, icon: area.icon, state: areaState(lines), counts, lines, unknown: counts.unknown > 0, total: lines.length }
}

// what the person has, in one list, each with the reason it is there (the own roles are shown as profiles: the service treats them as such)
export function sourcesOf(input) {
	const x = input || {}
	const p = x.person || {}
	const role = String(x.role || p.role || '')
	const out = []
	out.push({ kind: 'role', role, own: !isBaseRole(role), reason: isBaseRole(role) ? 'who_src_role' : 'who_src_own_role' })
	list(x.roleGroups).filter(g => g !== role).forEach(g => out.push({ kind: 'own_role', name: g, reason: 'who_src_own_role' }))
	list(p.profiles).forEach(id => out.push({ kind: 'profile', id, reason: 'who_src_profile' }))
	viaGroups(p).forEach(v => out.push({ kind: 'group', group: v.group, profiles: v.profiles, reason: 'who_src_group' }))
	list(p.groups).filter(g => !viaGroups(p).some(v => v.group === g)).forEach(g => out.push({ kind: 'group', group: g, profiles: [], reason: 'who_src_group' }))
	if (p.ceiling) out.push({ kind: 'ceiling', id: p.ceiling, reason: 'who_src_ceiling' })
	return out
}

export function personView(input) {
	const x = input || {}
	const p = x.person || {}
	const role = String(x.role || p.role || '')
	const name = String(x.name || p.name || '')
	const caps = list(x.caps)
	const byId = {}
	caps.forEach(c => { byId[c.id] = c })
	const rows = x.rows || {}
	const areas = AREAS.map(a => areaView(a, byId, rows, role, name))
	const summary = { can: 0, view: 0, partial: 0, cannot: 0, admin_only: 0, unknown: 0 }
	areas.forEach(a => { summary[a.state] += 1 })
	return { name, role, governed: !!p.governed, damaged: !!p.damaged, sources: sourcesOf({ person: p, role, roleGroups: x.roleGroups }), areas, summary }
}

export function gridRows(views) {
	return list(views).map(v => {
		const cells = {}
		v.areas.forEach(a => { cells[a.id] = a.state })
		return { name: v.name, role: v.role, cells }
	})
}

// worst first; an area that can everything is not restricted, and a state the service could not give comes after the ones it did
const SEVERITY = Object.freeze(['cannot', 'admin_only', 'partial', 'view', 'unknown'])

export function restrictedAreas(cells, n) {
	const c = cells || {}
	const rows = AREAS.filter(a => SEVERITY.indexOf(c[a.id]) >= 0).map(a => ({ id: a.id, state: c[a.id] }))
	rows.sort((x, y) => SEVERITY.indexOf(x.state) - SEVERITY.indexOf(y.state))
	return rows.slice(0, n > 0 ? n : 2)
}
