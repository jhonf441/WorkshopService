'use strict'

// My session, worked out from plain data (pure).
//
//   modeOf(session)       what the sheet shows: 'resolving' | 'damaged' | 'in' (a person is signed in) | 'open' (no people, or the
//                         roles are switched off: everybody is an administrator, there is nothing to sign in to) | 'out'
//   roleText(session, baseRoles)   { base, custom }: a base role is said by its name of the catalogs; a role of the workshop's own
//                         by the name they gave it, with the base role it starts from when the service tells it
//   pinProblems(form)     { old, fresh, again }: what is wrong in the change-PIN form before anything is sent ('' = fine).
//                         Only what the page can know: the length and the rest of the policy are the service's to judge.

const OUT = ['signed-out', 'signing-in', 'expired', 'pin-locked']

export function modeOf(s) {
	const x = s || {}
	if (x.state === 'resolving') return 'resolving'
	if (x.damaged) return 'damaged'
	if (OUT.indexOf(x.state) >= 0) return 'out'
	if (!x.configured || x.usersOff || !x.name) return 'open'
	return 'in'
}

export function roleText(s, baseRoles) {
	const x = s || {}
	const bases = baseRoles || []
	const name = String(x.roleName || x.role || '')
	if (bases.indexOf(name) >= 0) return { base: name, custom: '' }
	return { base: bases.indexOf(x.role) >= 0 && x.role !== name ? x.role : '', custom: name }
}

export function pinProblems(form) {
	const f = form || {}
	const fresh = String(f.newPin || '')
	return {
		old: String(f.oldPin || '') ? '' : 'missing',
		fresh: !fresh ? 'need_new' : !/^\d+$/.test(fresh) ? 'digits' : fresh === String(f.oldPin || '') ? 'same' : '',
		again: fresh && String(f.again || '') !== fresh ? 'mismatch' : ''
	}
}
