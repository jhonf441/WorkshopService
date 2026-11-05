'use strict'

// A change of identity cleans the page (ESTANDAR 3.1): what the person who left had read must not stay in memory. Pure logic, used by
// role-mixin.js; tests/session-reset.test.js loads this file in node.
//
//   sessionKey(role, out)                      'operator|in' / '|out': what changes when someone signs in, out or the role changes
//   sessionChangeKind(last, key, known)        'signed-in' | 'signed-out' | 'role-changed' | 'known' | '' (nothing to tell)
//                                              last = the previous key (null: the identity was unknown), known = the identity is not null now
//   resetSessionData(vm, names)                puts the data fields in `names` back to their initial value (the component option
//                                              `sessionData: ['users', 'dlg', ...]`); hiding with v-if is not enough

export function sessionKey(role, out) {
	return (role || '') + '|' + (out ? 'out' : 'in')
}

export function sessionChangeKind(last, key, known) {
	if (!known) return ''
	if (last === null || last === undefined) return 'known'
	if (last === key) return ''
	const was = last.split('|')[1]
	const now = key.split('|')[1]
	if (now === 'out') return 'signed-out'
	if (was === 'out') return 'signed-in'
	return 'role-changed'
}

export function resetSessionData(vm, names) {
	if (!names || !names.length) return
	const make = vm.$options && vm.$options.data
	const fresh = typeof make === 'function' ? make.call(vm, vm) : make || {}
	names.forEach(name => {
		if (Object.prototype.hasOwnProperty.call(fresh, name)) vm[name] = fresh[name]
	})
}
