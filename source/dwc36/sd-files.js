'use strict'

// Files per plugin (SdFilesDialog.vue): the logic of the viewer, with no Vue and no imports, so a test can feed it every case.
// The service (dsf/sd_files.py, operation startup.files) decides the status of each file; this only filters, counts and tells the page what to draw.
//
// A plugin:  { plugin, version, counts: { expected, present, ok, edited, missing, not_yet, attention }, files: [file] }
// A file:    { path, kind, status, state, used_by: [], safety, created_before?, breaks_if_missing? }

export const STATUSES = ['ok', 'edited', 'missing', 'not_yet', 'attention']
export const KINDS = ['workshop-owned', 'template', 'native-managed', 'generated', 'expected-external']

export const STATUS_COLOR = { ok: 'success', edited: 'warning', missing: 'error', not_yet: 'grey', attention: 'warning' }
export const STATUS_ICON = { ok: 'mdi-check', edited: 'mdi-pencil-outline', missing: 'mdi-file-alert-outline', not_yet: 'mdi-timer-sand', attention: 'mdi-alert-outline' }

export function emptyFilter() {
	return { status: 'all', q: '' }
}

// A file matches the search when the text is in its path, its class or the name of who uses it (case and surrounding spaces ignored).
export function matches(file, filter) {
	if (filter.status && filter.status !== 'all' && file.status !== filter.status) return false
	const q = String(filter.q || '').trim().toLowerCase()
	if (!q) return true
	const hay = [file.path, file.kind].concat(file.used_by || []).join('\n').toLowerCase()
	return hay.indexOf(q) !== -1
}

// The plugins with only the files that match; a plugin left with none is not drawn. Counts stay the plugin's own (they do not follow the filter).
export function visible(plugins, filter) {
	const out = []
	for (const p of plugins || []) {
		const files = (p.files || []).filter(f => matches(f, filter))
		if (files.length) out.push(Object.assign({}, p, { files }))
	}
	return out
}

// The four numbers of the header, from the files themselves (the server sends them too; this keeps the header right when only one plugin is read).
export function totals(plugins) {
	const t = { expected: 0, present: 0, missing: 0, edited: 0 }
	for (const p of plugins || []) {
		for (const f of p.files || []) {
			t.expected++
			if (f.status === 'missing') t.missing++
			else if (f.status !== 'not_yet') t.present++
			if (f.status === 'edited') t.edited++
		}
	}
	return t
}

// How many files of each status in a list (the filter chips show them).
export function byStatus(plugins) {
	const n = { all: 0 }
	for (const s of STATUSES) n[s] = 0
	for (const p of plugins || []) {
		for (const f of p.files || []) {
			n.all++
			if (n[f.status] !== undefined) n[f.status]++
		}
	}
	return n
}

// The plugins that open by themselves: the ones with something to look at (a missing or edited file, or one that needs a look).
export function needsLook(p) {
	const c = p.counts || {}
	return (c.missing || 0) + (c.edited || 0) + (c.attention || 0) > 0
}

// The diff is the one of the integrity module (startup.integrity.restore.preview): it exists only for a workshop-owned file that was edited.
export function canDiff(file) {
	return file.kind === 'workshop-owned' && file.status === 'edited'
}

// Something the start-up wizard can offer: any missing file (a template it creates; the rest it tells the person about). Used for the link.
export function hasMissing(plugins) {
	return (plugins || []).some(p => (p.files || []).some(f => f.status === 'missing'))
}

// Files the wizard will NOT recreate by itself (a template that was created once and deleted): the page says so on the row.
export function wontRecreate(file) {
	return file.kind === 'template' && file.status === 'missing' && !!file.created_before
}

// The key of the status text, and of the class text, in the catalog (sd_files.st_<status>, sd_files.kind_<kind>); an unknown one falls to 'attention' / null.
export function statusKey(file) {
	return 'st_' + (STATUSES.indexOf(file.status) === -1 ? 'attention' : file.status)
}

export function kindKey(file) {
	return KINDS.indexOf(file.kind) === -1 ? null : 'kind_' + file.kind
}
