'use strict'

// Thin calls to the access.* operations of the service (administrator only; DISENO-PANTALLAS section 8, step 0). Each wrapper builds the arguments the
// operation documents (dsf/access_ops.py) and calls it through the one API client; it adds no rule and no cache. The answer is the service's.
//
//   accessApi.profilesList()                          { damaged, profiles, base, limits, never_attached }
//   accessApi.profilesGet(name)                       { name, base, document, attached_to, version?, versions? }
//   accessApi.profileVersions(name)                   { name, versions: [{ n, active, at, by, doc }], max }
//   accessApi.profilesSet(document, opts)             saves a profile (a new version); opts: { confirm } as of api()
//   accessApi.profilesValidate(document)              dry run of profilesSet: { valid, name, created, changed, version, warnings: [{ code, text }] }; the same refusals, nothing written
//   accessApi.profilesRemove(name, opts)
//   accessApi.profileRollback(name, version, opts)
//   accessApi.groupsList() / groupsGet(name) / groupsSet({ name, description, profiles, members }, opts) / groupsRemove(name, opts)
//   accessApi.attach(subject, what, opts)             subject { user } or { group }; what { profile } or { memberOf }
//   accessApi.detach(subject, what, opts)
//   accessApi.ceilingSet(subject, profile, opts)      profile '' removes the ceiling
//   accessApi.attachValidate(subject, what) / detachValidate(subject, what) / ceilingValidate(subject, profile) / groupsValidate(group, remove)
//                                                     dry runs of the four changes above: { valid, what, kind, name } or the same refusal the real call gives; nothing written
//   accessApi.personGet(user)
//   accessApi.people()                                users.list: { configured, enabled, damaged, users: [{ name, role, modes }], ... }
//   accessApi.auditList(args, opts)                   audit.list: { total, rows, users }; args as listArgs() of access-audit-view.js
//   accessApi.auditVerify(after, limit)               audit.verify: { ok, broken, checked, done, next_after, links, cuts, pre_chain_rows }
//   accessApi.auditExport(range, after, limit)        audit.export: { jsonl, rows, chained, done, next_after }
//   accessApi.auditSettings(settings, opts)           audit.settings: { settings }; without `settings` it only reads
//   accessApi.alarms(from, to, limit)                 activity.list of the type security_alarm (the alarms of the service): { total, rows, kinds }
//   accessApi.keysList()                              keys.list: { keys: [...], presets, kinds, max, cap_prefix } (never the key itself; read only)
//   accessApi.report()                                access.report: { generated, damaged, people, keys: [{ id, last_used, uses, idle_days, breadth, ... }], locked }
//   accessApi.review()                                access.review: { generated, damaged, findings, counts, high, limits }
//   accessApi.can(items, opts)                        auth.can (any role, only the caller): { configured, named, login_required, items: [{ operation, target, allowed, reason, text }] }, up to 100 items
//   accessApi.check(args)                             { user, operation, target?, args?, mode?, modeNow?, jobRunning?, machineOn?, via? }
//   accessApi.checkMany(user, items)                  the same operation with `items` (up to 100 requests of ONE person, each as the args of check without the user):
//                                                     { user, items: [the answer of check, or { operation, error }] }; one answer per request, in order
//
// The operations of every screen are listed once in ACCESS_OPS (and AUDIT_OPS for the activity screen): a test checks each one against dsf/golden/api_contract.json.

import { api } from './workshop-api.js'

export const ACCESS_OPS = Object.freeze({
	profilesList: 'access.profiles.list',
	profilesGet: 'access.profiles.get',
	profilesSet: 'access.profiles.set',
	profilesRemove: 'access.profiles.remove',
	profilesValidate: 'access.profiles.validate',
	profileVersions: 'access.profile.versions',
	profileRollback: 'access.profile.rollback',
	groupsList: 'access.groups.list',
	groupsGet: 'access.groups.get',
	groupsSet: 'access.groups.set',
	groupsRemove: 'access.groups.remove',
	attach: 'access.attach',
	detach: 'access.detach',
	ceilingSet: 'access.ceiling.set',
	attachValidate: 'access.attach.validate',
	detachValidate: 'access.detach.validate',
	ceilingValidate: 'access.ceiling.validate',
	groupsValidate: 'access.groups.validate',
	personGet: 'access.person.get',
	check: 'access.check'
})

// The operations of Security > Recorded activity (step 5): the audit ones and the read of the alarms, which the service logs as Activity events.
// Checked against the golden contract by tests/access-audit.test.js.
export const AUDIT_OPS = Object.freeze({
	auditList: 'audit.list',
	auditVerify: 'audit.verify',
	auditExport: 'audit.export',
	auditSettings: 'audit.settings',
	alarms: 'activity.list'
})

// the type of the events the alarms of the service are logged as (audit_alarms.EVENT_TYPE)
export const ALARM_TYPE = 'security_alarm'

// { user } or { group } -> the same, and nothing else (the service refuses both or none with invalid_args)
export function subjectArgs(subject) {
	const s = subject || {}
	const out = {}
	if (s.user) out.user = String(s.user)
	if (s.group) out.group = String(s.group)
	return out
}

export function attachArgs(subject, what) {
	const w = what || {}
	const out = subjectArgs(subject)
	if (w.profile) out.profile = String(w.profile)
	if (w.memberOf) out.member_of = String(w.memberOf)
	return out
}

export function groupArgs(group) {
	const g = group || {}
	const out = { name: String(g.name || '') }
	if (g.description !== undefined) out.description = String(g.description)
	if (g.profiles !== undefined) out.profiles = g.profiles.slice()
	if (g.members !== undefined) out.members = g.members.slice()
	return out
}

export function checkArgs(c) {
	const x = c || {}
	const out = { user: String(x.user || ''), operation: String(x.operation || '') }
	if (x.target) out.target = String(x.target)
	if (x.args && typeof x.args === 'object') out.args = x.args
	if (x.mode) out.mode = String(x.mode)
	if (x.modeNow !== undefined) out.mode_now = !!x.modeNow
	if (x.jobRunning !== undefined) out.job_running = !!x.jobRunning
	if (x.machineOn !== undefined) out.machine_on = !!x.machineOn
	if (x.via) out.via = String(x.via)
	return out
}

// one request of a batch: the fields of checkArgs, without the person (the call names it once)
export function checkItem(it) {
	const out = checkArgs(Object.assign({}, it, { user: '' }))
	delete out.user
	return out
}

export function makeAccessApi(call) {
	const O = Object.assign({}, ACCESS_OPS, AUDIT_OPS)
	return {
		profilesList: () => call(O.profilesList),
		profilesGet: name => call(O.profilesGet, { name }),
		profileVersions: name => call(O.profileVersions, { name }),
		profilesSet: (document, opts) => call(O.profilesSet, { document }, opts),
		profilesRemove: (name, opts) => call(O.profilesRemove, { name }, opts),
		profilesValidate: document => call(O.profilesValidate, { document }),
		profileRollback: (name, version, opts) => call(O.profileRollback, { name, version }, opts),
		groupsList: () => call(O.groupsList),
		groupsGet: name => call(O.groupsGet, { name }),
		groupsSet: (group, opts) => call(O.groupsSet, groupArgs(group), opts),
		groupsRemove: (name, opts) => call(O.groupsRemove, { name }, opts),
		attach: (subject, what, opts) => call(O.attach, attachArgs(subject, what), opts),
		detach: (subject, what, opts) => call(O.detach, attachArgs(subject, what), opts),
		ceilingSet: (subject, profile, opts) => call(O.ceilingSet, Object.assign(subjectArgs(subject), { profile: String(profile || '') }), opts),
		attachValidate: (subject, what) => call(O.attachValidate, attachArgs(subject, what), { quiet: true }),
		detachValidate: (subject, what) => call(O.detachValidate, attachArgs(subject, what), { quiet: true }),
		ceilingValidate: (subject, profile) => call(O.ceilingValidate, Object.assign(subjectArgs(subject), { profile: String(profile || '') }), { quiet: true }),
		groupsValidate: (group, remove) => call(O.groupsValidate, Object.assign(groupArgs(group), remove ? { remove: true } : {}), { quiet: true }),
		personGet: user => call(O.personGet, { user }),
		auditList: (args, opts) => call(O.auditList, args, opts),
		auditVerify: (after, limit) => call(O.auditVerify, { after: after | 0, limit: limit || 2000 }),
		auditExport: (range, after, limit) => call(O.auditExport, { from: range.from, to: range.to, after: after | 0, limit: limit || 1000 }),
		auditSettings: (settings, opts) => call(O.auditSettings, settings ? { settings } : {}, opts),
		alarms: (from, to, limit) => call(O.alarms, { from, to, type: ALARM_TYPE, limit: limit || 5 }),
		check: args => call(O.check, checkArgs(args)),
		checkMany: (user, items, opts) => call(O.check, { user: String(user || ''), items: (items || []).map(checkItem) }, opts),
		can: (items, opts) => call(CAN_OP, { operations: items }, opts),
		capabilities: () => call(CAPABILITIES_OP),
		keysList: () => call(KEYS_OP),
		report: () => call(REPORT_OP),
		review: () => call(REVIEW_OP),
		people: () => call(PEOPLE_OP)
	}
}

// The capabilities (category, class, risk, lock) the builder shows come from the service, the one origin of that list (roles.list, administrator only)
export const CAPABILITIES_OP = 'roles.list'

// The people of the workshop (role, modes) come from users.list, the operation the Users section already uses (administrator only)
export const PEOPLE_OP = 'users.list'

// The keys screen only reads: the keys of the external services (keys.list, the card of the API section creates and edits them), the people and keys
// report (last use of each key) and the review of accesses (its finding of a wide key that is not used)
export const KEYS_OP = 'keys.list'

// The caller's own answers (any role): the cause of a locked control; asked in one batch by access-can.js
export const CAN_OP = 'auth.can'
export const REPORT_OP = 'access.report'
export const REVIEW_OP = 'access.review'

export const accessApi = makeAccessApi(api)
