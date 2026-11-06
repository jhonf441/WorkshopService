'use strict'

// The rules of the "Roles and permissions" matrix (phase 3 of informes/permisos-por-rol/DISENO.md). Pure logic, no Vue and no calls: the
// card (RolesCard.vue) passes what roles.list / roles.effective answered, and tests/roles-matrix.test.js loads this file in node.
//
// A COLUMN is a base role ({ kind: 'base', role }) or a custom role ({ kind: 'custom', def: { base, grant, deny } }). A ROW is a capability
// of roles.list ({ id, category, class, risk, ops, title, delegable, deniable }). The state of a cell:
//
//   allowed    the base role allows every operation of the capability
//   partial    the base role allows some of them
//   blocked    the base role allows none
//   limited    allowed, but only in some modes (operator) or with the camera flag (viewer)
//   granted    the custom role adds it on top of its base role
//   denied     the custom role takes it away (a denial wins over everything but stopping)
//   locked     it cannot be delegated: only an administrator has it
//   stop       it holds a stop operation: stopping is never blocked, so it cannot be denied
//
// Only a cell of a custom column can be changed, and never a `locked` or `stop` one.

export const BASE_ROLES = ['viewer', 'operator', 'technician', 'admin']
export const HARDWARE_PARAMS = 'machine.hardware_params'

// explicit literal keys (plugins.WorkshopService.roles.<key>) so the i18n check can see that each one is used
export const CELL_INFO = {
	allowed: { icon: 'mdi-check', label: 'cell_allowed', why: 'cell_allowed_why' },
	partial: { icon: 'mdi-circle-half-full', label: 'cell_partial', why: 'cell_partial_why' },
	blocked: { icon: 'mdi-minus', label: 'cell_blocked', why: 'cell_blocked_why' },
	limited: { icon: 'mdi-filter-outline', label: 'cell_limited', why: 'cell_limited_why' },
	granted: { icon: 'mdi-plus-circle-outline', label: 'cell_granted', why: 'cell_granted_why' },
	denied: { icon: 'mdi-cancel', label: 'cell_denied', why: 'cell_denied_why' },
	locked: { icon: 'mdi-lock-outline', label: 'cell_locked', why: 'cell_locked_why' },
	stop: { icon: 'mdi-stop-circle-outline', label: 'cell_stop', why: 'cell_stop_why' }
}

export const CLASS_KEYS = { read: 'class_read', write: 'class_write', motion: 'class_motion', stop: 'class_stop', power: 'class_power', admin: 'class_admin' }

export function emptyDef(base) {
	return { base: base || 'operator', grant: [], deny: [] }
}

// roles.effective rows of ONE role -> { <capability id>: { allowed, limited, total } }. A row blocked by the camera flag or by a mode counts as
// `limited` (the role may, under a condition); the other blocked rows only count in the total.
export function tallyByCapability(rows) {
	const out = {}
	;(rows || []).forEach(r => {
		const id = r.capability
		if (!id) return
		const t = out[id] || (out[id] = { allowed: 0, limited: 0, total: 0 })
		t.total++
		if (r.allowed) t.allowed++
		else if (r.reason === 'camera' || r.reason === 'mode' || r.reason === 'mode_unknown') t.limited++
	})
	return out
}

// The state a base role gives a capability. `tallies` = { viewer: tally, operator: tally, ... }.
export function baseState(cap, role, tallies) {
	if (cap.deniable === false) return 'stop'
	if (role === 'admin') return 'allowed'
	if (cap.delegable === false) return 'locked'
	if (cap.id === HARDWARE_PARAMS) return 'blocked'
	const t = ((tallies || {})[role] || {})[cap.id]
	if (!t || !t.total) return 'blocked'
	if (t.allowed === t.total) return 'allowed'
	if (t.allowed + t.limited === t.total && t.limited > 0) return 'limited'
	return t.allowed + t.limited > 0 ? 'partial' : 'blocked'
}

export function entryOf(def, capId) {
	if ((def.deny || []).includes(capId)) return 'deny'
	if ((def.grant || []).includes(capId)) return 'grant'
	return 'inherit'
}

// The state of a cell for a column.
export function cellState(cap, col, tallies) {
	if (col.kind === 'base') return baseState(cap, col.role, tallies)
	const def = col.def
	if (cap.deniable === false) return 'stop'
	if (entryOf(def, cap.id) === 'deny') return 'denied'
	if (cap.delegable === false) return 'locked'
	if (entryOf(def, cap.id) === 'grant') return 'granted'
	return baseState(cap, def.base, tallies)
}

// Can the person change this cell? Only a custom column, never a locked or stop one.
export function editable(cap, col) {
	return col.kind === 'custom' && cap.deniable !== false && cap.delegable !== false
}

// What a click does: inherit -> grant (when the base role does not already allow all of it) -> deny -> inherit. A base role that allows everything
// has nothing to grant, one that allows nothing has nothing to deny.
export function nextEntry(cap, def, tallies) {
	const cur = entryOf(def, cap.id)
	const b = baseState(cap, def.base, tallies)
	const options = ['inherit']
	if (b !== 'allowed' && b !== 'limited') options.push('grant')
	if (b !== 'blocked') options.push('deny')
	if (!options.includes(cur)) options.push(cur)
	const order = ['inherit', 'grant', 'deny'].filter(x => options.includes(x))
	return order[(order.indexOf(cur) + 1) % order.length]
}

// A new definition with the entry of one capability set (the entries that are not capability ids, such as operation names, are kept as they are).
export function withEntry(def, capId, entry) {
	const grant = (def.grant || []).filter(x => x !== capId)
	const deny = (def.deny || []).filter(x => x !== capId)
	if (entry === 'grant') grant.push(capId)
	if (entry === 'deny') deny.push(capId)
	return Object.assign({}, def, { grant, deny })
}

export function toggle(cap, def, tallies) {
	return withEntry(def, cap.id, nextEntry(cap, def, tallies))
}

// Entries of a definition that are not a capability id (operation names, patterns): the matrix cannot show them, the card says how many are kept.
export function foreignEntries(def, caps) {
	const ids = new Set((caps || []).map(c => c.id))
	return (def.grant || []).concat(def.deny || []).filter(x => !ids.has(x))
}

// The preview of a change: what changes in the matrix between two definitions of the same column.
// -> [{ id, title, category, from, to }] in the order of the capabilities
export function diffStates(caps, before, after, tallies) {
	const out = []
	;(caps || []).forEach(cap => {
		const from = cellState(cap, { kind: 'custom', def: before }, tallies)
		const to = cellState(cap, { kind: 'custom', def: after }, tallies)
		if (from !== to) out.push({ id: cap.id, title: cap.title, category: cap.category, from, to })
	})
	return out
}

export function sameList(a, b) {
	const x = (a || []).slice().sort()
	const y = (b || []).slice().sort()
	return x.length === y.length && x.every((v, i) => v === y[i])
}

// Did the draft change anything compared with what is saved? (`saved` is null for a new role.)
export function isDirty(saved, draft) {
	if (!saved) return true
	return saved.base !== draft.base || (saved.description || '') !== (draft.description || '') || !sameList(saved.grant, draft.grant) || !sameList(saved.deny, draft.deny)
}

// Grants of risk 4 (can hurt the hardware or lock the workshop out): the card warns before applying.
export function riskyGrants(caps, def, minRisk) {
	const m = minRisk || 4
	return (caps || []).filter(c => (def.grant || []).includes(c.id) && c.risk >= m)
}

// Groups the capabilities by category, in the order of `categories` ([{ id, title }]); an empty category is left out.
export function groupByCategory(caps, categories) {
	return (categories || []).map(c => ({ id: c.id, title: c.title, caps: (caps || []).filter(x => x.category === c.id) })).filter(g => g.caps.length)
}

// The rows of roles.effective that the "what can this person do" panel shows: only the blocked ones, and/or those whose operation contains the text.
export function filterEffective(rows, { blockedOnly, query } = {}) {
	const q = String(query || '').trim().toLowerCase()
	return (rows || []).filter(r => (!blockedOnly || !r.allowed) && (!q || String(r.op).toLowerCase().includes(q)))
}

// Items of the person / role selector of that panel: { value: 'user:Ana' | 'role:Operador' }
export function subjectArgs(value) {
	const i = String(value || '').indexOf(':')
	if (i < 0) return null
	const kind = value.slice(0, i)
	const name = value.slice(i + 1)
	if (!name || (kind !== 'user' && kind !== 'role')) return null
	return { [kind]: name }
}
