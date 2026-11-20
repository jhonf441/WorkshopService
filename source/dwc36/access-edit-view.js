'use strict'

// Pure helpers of the editing of people and groups (DISENO-PANTALLAS sections 2.3, 2.5, 5 and 7; step 4). No imports, no DOM: the components draw what these
// functions return and a test loads this file in node. Nothing here decides access: the service is the judge and refuses what the rules of the owner forbid
// (self_change, lockout, admin_profile, no_allow, plugin_ceiling, in_use...). This file only decides what the screen OFFERS, so that the refusals are rare, and
// how a change is described for the one dialog (before, after, outcome).
//
//   Brief      { profiles: [], groups: [], ceiling: name|null }    what the service keeps of a person (groups = their groups) or of a group
//                                                                   (groups = their members): the same shape access-diff.js compares
//   change     { kind, subject: { user } | { group }, profile?, group?, item?, name?, description? }, kind one of CHANGE_KINDS
//   myName(identity) / isSelf(name, identity)           the person at this screen (identity.user.name)
//   briefOfPerson(answer) / briefOfGroup(answer)        a Brief from access.person.get / access.groups.get
//   sameBrief(a, b)                                     the service answers the same now as when the dialog was opened (nobody else changed it)
//   attachCandidates(profiles, attached)                [{ name, kind: 'own'|'base'|'plugin' }] that may be attached (never base.administrator)
//   ceilingPool(profiles, current) / ceilingCandidates(pool, docs)   profiles that may be a ceiling (own or base, with an allow rule; never a plugin one)
//   groupChoices(groups, memberOf) / memberChoices(users, members, identity)   what the selectors offer
//   groupNameProblem(name, groups, reserved)            '' or the key of the sentence that says why the name cannot be used
//   applyChange(brief, change)                          the Brief the change would leave (a prediction for the dialog, not a rule)
//   describeChange(change, info)                        keys and params of the title, the verb and the outcome of a change
//   sideLines(side, diff, brief, kind)                  lines of one side of the dialog: [{ section, label, items: [{ name, sign }] }]
//   governedAfter(brief, groups)                        true when profiles or a ceiling (own or of a group) would decide for the person
//   refusalOf(error)                                    { code, text, handled } of a refusal of the service (its own translated sentence)
//   HANDLED_CODES                                       the refusal codes the screens show

export const NEVER_ATTACHED = 'base.administrator'
export const CHANGE_KINDS = Object.freeze(['attach', 'detach', 'join', 'leave', 'ceiling', 'group_save', 'group_remove'])
// the codes of access_store.AccessError that the edits can meet; each has its sentence in dsf/i18n (access_err_<code>), which the service translates
export const HANDLED_CODES = Object.freeze(['self_change', 'lockout', 'admin_profile', 'no_allow', 'plugin_ceiling', 'in_use', 'already', 'not_attached', 'reserved_name',
	'invalid_name', 'invalid_args', 'too_many', 'unknown_profile', 'unknown_group', 'unknown_user', 'damaged', 'save_failed'])

const GROUP_NAME = /^[\p{L}\p{M}\p{N}_ .-]{1,32}$/u

function list(x) {
	return Array.isArray(x) ? x.slice() : []
}

function key(s) {
	return String(s === null || s === undefined ? '' : s).toLowerCase()
}

export function myName(identity) {
	return identity && identity.user && identity.user.name ? String(identity.user.name) : ''
}

export function isSelf(name, identity) {
	const me = myName(identity)
	return !!me && key(me) === key(name)
}

export function briefOfPerson(p) {
	const x = p || {}
	return { profiles: list(x.profiles), groups: list(x.groups), ceiling: x.ceiling || null }
}

export function briefOfGroup(g) {
	const x = g || {}
	return { profiles: list(x.profiles), groups: list(x.members), ceiling: x.ceiling || null }
}

export function sameBrief(a, b) {
	const x = a || { profiles: [], groups: [], ceiling: null }
	const y = b || { profiles: [], groups: [], ceiling: null }
	return JSON.stringify([x.profiles, x.groups, x.ceiling || null]) === JSON.stringify([y.profiles, y.groups, y.ceiling || null])
}

// ---- what the selectors offer ----

export function attachCandidates(profiles, attached) {
	const p = profiles || {}
	const never = new Set(list(p.never_attached).concat([NEVER_ATTACHED]).map(key))
	const have = new Set(list(attached).map(key))
	const out = []
	const add = (rows, kind) => list(rows).forEach(r => {
		const name = String(r.name)
		if (!never.has(key(name)) && !have.has(key(name))) out.push({ name, kind })
	})
	add(p.profiles, 'own')
	add(p.base, 'base')
	add(p.plugin, 'plugin')
	return out
}

export function hasAllowRule(doc) {
	return list(doc && doc.rules).some(r => r && r.decision === 'allow')
}

// A ceiling is an own or base profile (a plugin one never) with at least one rule; whether one of them ALLOWS something is read from its document
// (ceilingCandidates), because the list only says how many rules there are. The profile of the administrators is no ceiling worth offering.
export function ceilingPool(profiles, current) {
	const p = profiles || {}
	const out = []
	const add = (rows, kind) => list(rows).forEach(r => {
		const name = String(r.name)
		if (name !== NEVER_ATTACHED && key(name) !== key(current) && Number(r.rules) > 0) out.push({ name, kind })
	})
	add(p.profiles, 'own')
	add(p.base, 'base')
	return out
}

export function ceilingCandidates(pool, docs) {
	const d = docs || {}
	return list(pool).filter(c => hasAllowRule(d[c.name]))
}

export function groupChoices(groups, memberOf) {
	const have = new Set(list(memberOf).map(key))
	return list(groups && groups.groups).filter(g => g.source === 'group' && !have.has(key(g.name))).map(g => String(g.name))
}

export function memberChoices(users, members, identity) {
	const have = new Set(list(members).map(key))
	const me = key(myName(identity))
	return list(users).map(u => String(u && u.name !== undefined ? u.name : u)).filter(n => !have.has(key(n)) && key(n) !== me)
}

// The service is the judge of the name; this only keeps the screen from sending what it already knows will be refused, or from replacing a group that exists
export function groupNameProblem(name, groups, reserved) {
	const n = String(name || '').split(/\s+/).filter(Boolean).join(' ')
	if (!GROUP_NAME.test(n)) return 'groups_name_rule'
	if (list(reserved).some(r => key(r) === key(n))) return 'pedit_name_reserved'
	if (list(groups && groups.groups).some(g => key(g.name) === key(n))) return 'pedit_name_taken'
	return ''
}

// ---- the dialog ----

export function applyChange(brief, change) {
	const b = brief ? { profiles: list(brief.profiles), groups: list(brief.groups), ceiling: brief.ceiling || null } : null
	const c = change || {}
	if (c.kind === 'group_remove') return null
	if (!b) return { profiles: [], groups: [], ceiling: null }
	const without = (l, x) => l.filter(y => key(y) !== key(x))
	const withItem = (l, x) => (l.some(y => key(y) === key(x)) ? l : l.concat([x]))
	if (c.kind === 'attach') b.profiles = withItem(b.profiles, c.profile)
	else if (c.kind === 'detach') b.profiles = without(b.profiles, c.profile)
	else if (c.kind === 'join') b.groups = withItem(b.groups, c.item)
	else if (c.kind === 'leave') b.groups = without(b.groups, c.item)
	else if (c.kind === 'ceiling') b.ceiling = c.profile ? String(c.profile) : null
	return b
}

// keys of the area `access` (literal, so a test sees every one): the title, the verb and the outcome of a change; `info`: { members, governedBefore, governedAfter }
export function describeChange(change, info) {
	const c = change || {}
	const i = info || {}
	const who = (c.subject && (c.subject.user || c.subject.group)) || ''
	const onGroup = !!(c.subject && c.subject.group)
	const params = { who, profile: c.profile || '', group: c.group || '', name: c.name || '', n: i.members || 0 }
	let out
	if (c.kind === 'attach') out = { title: 'change_attach', verb: 'change_do_attach', outcome: onGroup ? 'pedit_result_attach_group' : 'pedit_result_attach_person' }
	else if (c.kind === 'detach') out = { title: 'change_detach', verb: 'change_do_detach', outcome: onGroup ? 'pedit_result_detach_group' : 'pedit_result_detach_person' }
	else if (c.kind === 'join') out = { title: 'change_join', verb: 'change_do_join', outcome: 'pedit_result_join' }
	else if (c.kind === 'leave') out = { title: 'change_leave', verb: 'change_do_leave', outcome: 'pedit_result_leave' }
	else if (c.kind === 'ceiling' && c.profile) out = { title: 'change_ceiling', verb: 'change_do_ceiling', outcome: 'pedit_result_ceiling_set' }
	else if (c.kind === 'ceiling') out = { title: 'change_ceiling_clear', verb: 'change_do_ceiling_clear', outcome: 'pedit_result_ceiling_clear' }
	else if (c.kind === 'group_save') out = { title: 'change_group_create', verb: 'change_do_group_create', outcome: 'pedit_result_group_create' }
	else if (c.kind === 'group_remove') out = { title: 'change_group_remove', verb: 'change_do_group_remove', outcome: 'pedit_result_group_remove' }
	else out = { title: 'pedit_unknown', verb: 'common_cancel', outcome: '' }
	let note = ''
	if (!onGroup && c.kind !== 'group_save' && c.kind !== 'group_remove') {
		if (!i.governedBefore && i.governedAfter) note = 'pedit_result_governed_on'
		else if (i.governedBefore && !i.governedAfter) note = 'pedit_result_governed_off'
	}
	return Object.assign(out, { params, note })
}

// What the dialog lists on one side. `diff` is diffAttachment(before, after); a removal or a creation has no brief on one side.
export function sideLines(side, diff, brief, kind) {
	const d = diff || { profiles: { added: [], removed: [] }, groups: { added: [], removed: [] }, ceiling: { before: null, after: null, changed: false } }
	const b = brief || { profiles: [], groups: [], ceiling: null }
	const items = (all, part) => all.map(name => ({ name, sign: '' })).concat(side === 'before' ? part.removed.map(name => ({ name, sign: '-' })) : part.added.map(name => ({ name, sign: '+' })))
	// `brief` is the side being drawn (before: what there was; after: what there will be); the kept ones come first, then the ones that go / arrive
	const rows = (field, section, label) => {
		const part = d[field]
		const all = list(b[field]).filter(n => (side === 'before' ? part.removed.indexOf(n) < 0 : part.added.indexOf(n) < 0))
		return { section, label, items: items(all, part) }
	}
	const ceil = d.ceiling
	const ceilingItems = []
	if (side === 'before' && ceil.before) ceilingItems.push({ name: ceil.before, sign: ceil.changed ? '-' : '' })
	if (side === 'after' && ceil.after) ceilingItems.push({ name: ceil.after, sign: ceil.changed ? '+' : '' })
	return [
		rows('profiles', 'profiles', kind === 'group' ? 'groups_col_profiles' : 'people_profiles'),
		rows('groups', 'groups', kind === 'group' ? 'groups_members' : 'people_groups'),
		{ section: 'ceiling', label: 'people_ceiling', items: ceilingItems }
	]
}

// Would profiles or a ceiling decide for the person? As the service says it: any profile or ceiling of their own or through a group they are in.
export function governedAfter(brief, groups) {
	const b = brief || { profiles: [], groups: [], ceiling: null }
	if (b.profiles.length || b.ceiling) return true
	const all = list(groups && groups.groups).filter(g => g.source === 'group')
	return b.groups.some(name => {
		const g = all.find(x => key(x.name) === key(name))
		return !!g && (list(g.profiles).length > 0 || !!g.ceiling)
	})
}

// A refusal of the service: its own sentence (already in the language of the page) and whether this screen knows the code
export function refusalOf(error) {
	const e = error || {}
	const code = String(e.code || '')
	return { code, text: String(e.message || ''), handled: HANDLED_CODES.indexOf(code) >= 0 }
}
