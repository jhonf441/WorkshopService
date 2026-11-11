'use strict'

// Start-up wizard (StartupWizard.vue): what the person ticked and what may be sent. Pure functions, no Vue and no imports, so a test can feed
// them every case. The service (dsf/startup_plan.py) decides again on its own: this only keeps the page honest and tells the person why a button is closed.
//
// An item of the plan: { id, group: 'hooks'|'modes'|'templates'|'cleanup', kind: 'create'|'edit'|'move'|'rewrite'|'remove', path, new_path, action, reason, selectable,
//   blocked, safety: null|'startup'|'daemon'|'homing'|'guard'|'pause'|'cancel'|'system', expected_sha, diff, warnings }

export const GROUPS = ['hooks', 'modes', 'templates', 'cleanup']

// The files of this group move together: ticked all or none (a half-done move leaves daemon.g pointing at a file that is not there).
export const TOGETHER = 'modes'

export function byGroup(items) {
	return GROUPS.map(id => ({ id, items: (items || []).filter(i => i.group === id) })).filter(g => g.items.length)
}

// Nothing is ticked at the start: every change is accepted on purpose, one by one.
// `seen` = the items whose diff the person opened: a safety file can only be confirmed after its diff was on screen (review: nobody should
// confirm a change to daemon.g or config.g without having had the diff in front).
export function emptySelection() {
	return { ticked: {}, safe: {}, machineOff: false, seen: {} }
}

function groupIds(items, group) {
	return items.filter(i => i.group === group && i.selectable).map(i => i.id)
}

// Ticks or unticks one item (and the rest of its group when the group goes together). Returns a NEW selection.
export function setTicked(sel, items, id, value) {
	const it = items.find(i => i.id === id)
	if (!it || !it.selectable) return sel
	const ids = it.group === TOGETHER ? groupIds(items, TOGETHER) : [id]
	const ticked = Object.assign({}, sel.ticked)
	const safe = Object.assign({}, sel.safe)
	for (const x of ids) {
		if (value) ticked[x] = true
		else {
			delete ticked[x]
			delete safe[x]
		}
	}
	return { ticked, safe, machineOff: sel.machineOff, seen: sel.seen || {} }
}

// The person opened the diff of this item.
export function setSeen(sel, id) {
	return { ticked: sel.ticked, safe: sel.safe, machineOff: sel.machineOff, seen: Object.assign({}, sel.seen, { [id]: true }) }
}

// The confirmation of a safety file is only taken once its diff was opened (a confirmation without it is ignored).
export function setSafe(sel, id, value) {
	const safe = Object.assign({}, sel.safe)
	if (value && (sel.seen || {})[id]) safe[id] = true
	else delete safe[id]
	return { ticked: sel.ticked, safe, machineOff: sel.machineOff, seen: sel.seen || {} }
}

export function setMachineOff(sel, value) {
	return { ticked: sel.ticked, safe: sel.safe, machineOff: !!value, seen: sel.seen || {} }
}

// After ANY apply (done, partly done or refused) the statements "machine off" and "I confirm this safety file" are forgotten: they were about
// the board and the files of that moment, and the next press has to be a new decision. The ticks and the opened diffs stay.
export function afterApply(sel) {
	return { ticked: sel.ticked, safe: {}, machineOff: false, seen: sel.seen || {} }
}

export function chosen(items, sel) {
	return (items || []).filter(i => i.selectable && sel.ticked[i.id])
}

export function chosenSafety(items, sel) {
	return chosen(items, sel).filter(i => i.safety)
}

// Why the apply button is closed, or '' when it may be pressed: 'none' | 'busy' | 'diff' | 'safety' | 'machine_off'. (The role is the lock of the button, not here.)
export function applyBlock(items, sel, blockers) {
	const list = chosen(items, sel)
	if (!list.length) return 'none'
	if (blockers && blockers.length) return 'busy'
	const risky = list.filter(i => i.safety)
	if (risky.some(i => !(sel.seen || {})[i.id])) return 'diff'
	if (risky.some(i => !sel.safe[i.id])) return 'safety'
	if (risky.length && !sel.machineOff) return 'machine_off'
	return ''
}

// The body of startup.apply: only what was ticked, each with the sha of the file the person looked at.
export function buildPayload(items, sel) {
	return {
		apply: true,
		machine_off: !!sel.machineOff,
		items: chosen(items, sel).map(i => ({ id: i.id, expected_sha: i.expected_sha, confirm_safety: i.safety ? !!sel.safe[i.id] : false }))
	}
}

// A unified diff as lines with a class for the colour. Never HTML: the text is shown as text.
export function diffLines(diff) {
	const out = []
	for (const raw of String(diff || '').split('\n')) {
		if (!raw && !out.length) continue
		let cls = 'ctx'
		if (raw.startsWith('+++') || raw.startsWith('---')) cls = 'file'
		else if (raw.startsWith('@@')) cls = 'hunk'
		else if (raw.startsWith('+')) cls = 'add'
		else if (raw.startsWith('-')) cls = 'del'
		out.push({ cls, text: raw })
	}
	return out
}

export function diffStats(diff) {
	let add = 0
	let del = 0
	for (const l of diffLines(diff)) {
		if (l.cls === 'add') add++
		else if (l.cls === 'del') del++
	}
	return { add, del }
}

// The result of startup.apply as rows: one per item sent, in the order of the plan, with ok / failed.
export function resultRows(items, result) {
	const names = {}
	;(items || []).forEach(i => { names[i.id] = i })
	const rows = []
	for (const a of (result && result.applied) || []) rows.push({ id: a.id, ok: true, path: a.path, code: a.result, backup: a.backup_path || '' })
	for (const f of (result && result.failed) || []) rows.push({ id: f.id, ok: false, path: names[f.id] ? names[f.id].path : f.id, code: f.code, reason: f.reason })
	return rows
}

// A failure code the page has a text for (startup_wizard.err_<code>); anything else is 'other'.
const ERR = { changed_since_preview: 'changed_since_preview', stale: 'changed_since_preview', not_in_plan: 'not_in_plan', not_applicable: 'not_applicable',
	board_busy: 'board_busy', busy: 'board_busy', group_incomplete: 'group_incomplete', modes_failed: 'modes_failed', write_error: 'write_error', oserror: 'write_error',
	mergeerror: 'write_error', moveerror: 'write_error', valueerror: 'write_error' }
export function errCode(code) {
	return ERR[code] || 'other'
}

// "Marcar todos": every item that can be applied (not blocked) has its diff opened (so it counts as seen, like opening it by hand) and is ticked.
// It NEVER ticks the confirmation of a safety file or "machine off" for the person, and never ticks a blocked item. What was confirmed before stays as it was.
export function selectAll(sel, items) {
	let out = { ticked: Object.assign({}, sel.ticked), safe: Object.assign({}, sel.safe), machineOff: sel.machineOff, seen: Object.assign({}, sel.seen) }
	for (const i of items || []) {
		if (!i.selectable) continue
		out = setTicked(setSeen(out, i.id), items, i.id, true)
	}
	return out
}

// The ids whose diff the page opens when "Marcar todos" is pressed.
export function openableIds(items) {
	return (items || []).filter(i => i.selectable).map(i => i.id)
}

// "Quitar todas las marcas": no tick, no safety confirmation and no "machine off" is left; the diffs already seen stay seen.
export function clearAll(sel) {
	return { ticked: {}, safe: {}, machineOff: false, seen: Object.assign({}, sel.seen) }
}

// Why the box of an item cannot be used, as a key of the page: 'blocked' (the plan blocks it) or '' (it can be ticked).
export function lockWhy(item) {
	return item && item.selectable ? '' : 'blocked'
}

// The confirmation of a safety file waits for the diff: true while this item still needs it opened (the page then offers a button that opens it).
export function needsDiffOpen(sel, item) {
	return !!item && !!item.safety && !!sel.ticked[item.id] && !(sel.seen || {})[item.id]
}

// What the toolbar can do: how many items "Marcar todos" would tick and how many are ticked now.
export function toolbarState(items, sel) {
	const open = openableIds(items)
	return { canAll: open.some(id => !sel.ticked[id]), canClear: Object.keys(sel.ticked).length > 0 || !!sel.machineOff }
}
