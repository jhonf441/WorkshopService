'use strict'

// Thin calls to the access.* operations of the service (administrator only; DISENO-PANTALLAS section 8, step 0). Each wrapper builds the arguments the
// operation documents (dsf/access_ops.py) and calls it through the one API client; it adds no rule and no cache. The answer is the service's.
//
//   accessApi.profilesList()                          { damaged, profiles, base, limits, never_attached }
//   accessApi.profilesGet(name)                       { name, base, document, attached_to, version?, versions? }
//   accessApi.profileVersions(name)                   { name, versions: [{ n, active, at, by, doc }], max }
//   accessApi.profilesSet(document, opts)             saves a profile (a new version); opts: { confirm } as of api()
//   accessApi.profilesRemove(name, opts)
//   accessApi.profileRollback(name, version, opts)
//   accessApi.groupsList() / groupsGet(name) / groupsSet({ name, description, profiles, members }, opts) / groupsRemove(name, opts)
//   accessApi.attach(subject, what, opts)             subject { user } or { group }; what { profile } or { memberOf }
//   accessApi.detach(subject, what, opts)
//   accessApi.ceilingSet(subject, profile, opts)      profile '' removes the ceiling
//   accessApi.personGet(user)
//   accessApi.check(args)                             { user, operation, target?, args?, mode?, modeNow?, jobRunning?, machineOn?, via? }
//
// The operations of every screen are listed once in ACCESS_OPS: a test checks each one against dsf/golden/api_contract.json.

import { api } from './workshop-api.js'

export const ACCESS_OPS = Object.freeze({
	profilesList: 'access.profiles.list',
	profilesGet: 'access.profiles.get',
	profilesSet: 'access.profiles.set',
	profilesRemove: 'access.profiles.remove',
	profileVersions: 'access.profile.versions',
	profileRollback: 'access.profile.rollback',
	groupsList: 'access.groups.list',
	groupsGet: 'access.groups.get',
	groupsSet: 'access.groups.set',
	groupsRemove: 'access.groups.remove',
	attach: 'access.attach',
	detach: 'access.detach',
	ceilingSet: 'access.ceiling.set',
	personGet: 'access.person.get',
	check: 'access.check'
})

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

export function makeAccessApi(call) {
	const O = ACCESS_OPS
	return {
		profilesList: () => call(O.profilesList),
		profilesGet: name => call(O.profilesGet, { name }),
		profileVersions: name => call(O.profileVersions, { name }),
		profilesSet: (document, opts) => call(O.profilesSet, { document }, opts),
		profilesRemove: (name, opts) => call(O.profilesRemove, { name }, opts),
		profileRollback: (name, version, opts) => call(O.profileRollback, { name, version }, opts),
		groupsList: () => call(O.groupsList),
		groupsGet: name => call(O.groupsGet, { name }),
		groupsSet: (group, opts) => call(O.groupsSet, groupArgs(group), opts),
		groupsRemove: (name, opts) => call(O.groupsRemove, { name }, opts),
		attach: (subject, what, opts) => call(O.attach, attachArgs(subject, what), opts),
		detach: (subject, what, opts) => call(O.detach, attachArgs(subject, what), opts),
		ceilingSet: (subject, profile, opts) => call(O.ceilingSet, Object.assign(subjectArgs(subject), { profile: String(profile || '') }), opts),
		personGet: user => call(O.personGet, { user }),
		check: args => call(O.check, checkArgs(args)),
		capabilities: () => call(CAPABILITIES_OP)
	}
}

// The capabilities (category, class, risk, lock) the builder shows come from the service, the one origin of that list (roles.list, administrator only)
export const CAPABILITIES_OP = 'roles.list'

export const accessApi = makeAccessApi(api)
