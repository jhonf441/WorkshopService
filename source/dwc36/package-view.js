'use strict'

// The Configuration package (ConfigPackagePanel.vue): the logic of the view with no Vue (it only reads the list of run outcomes of package-wizard.js), so a test can feed it every case.
// The service decides the state of each file (startup.files, dsf/sd_files.py); this only groups, counts, filters, searches and says what to do next.
//
// A plugin:  { plugin, version, counts: { expected, present, ok, edited, missing, not_yet, attention }, files: [file] }
// A file:    { path, kind, status, state, used_by: [], safety, created_before?, breaks_if_missing? }
//
//   fileState(f)            'identical' | 'present' | 'missing' | 'edited' | 'not_yet' | 'attention'  (the word of the row)
//   needsAttention(f)       a missing, a hand edited or an odd file
//   splitPath(path)         { name, dir } : the file name and the folder it lives in
//   groupFiles(plugins, f)  the plugins with only the files that match { q, only }, each row decorated for the view
//   fileCounts(plugins)     { plugins, files, present, missing, edited, attention, not_yet, identical }
//   canRestore(f)           the row offers "see changes / restore": a workshop owned file that is edited or missing (the service decides again)
//   refusalKey(code)        the catalog key of a refusal of the restore preview, or '' when the page has no sentence for it
//   runSummary(summary, label)  'created: 2, unchanged: 1' from the counts of a run (only the outcomes the page knows)
//   summarize(parts)        ONE total of the whole package and the one next action
//   emptyFilter()           { q: '', only: false }

import { RUN_ACTIONS } from './package-wizard.js'

export const FILE_STATES = ['identical', 'present', 'missing', 'edited', 'not_yet', 'attention']
export const STATE_ICON = { identical: 'mdi-check-all', present: 'mdi-check', missing: 'mdi-file-alert-outline', edited: 'mdi-pencil-outline', not_yet: 'mdi-timer-sand', attention: 'mdi-alert-outline' }
export const STATE_COLOR = { identical: 'success', present: 'success', missing: 'error', edited: 'warning', not_yet: 'grey', attention: 'warning' }
const ATTENTION = ['missing', 'edited', 'attention']

export function emptyFilter() {
	return { q: '', only: false }
}

export function fileState(f) {
	const s = f && f.status
	if (s === 'ok') return f.kind === 'workshop-owned' ? 'identical' : 'present'
	if (s === 'edited' || s === 'missing' || s === 'not_yet') return s
	return 'attention'
}

export function needsAttention(f) {
	return ATTENTION.indexOf(fileState(f)) !== -1
}

export function splitPath(path) {
	const p = String(path || '')
	const i = p.lastIndexOf('/')
	return { name: i === -1 ? p : p.slice(i + 1), dir: i === -1 ? '' : p.slice(0, i + 1) }
}

// A file matches the search when the text is in its path, its class or the name of who uses it (case and surrounding spaces ignored).
export function fileMatches(f, filter) {
	if (filter && filter.only && !needsAttention(f)) return false
	const q = String((filter && filter.q) || '').trim().toLowerCase()
	if (!q) return true
	return [f.path, f.kind].concat(f.used_by || []).join('\n').toLowerCase().indexOf(q) !== -1
}

export function decorate(f) {
	const s = splitPath(f.path)
	return Object.assign({}, f, { name: s.name, dir: s.dir, fileState: fileState(f), attention: needsAttention(f) })
}

// The plugins with only the files that match; a plugin left with none is not drawn. The counts stay the plugin's own (they do not follow the filter).
export function groupFiles(plugins, filter) {
	const out = []
	for (const p of plugins || []) {
		const files = (p.files || []).filter(f => fileMatches(f, filter)).map(decorate)
		if (files.length) out.push(Object.assign({}, p, { files, attention: (p.files || []).filter(needsAttention).length }))
	}
	return out
}

export function fileCounts(plugins) {
	const c = { plugins: 0, files: 0, present: 0, missing: 0, edited: 0, attention: 0, not_yet: 0, identical: 0 }
	for (const p of plugins || []) {
		c.plugins++
		for (const f of p.files || []) {
			c.files++
			const s = fileState(f)
			if (s === 'identical') c.identical++
			if (s === 'missing') c.missing++
			else if (s === 'edited') c.edited++
			else if (s === 'attention') c.attention++
			else if (s === 'not_yet') c.not_yet++
			if (s !== 'missing' && s !== 'not_yet') c.present++
		}
	}
	return c
}

// Something to restore from the factory copy: only a file of the workshop that is edited or gone. Safety files and the rest are refused by the service
// with their reason, which the preview shows.
export function canRestore(f) {
	return !!f && f.kind === 'workshop-owned' && (f.status === 'edited' || f.status === 'missing')
}

const REFUSALS = ['already_ok', 'factory_missing', 'factory_mismatch', 'wrong_kind', 'not_in_manifest', 'not_a_file', 'safety', 'board_busy']
export function refusalKey(code) {
	return REFUSALS.indexOf(code) === -1 ? '' : 'refusal_' + code
}

// ---- the one total ------------------------------------------------------------------------------------------------------------------------
//   steps = { rows, pending, unchecked, needsLogin, settled }   plugins with steps left (readiness.list)
//   files = { loaded, needsLogin, counts, settled }             what fileCounts() said about startup.files
//   plan  = { loaded, items, needsLogin, settled }              changes waiting in startup.plan
// settled: the block finished its first read (it answered, failed, or the role does not read it); a total is never "ready" before all are settled.
// kind:  'login' | 'pending' (steps or changes to apply) | 'attention' (only files to look at) | 'loading' | 'unchecked' | 'ready'
// next:  the one action: { id: 'sign_in' } | { id: 'steps' } | { id: 'plan' } | { id: 'files' } | { id: 'unchecked' } | { id: 'none' }
export function summarize(parts) {
	const s = Object.assign({ rows: 0, pending: 0, unchecked: 0, needsLogin: false, settled: true }, parts && parts.steps)
	const f = Object.assign({ loaded: false, needsLogin: false, counts: null, settled: true }, parts && parts.files)
	const p = Object.assign({ loaded: false, items: 0, needsLogin: false, settled: true }, parts && parts.plan)
	const stepsPending = s.needsLogin ? 0 : s.pending
	const planPending = p.needsLogin ? 0 : p.items
	const c = (!f.needsLogin && f.counts) || null
	const filesLook = c ? c.missing + c.attention : 0
	const filesEdited = c ? c.edited : 0
	const unchecked = s.needsLogin ? 0 : s.unchecked
	const n = stepsPending + planPending
	const blind = s.needsLogin || f.needsLogin || p.needsLogin
	let kind = 'ready'
	if (blind && n === 0 && filesLook === 0) kind = 'login'
	else if (n > 0) kind = 'pending'
	else if (filesLook > 0) kind = 'attention'
	else if (!(s.settled && f.settled && p.settled)) kind = 'loading'
	else if (unchecked > 0) kind = 'unchecked'
	let next = { id: 'none' }
	if (kind === 'login') next = { id: 'sign_in' }
	else if (stepsPending > 0) next = { id: 'steps' }
	else if (planPending > 0) next = { id: 'plan' }
	else if (filesLook > 0) next = { id: 'files' }
	else if (unchecked > 0) next = { id: 'unchecked' }
	return { kind, n, stepsPending, planPending, filesLook, filesEdited, unchecked, next }
}

export const KIND_COLOR = { login: undefined, loading: undefined, pending: 'warning', attention: 'warning', unchecked: undefined, ready: 'success' }
export const KIND_ICON = { login: 'mdi-account-lock-outline', loading: 'mdi-timer-sand', pending: 'mdi-alert-circle-outline', attention: 'mdi-alert-circle-outline', unchecked: 'mdi-help-circle-outline', ready: 'mdi-check-circle-outline' }

// The counts per outcome of a run (install_runs.summary) as one short line. label(action) is the sentence of that outcome; an outcome the page has no
// sentence for, or with a zero, is left out.
// The three numbers of a run: what was applied, what was left alone because the file already existed or has content of the person, and what
// needed nothing. `skipped*` and `unchanged` are not applied; everything else counts as applied.
export function runCounts(summary) {
	const s = summary && typeof summary === 'object' ? summary : {}
	const c = { applied: 0, skipped: 0, unchanged: 0 }
	Object.keys(s).filter(k => RUN_ACTIONS.indexOf(k) !== -1 && Number(s[k]) > 0).forEach(k => {
		if (k.indexOf('skipped') === 0) c.skipped += Number(s[k])
		else if (k === 'unchanged') c.unchanged += Number(s[k])
		else c.applied += Number(s[k])
	})
	return c
}

// the actions of a run split in the two lists the page draws: the ones that did something and the skipped ones (grouped by reason)
export function splitActions(actions) {
	const list = Array.isArray(actions) ? actions : []
	const skipped = list.filter(a => String(a.action || '').replace(/^would_/, '').indexOf('skipped') === 0)
	const done = list.filter(a => skipped.indexOf(a) < 0)
	const reasons = {}
	skipped.forEach(a => { const k = String(a.action || '').replace(/^would_/, ''); reasons[k] = (reasons[k] || 0) + 1 })
	return { done, skipped, reasons: Object.keys(reasons).map(k => ({ action: k, n: reasons[k] })) }
}

export function runSummary(summary, label) {
	const s = summary && typeof summary === 'object' ? summary : {}
	return Object.keys(s).filter(k => RUN_ACTIONS.indexOf(k) !== -1 && Number(s[k]) > 0).map(k => label(k) + ': ' + Number(s[k])).join(', ')
}
