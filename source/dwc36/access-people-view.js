'use strict'

// Pure helpers of the read-only screen Access > People and groups (DISENO-PANTALLAS sections 2.3 and 5). No imports of the page, no DOM: the components
// only draw what these functions return and a test loads this file in node. Nothing here decides access: the people come from users.list, what each
// has from access.person.get, the groups from access.groups.list / get and the answer of the checker from access.check. This file only arranges them.
//
//   BASE_ROLES                        the four base roles (the custom roles are the others)
//   accessStateOf(person)             'governed' (the evaluator decides) | 'admin' | 'base' (the table of roles decides) | 'unknown'
//   peopleRows(users, groups, persons, text)   the rows of the people table: role, groups, own profiles, ceiling, access state; text filters by name
//   groupRows(groups, text)           the rows of the groups table, custom roles included (read only)
//   roleGroupsOf(name, groups)        the custom roles (shown as read-only groups) that a person holds
//   viaGroups(person)                 [{ group, profiles }]: the profiles that come through the groups of a person
//   checkRequest(form, user)          the arguments of access.check for the form of "What this person can do"
//   checkOutcome(answer, options)     what the checker answered, ready to draw: the sentence of its cause, who decided, the other rules
//   MODE_CHOICES / VIA_CHOICES / TRISTATE   the values the form offers

import { causeOfDecision, conditionPhrase } from './access-reason.js'

export const BASE_ROLES = Object.freeze(['viewer', 'operator', 'technician', 'admin'])
export const MODE_CHOICES = Object.freeze(['', 'now', 'laser', 'cnc', 'fff'])
export const VIA_CHOICES = Object.freeze(['session', 'key', 'macro', 'local'])
export const TRISTATE = Object.freeze(['', 'yes', 'no'])
export const OTHERS_COLLAPSED = 6

const ADMIN = 'admin'

function list(x) {
	return Array.isArray(x) ? x.slice() : []
}

function sameText(a, b) {
	return String(a || '').toLowerCase() === String(b || '').toLowerCase()
}

export function isBaseRole(role) {
	return BASE_ROLES.includes(role)
}

export function accessStateOf(person) {
	if (!person || typeof person !== 'object') return 'unknown'
	if (person.governed) return 'governed'
	return person.role === ADMIN ? 'admin' : 'base'
}

// the groups of a person: what access.person.get says, else the groups whose member list has the person
function groupsOfPerson(name, person, groups) {
	if (person && Array.isArray(person.groups)) return person.groups.slice()
	return list(groups && groups.groups).filter(g => g.source === 'group' && list(g.members).some(m => sameText(m, name))).map(g => g.name)
}

export function peopleRows(users, groups, persons, text) {
	const known = persons || {}
	const rows = list(users).map(u => {
		const p = known[u.name] || null
		return {
			name: String(u.name),
			role: String(u.role),
			customRole: !isBaseRole(u.role),
			groups: groupsOfPerson(u.name, p, groups),
			profiles: p ? list(p.profiles) : [],
			ceiling: (p && p.ceiling) || '',
			state: accessStateOf(p ? Object.assign({ role: u.role }, p) : null)
		}
	})
	const q = String(text || '').trim().toLowerCase()
	return q ? rows.filter(r => r.name.toLowerCase().includes(q)) : rows
}

export function groupRows(groups, text) {
	const rows = list(groups && groups.groups).map(g => ({
		name: String(g.name),
		readonly: !!g.readonly,
		role: g.source === 'role',
		description: String(g.description || ''),
		profiles: list(g.profiles),
		ceiling: g.ceiling || '',
		members: list(g.members),
		base: g.role && g.role.base ? String(g.role.base) : '',
		grants: g.role ? list(g.role.grant).length : 0,
		denies: g.role ? list(g.role.deny).length : 0
	}))
	const q = String(text || '').trim().toLowerCase()
	return q ? rows.filter(r => r.name.toLowerCase().includes(q)) : rows
}

export function roleGroupsOf(name, groups) {
	return list(groups && groups.groups).filter(g => g.source === 'role' && list(g.members).some(m => sameText(m, name))).map(g => g.name)
}

export function viaGroups(person) {
	const via = (person && person.via_groups) || {}
	return Object.keys(via).map(g => ({ group: g, profiles: list(via[g]) }))
}

// ---- "What this person can do" ----

const YES_NO = { yes: true, no: false }

export function checkRequest(form, user) {
	const f = form || {}
	const out = { user: String(user || ''), operation: String(f.operation || '').trim() }
	if (String(f.target || '').trim()) out.target = String(f.target).trim()
	if (f.mode === 'now') out.modeNow = true
	else if (f.mode) out.mode = String(f.mode)
	if (f.job in YES_NO) out.jobRunning = YES_NO[f.job]
	if (f.machineOn in YES_NO) out.machineOn = YES_NO[f.machineOn]
	if (f.via) out.via = String(f.via)
	return out
}

// explicit keys (not built at run time) so the i18n checks can see that each one is used
const WHY_KEYS = Object.freeze({
	operation: 'check_why_operation',
	target: 'check_why_target',
	mode: 'check_cond_mode',
	job_running: 'check_cond_job_running',
	machine_on: 'check_cond_machine_on',
	via: 'check_cond_via',
	risk_max: 'check_cond_risk_max'
})
const SOURCE_KEYS = Object.freeze({
	base: 'check_source_base',
	role: 'check_source_role',
	attached: 'check_source_attached',
	ceiling: 'check_source_ceiling'
})
// the legacy engine (the table of roles) names its reason with these codes (permissions.decide)
const LEGACY_KEYS = Object.freeze({
	role: 'reason_role',
	camera: 'reason_camera',
	mode: 'reason_mode',
	mode_unknown: 'reason_mode_unknown',
	denied: 'reason_role_denied'
})
const LEGACY_KEY = 'reason_legacy'
const LEGACY_DAMAGED_KEY = 'reason_legacy_damaged'

function whyKey(w) {
	const s = String(w)
	if (s.startsWith('condition:')) return WHY_KEYS[s.slice(10)] || 'check_cond_unknown'
	return WHY_KEYS[s] || 'check_cond_unknown'
}

function otherRow(r) {
	return {
		source: SOURCE_KEYS[r.source] || SOURCE_KEYS.attached,
		profile: String(r.profile),
		rule: String(r.id),
		deny: r.decision === 'deny',
		matched: !!r.matched,
		why: list(r.why).map(whyKey)
	}
}

// the sentence of a refusal of the evaluator, by cause (access-reason.js knows the cause of a code)
function accessSentence(answer, role) {
	const reason = answer.reason || {}
	const rows = list(answer.rules)
	const cause = causeOfDecision(reason)
	if (reason.code === 'stop') return { key: 'reason_stop', params: {}, cause: 'stop' }
	if (answer.allowed) return { key: '', params: {}, cause: '' }
	if (reason.code === 'escalated') return { key: 'reason_escalated', params: { tier: reason.needed_tier || '' }, cause: 'escalated' }
	if (reason.code === 'bad_request') return { key: 'reason_bad_request', params: {}, cause: 'bad_request' }
	if (cause === 'profile') return { key: 'reason_deny', params: { profile: reason.profile || '', rule: reason.id || '' }, cause }
	if (cause === 'ceiling') {
		const names = reason.ceiling ? [reason.ceiling] : [...new Set(rows.filter(r => r.source === 'ceiling').map(r => r.profile))]
		return { key: 'reason_ceiling', params: { ceiling: names.join(', ') }, cause }
	}
	if (cause === 'not_delegable') return { key: 'reason_admin_only', params: {}, cause }
	if (cause === 'no_rule') return { key: 'reason_no_rule', params: {}, cause }
	if (cause === 'condition') {
		const near = rows.find(r => r.decision === 'allow' && !r.matched && list(r.why).some(w => String(w).startsWith('condition:')))
		const keys = list(reason.failed_conditions).map(k => WHY_KEYS[k] || 'check_cond_unknown')
		return { key: 'reason_condition', params: { rule: near ? near.id : '', condition: '' }, paramKeys: { condition: keys }, cause }
	}
	void role
	return { key: 'reason_unknown', params: {}, cause: 'unknown' }
}

function legacySentence(answer, damaged) {
	const reason = answer.reason || {}
	const code = String(reason.code || '')
	const second = damaged ? LEGACY_DAMAGED_KEY : LEGACY_KEY
	if (answer.allowed) return { key: second, params: {}, cause: '', extra: '' }
	const key = LEGACY_KEYS[code] || 'reason_unknown'
	return { key, params: {}, cause: causeOfDecision(reason), extra: second }
}

// answer: the answer of access.check; options: { damaged } (the access file is damaged: the answer comes from the table of roles for that reason)
export function checkOutcome(answer, options) {
	const a = answer || {}
	const legacy = a.engine === 'legacy'
	const damaged = !!(options && options.damaged)
	const base = legacy ? legacySentence(a, damaged) : Object.assign({ extra: '', paramKeys: null }, accessSentence(a, ''))
	const deciding = a.deciding && a.deciding.profile ? { profile: String(a.deciding.profile), rule: String(a.deciding.id), source: SOURCE_KEYS[a.deciding.source] || SOURCE_KEYS.attached } : null
	const others = list(a.rules).filter(r => !(a.deciding && r.profile === a.deciding.profile && r.id === a.deciding.id)).map(otherRow)
	others.sort((x, y) => (x.matched === y.matched ? 0 : x.matched ? -1 : 1))
	return {
		allowed: !!a.allowed,
		legacy,
		stop: !!(a.reason && a.reason.code === 'stop'),
		operation: String(a.operation || ''),
		target: String(a.target || ''),
		sentence: base,
		deciding,
		others,
		conditionNote: base.cause === 'condition',
		legacyAnswer: a.legacy ? { allowed: !!a.legacy.allowed } : null
	}
}

export { conditionPhrase }
