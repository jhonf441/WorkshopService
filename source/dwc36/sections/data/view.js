'use strict'

// Data and backups, as a pure view of what db.status says: the tables, the figures, the notices that explain a backup problem, the
// list of copies with what is going to happen to each, the draft of the settings and the places a backup may go. No Vue, no texts, no clock
// (the screens pass `now` in seconds when a date is compared).

const HIDDEN_TABLES = ['presets', 'sqlite_sequence']
export const LIST_SHOWN = 20          // the service lists the most recent twenty

export function tablesOf(status) {
	return ((status && status.tables) || []).filter(x => x && HIDDEN_TABLES.indexOf(x.name) < 0)
		.map(x => ({ name: x.name, rows: Number(x.rows) || 0, since: x.since || null, until: x.until || null }))
}

export function totalRows(tables) {
	return tables.reduce((n, x) => n + x.rows, 0)
}

// the figures of the database card; free space is in GB with one decimal, null when the service does not say
export function figuresOf(status) {
	const s = status || {}
	const free = typeof s.free_mb === 'number' && s.free_mb > 0 ? Math.round(s.free_mb / 102.4) / 10 : null
	return { mb: typeof s.mb === 'number' ? s.mb : null, rows: totalRows(tablesOf(s)), modified: s.modified || null, freeGb: free, ok: s.check === 'ok' }
}

// what explains a backup that is not as it should be, worst first: [{ id, level }]
export function notesOf(backup) {
	const r = backup || null
	if (!r) return []
	const out = []
	if (r.failures && r.failures.length) out.push({ id: 'failing', level: 'error' })
	if (r.late) out.push({ id: 'late', level: 'warn' })
	if (r.active === false) out.push({ id: 'off', level: 'info' })
	if (r.folder_disconnected) out.push({ id: 'folder_gone', level: 'warn' })
	if (r.mirror_disconnected) out.push({ id: 'mirror_gone', level: 'warn' })
	if (r.same_card && !r.mirror) out.push({ id: 'same_card', level: 'warn' })
	return out
}

// the copies, newest first as the service lists them: what is going to happen to each (kept for ever, goes on a day, normal)
export function copyRows(backup) {
	const r = backup || {}
	const kept = r.kept || []
	const goes = r.per_delete || []
	return (r.list || []).slice(0, LIST_SHOWN).map(c => {
		const g = goes.find(p => p.file === c.file)
		const isKept = kept.indexOf(c.file) >= 0
		return { file: c.file, mb: c.mb, date: c.date || null, kept: isKept, until: g ? g.until : null, state: isKept ? 'kept' : g ? 'goes' : 'normal' }
	})
}

// the settings as the form starts: nothing is sent until Save
export function draftOf(backup) {
	const r = backup || {}
	return { auto: r.active !== false, daily: String(r.daily === undefined ? 7 : r.daily), weekly: String(r.weekly === undefined ? 4 : r.weekly), mirror: r.mirror_mode || 'auto', summarize: r.summarize_consumption !== false }
}

// "7" -> 7 ; 0..max whole numbers only, else null
export function parseCount(text, max) {
	const s = String(text === undefined || text === null ? '' : text).trim()
	if (!/^\d{1,3}$/.test(s)) return null
	const n = Number(s)
	return n <= (max === undefined ? 365 : max) ? n : null
}

export function changed(draft, base) {
	const d = draftOf(base)
	return ['auto', 'daily', 'weekly', 'mirror', 'summarize'].some(k => String(draft[k]) !== String(d[k]))
}

// the choices of "a copy somewhere else": automatic, none, and the places the service lists that are not where the backups already are
export function mirrorChoices(places, folder, current) {
	const out = [{ value: 'auto', name: '', folder: '' }, { value: 'no', name: '', folder: '' }]
	;(places || []).forEach(p => { if (p.folder !== folder) out.push({ value: p.folder, name: p.name || '', folder: p.folder }) })
	if (current && !out.some(x => x.value === current)) out.push({ value: current, name: '', folder: current })
	return out
}

// the places a person may move the backups to (never the one they are in)
export function moveChoices(places, folder) {
	return (places || []).filter(p => p && p.folder !== folder)
}

// where a file of the SD card is for DWC ("0:/..."), or null for a place DWC does not serve (a USB drive)
export function sdPath(folder) {
	return /^\/opt\/dsf\/sd\//.test(folder || '') ? '0:/' + folder.slice('/opt/dsf/sd/'.length) : null
}
