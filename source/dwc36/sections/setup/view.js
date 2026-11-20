'use strict'

// Setup, as a pure view: the plugins that have a start-up card (in the order a new person goes through them), their state word, the one
// verdict of the whole setup and the files of the plan grouped for the screen. The logic of the files, the plan and the package lives in the
// pure modules that survive from the old page (package-view.js, package-wizard.js, startup-groups.js, sd-viewer.js): nothing is copied here.

import { IDS } from '../../workshop-ids.js'
import { summarize } from '../../package-view.js'

// key = the table of workshop-ids.js, also the end of the text key of its name (startup_master.name_<key> and setup.help_<key>_*)
export const PLUGINS = Object.freeze([
	{ key: 'bar', id: 'WorkshopControlBar', icon: 'mdi-dock-left' },
	{ key: 'lights', id: 'WorkshopLights', icon: 'mdi-led-strip-variant', path: '/Plugins/Lights' },
	{ key: 'consumption', id: 'WorkshopPower', icon: 'mdi-flash-outline', path: '/Plugins/Power' },
	{ key: 'motors', id: 'WorkshopMotors', icon: 'mdi-engine-outline', path: '/Plugins/Motors' },
	{ key: 'jog', id: 'WorkshopJog', icon: 'mdi-gamepad-variant-outline' },
	{ key: 'camera', id: 'WorkshopCamera', icon: 'mdi-video-outline', path: '/Plugins/Timelapses' },
	{ key: 'vision', id: 'WorkshopVision', icon: 'mdi-eye-outline', path: '/Plugins/Vision' },
	{ key: 'workbench', id: 'WorkshopWorkbench', icon: 'mdi-table-furniture', path: '/Plugins/Workbench' },
	{ key: 'printing', id: 'WorkshopPrinting', icon: 'mdi-printer-3d-nozzle-outline', path: '/Plugins/Printing' },
	{ key: 'rs485', id: 'WorkshopRS485', icon: 'mdi-serial-port', path: '/Plugins/RS485' },
	{ key: 'activity', id: 'WorkshopActivity', icon: 'mdi-history', path: '/Plugins/Activity' },
	{ key: 'health', id: 'WorkshopPiHealth', icon: 'mdi-heart-pulse', path: '/Plugins/PiHealth' }
])

// the rows: [the first administrator when nobody was created], then each installed plugin with what it reported
//   reported: readiness.list's `plugins` ({ id: { pending, total } }); on(key): is the plugin installed and enabled; usersOff: no people yet
export function rowsOf(reported, on, usersOff) {
	const rep = reported || {}
	const rows = usersOff ? [{ key: 'users', id: 'users', icon: 'mdi-account-key-outline', entry: { pending: 1, total: 1 } }] : []
	PLUGINS.filter(p => on(p.key)).forEach(p => {
		const ids = IDS[p.key] || [p.id]
		rows.push(Object.assign({}, p, { entry: ids.map(i => rep[i]).find(Boolean) || null }))
	})
	return rows
}

// 'login' (nobody may know) | 'unchecked' (never reported) | 'pending' (steps left) | 'ready'
export function wordOf(row, needsLogin) {
	if (row.key === 'users') return 'pending'
	if (needsLogin) return 'login'
	if (!row.entry) return 'unchecked'
	return row.entry.pending > 0 ? 'pending' : 'ready'
}

export const WORD_LEVEL = Object.freeze({ ready: 'ok', pending: 'warn', unchecked: 'rest', login: 'rest' })

export function stepsOf(rows, needsLogin) {
	const withData = rows.filter(r => r.entry)
	return { rows: rows.length, pending: withData.filter(r => r.entry.pending > 0).length, unchecked: rows.length - withData.length, needsLogin: !!needsLogin }
}

// how many plugins are listos of the total (the user row is not a plugin)
export function readyCount(rows, needsLogin) {
	const plugins = rows.filter(r => r.key !== 'users')
	return { ready: needsLogin ? 0 : plugins.filter(r => r.entry && !(r.entry.pending > 0)).length, total: plugins.length }
}

// the ONE total of the whole setup, with the level it is drawn in and the next action
export function verdictOf(parts) {
	const o = summarize(parts)
	const level = o.kind === 'ready' ? 'ok' : 'warn'
	return Object.assign({ level }, o)
}

// the text keys of one verdict (area configPackage): the headline and the parts it is made of, only the ones that are not zero
export function verdictKeys(o) {
	const head = { login: 'state_login', loading: 'state_loading', pending: 'state_pending', attention: 'state_attention', unchecked: 'state_unchecked', ready: 'state_ready' }[o.kind]
	const n = o.kind === 'pending' ? o.n : o.kind === 'attention' ? o.filesLook : o.kind === 'unchecked' ? o.unchecked : 0
	const parts = []
	if (o.kind !== 'login' && o.kind !== 'ready') {
		if (o.stepsPending) parts.push({ key: 'part_steps', n: o.stepsPending })
		if (o.planPending) parts.push({ key: 'part_plan', n: o.planPending })
		if (o.filesLook) parts.push({ key: 'part_files', n: o.filesLook })
		if (o.unchecked && o.kind !== 'unchecked') parts.push({ key: 'part_unchecked', n: o.unchecked })
	}
	return { head, n, parts }
}

// the tab a next action leads to ('' = stay here, the rows are below)
export function tabOfNext(next) {
	return next && next.id === 'plan' ? 'changes' : next && next.id === 'files' ? 'files' : ''
}

// the package of another machine, as a preview: what each item would do; `replace` lists the paths the person ticked
export function packageTodo(items, replace) {
	return (items || []).filter(i => i.action === 'create' || i.action === 'reference' || (i.action === 'conflict' && (replace || []).indexOf(i.path) >= 0)).length
}

// the words the catalogs have a sentence for (anything else is shown as the service wrote it)
export const WHY = Object.freeze(['file_absent', 'stale_staged_copy'])
export const BLOCKED = Object.freeze(['modes_not_ready', 'target_missing', 'modes_not_migrated'])
export const TRIGGERS = Object.freeze(['wizard', 'plugin-install', 'plugin-update', 'hook-install', 'integrity-restore', 'migration'])

export const PACKAGE_CATEGORIES = Object.freeze(['config', 'zones', 'macros', 'system'])
export const PACKAGE_SOFT_KB = 700
export const PACKAGE_HARD_KB = 1024

// a chosen file: 'ok' | 'big' (over 700 KB: the service may refuse) | 'huge' (over 1 MB: refused before it is read) | 'empty'
export function packageSize(bytes) {
	const n = Number(bytes) || 0
	if (n === 0) return 'empty'
	if (n > PACKAGE_HARD_KB * 1024) return 'huge'
	return n > PACKAGE_SOFT_KB * 1024 ? 'big' : 'ok'
}

export function toBase64(buffer) {
	const bytes = new Uint8Array(buffer)
	let s = ''
	for (let i = 0; i < bytes.length; i += 0x8000) s += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000))
	return btoa(s)
}
