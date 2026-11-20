'use strict'

// The places of the redesigned service page, as DATA (information architecture approved in the design: diseno/FLUJOS.md section 2).
// Pure: no DOM, no store, no texts (titles are keys of the catalog area `shell`).
//
// A place is { s, t, a }: section, tab ('' = the section has none) and anchor ('' = the top). It is what the address carries:
// /Plugins/WorkshopService?s=health&t=processes&a=svc-proc-jog
//
//   SECTIONS                the nine sections: id, icon, tabs, admin (only who administers opens it), menu (false: not an entry of the
//                           navigation, reached from the header), live (shows data the service publishes at its fast rate while watched)
//   sectionOf(id) / tabsOf(id) / defaultTab(id)
//   placeOf(query)          the place an address means: its own (?s=&t=&a=), an OLD one (?anchor=svc-base, an old section id, an old
//                           section/tab) or, for anything unknown, the home. Never null: every address lands somewhere
//   queryOf(place)          the address of a place (the default tab is written too: a link says where it goes)
//   navEntries(mayAdmin)    what the navigation draws: who administers sees Access and Security, anyone else ONE locked entry
//                           "Administration" (nothing is hidden: the entry exists, says what it holds and opens its cover)
//
// Old links are redirections only (the phone notices send to svc-base and svc-blackbox); no old data format is read.

const section = (id, icon, tabs, extra) => Object.freeze(Object.assign({ id, icon, tabs: Object.freeze(tabs || []), admin: false, menu: true, live: false }, extra || {}))

export const SECTIONS = Object.freeze([
	section('home', 'mdi-view-dashboard-outline', [], { live: true }),
	section('machine', 'mdi-printer-3d-nozzle-outline', ['auto', 'comms']),
	section('health', 'mdi-pulse', ['processes', 'load', 'shutdowns'], { live: true }),
	section('links', 'mdi-lan-connect', ['bridge', 'commands', 'api']),
	section('data', 'mdi-database-outline', ['db', 'backups']),
	section('setup', 'mdi-clipboard-check-outline', ['status', 'files', 'changes', 'package']),
	section('access', 'mdi-shield-key-outline', ['people', 'profiles', 'templates', 'can', 'keys', 'settings'], { admin: true }),
	section('security', 'mdi-shield-search', ['review', 'report', 'activity'], { admin: true }),
	section('session', 'mdi-account-circle-outline', [], { menu: false })
])

export const HOME = 'home'
export const ADMIN_ENTRY = 'admin'      // the one entry a person who does not administer sees instead of Access and Security
export const ADMIN_OP = 'access.profiles.list'   // who may read the profiles administers (the same question the old page asked)

const own = (o, k) => Object.prototype.hasOwnProperty.call(o, k)
const place = (s, t, a) => Object.freeze({ s, t: t || '', a: a || '' })

export function sectionOf(id) {
	return SECTIONS.find(x => x.id === id) || null
}

export function tabsOf(id) {
	const s = sectionOf(id)
	return s ? s.tabs : []
}

export function defaultTab(id) {
	return tabsOf(id)[0] || ''
}

// Where every OLD address lands (FLUJOS 2.2): old section ids, old 'section/tab' pairs and old anchors.
export const OLD = Object.freeze({
	summary: place('home'), state: place('home'),
	people: place('session'), 'people/session': place('session'),
	password: place('access', 'settings', 'svc-dwc-password'), 'people/password': place('access', 'settings', 'svc-dwc-password'),
	'machine/channel': place('machine', 'comms'), 'machine/automation': place('machine', 'auto'),
	processes: place('health', 'processes'), 'processes/list': place('health', 'processes'), 'processes/load': place('health', 'load'),
	'svc-blackbox': place('health', 'shutdowns', 'svc-blackbox'),
	bridge: place('links', 'bridge'), 'svc-bridge': place('links', 'bridge', 'svc-bridge'), connections: place('links', 'bridge'), 'connections/bridge': place('links', 'bridge'),
	'connections/reference': place('links', 'api'),
	commands: place('links', 'commands'), 'data/commands': place('links', 'commands'),
	base: place('data', 'db'), 'svc-base': place('data', 'db', 'svc-base'), 'data/database': place('data', 'db'),
	'svc-package': place('setup', 'status', 'svc-package'), 'svc-startup': place('setup', 'status', 'svc-startup'), 'data/package': place('setup', 'status'),
	users: place('access', 'people'), 'people/users': place('access', 'people'),
	'people/roles': place('access', 'profiles', 'svc-roles'), 'svc-roles': place('access', 'profiles', 'svc-roles'),
	api: place('access', 'keys'), 'connections/keys': place('access', 'keys')
})
// the ids that are ALSO a section of today mean today's section when they come as ?s= ; as ?anchor= or as an old id they mean the old one
const OLD_ONLY_AS_ANCHOR = Object.freeze({ access: place('access', 'profiles'), security: place('security', 'activity') })
// svc-proc-<id>: one anchor per process
const PROCESS_ANCHOR = 'svc-proc-'

export function oldPlace(id) {
	const key = String(id === null || id === undefined ? '' : id)
	if (!key) return null
	if (own(OLD, key)) return OLD[key]
	if (own(OLD_ONLY_AS_ANCHOR, key)) return OLD_ONLY_AS_ANCHOR[key]
	if (key.indexOf(PROCESS_ANCHOR) === 0 && key.length > PROCESS_ANCHOR.length) return place('health', 'processes', key)
	return null
}

function normal(s, t, a) {
	const sec = sectionOf(s)
	if (!sec) return null
	const tabs = sec.tabs
	return place(sec.id, tabs.length ? (tabs.indexOf(t) >= 0 ? t : tabs[0]) : '', typeof a === 'string' ? a : '')
}

export function placeOf(query) {
	const q = query && typeof query === 'object' ? query : {}
	const s = typeof q.s === 'string' ? q.s : ''
	const t = typeof q.t === 'string' ? q.t : ''
	const a = typeof q.a === 'string' ? q.a : ''
	if (s) {
		const here = sectionOf(s)
		// a tab that moved away with its old section ('people/password') is looked up before the section's own tabs
		const moved = own(OLD, s + '/' + t) && (!here || here.tabs.indexOf(t) < 0) ? OLD[s + '/' + t] : null
		if (moved) return place(moved.s, moved.t, a || moved.a)
		if (here) return normal(s, t, a)
		const old = oldPlace(s)
		if (old) return place(old.s, old.t, a || old.a)
	}
	// the old way: ?anchor=svc-base (a DOM id or an old section id)
	const anchor = typeof q.anchor === 'string' ? q.anchor : ''
	if (anchor) {
		const old = oldPlace(anchor)
		if (old) return old
		const sec = sectionOf(anchor)
		if (sec) return normal(sec.id, '', '')
	}
	return place(HOME)
}

export function queryOf(p) {
	const n = normal(p && p.s, p && p.t, p && p.a) || place(HOME)
	const q = { s: n.s }
	if (n.t) q.t = n.t
	if (n.a) q.a = n.a
	return q
}

export function samePlace(x, y) {
	return !!x && !!y && x.s === y.s && x.t === y.t && x.a === y.a
}

export function navEntries(mayAdmin) {
	const open = SECTIONS.filter(x => x.menu && !x.admin).map(x => ({ id: x.id, icon: x.icon, to: x.id, locked: false }))
	const admin = SECTIONS.filter(x => x.menu && x.admin)
	if (mayAdmin) return open.concat(admin.map(x => ({ id: x.id, icon: x.icon, to: x.id, locked: false })))
	return open.concat([{ id: ADMIN_ENTRY, icon: 'mdi-shield-lock-outline', to: admin[0].id, locked: true }])
}

// the entry of the navigation a section is drawn under (Access and Security are the locked Administration entry for who does not administer)
export function entryOf(sectionId, mayAdmin) {
	const s = sectionOf(sectionId)
	if (!s || !s.menu) return ''
	return s.admin && !mayAdmin ? ADMIN_ENTRY : s.id
}
