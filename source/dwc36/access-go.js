'use strict'

// "Go to the object" from Security (review, report) and from the block with a reason: the page asks the Access section to show a tab AND, when it names one,
// the object on it (a profile by name, a person or a group by name, a key by id). Pure: no DOM, no store.
//
//   go          { tab: 'profiles' | 'people' | 'templates' | 'can' | 'keys' | '', name?: string, id?: string, n: number }   ('can': name = the person)     n changes with every request (a watcher fires on it)
//   goPayload(x)             the request a button sends: a tab name (the old form) or { tab, name?, id? } -> { tab, name, id }
//   nextGo(prev, x)          the `go` after a request: the request and n + 1
//   focusOf(go, tab)         { name, id, n } when `go` asks for something on `tab`, else null (a tab opened by hand carries no request)
//   profileFocus(list, name)           { name, base } of the profile in access.profiles.list (own, base or plugin), or null
//   peopleFocus(users, groups, name)   { kind: 'person' | 'group', name } (a person wins over a group of the same name), or null
//   keyFocus(keys, id)                 the id of the key in the list of keys, or ''

export const GO_TABS = Object.freeze(['profiles', 'people', 'templates', 'can', 'keys'])

function key(s) {
	return String(s === null || s === undefined ? '' : s).toLowerCase()
}

export function goPayload(x) {
	if (typeof x === 'string') return { tab: x, name: '', id: '' }
	const o = x && typeof x === 'object' ? x : {}
	return { tab: String(o.tab || ''), name: o.name ? String(o.name) : '', id: o.id ? String(o.id) : '' }
}

export function nextGo(prev, x) {
	const p = goPayload(x)
	return { tab: p.tab, name: p.name, id: p.id, n: ((prev && prev.n) | 0) + 1 }
}

export function focusOf(go, tab) {
	const g = go || {}
	if (!g.n || g.tab !== tab || !(g.name || g.id)) return null
	return { name: g.name || '', id: g.id || '', n: g.n }
}

export function profileFocus(list, name) {
	const l = list || {}
	const want = key(name)
	if (!want) return null
	const groups = [[l.profiles, false], [l.base, true], [l.plugin, true]]
	for (const [rows, base] of groups) {
		const hit = (Array.isArray(rows) ? rows : []).find(r => key(r.name) === want)
		if (hit) return { name: hit.name, base }
	}
	return null
}

export function peopleFocus(users, groups, name) {
	const want = key(name)
	if (!want) return null
	const person = (Array.isArray(users) ? users : []).find(u => key(u.name) === want)
	if (person) return { kind: 'person', name: person.name }
	const group = ((groups && groups.groups) || []).find(g => key(g.name) === want)
	return group ? { kind: 'group', name: group.name } : null
}

export function keyFocus(keys, id) {
	const hit = (Array.isArray(keys) ? keys : []).find(k => String(k.id) === String(id))
	return hit ? String(hit.id) : ''
}
