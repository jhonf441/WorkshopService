'use strict'

// The file reader of "Archivos por plugin" (SdFilesDialog.vue): the logic with no Vue and no imports, so a test can feed it every case.
// The service (dsf/sd_view.py, operation startup.file.view) answers with keys and numbers; this turns them into the sentences of the person.
//
// A view:  { path, present, status, state, lines, size, content, truncated, binary, masked, applied: {key, params?},
//            summary: [{key, params?}], factory: { available, reason, changed: [[from, to]], removed: [{after, lines}] },
//            diff_lines?: [{n, text, flag: 'same' | 'changed' | 'added'}] }
// t(key, params) = the translator of the dialog's own texts (sd_files.*).

import { errorKind } from './friendly-error.js'

export const CONTEXT = 2

// "12", "12 a 15" ... joined with commas. Ranges are [from, to] in lines of the file on the card.
export function rangesText(ranges, t) {
	return (ranges || []).map(r => (r[0] === r[1] ? t('range_one', { n: r[0] }) : t('range_many', { from: r[0], to: r[1] }))).join(', ')
}

function params(item, t) {
	const p = Object.assign({}, item.params || {})
	if (Array.isArray(p.ranges)) p.ranges = rangesText(p.ranges, t)
	return p
}

// One sentence for one entry of the summary (view_sum_<key>); an unknown key says something plain instead of a code.
export function sentence(item, t) {
	const p = params(item, t)
	if (item.key === 'edited_lines') {
		const lost = p.removed > 0 ? t('view_sum_edited_removed', { removed: p.removed }) : ''
		return p.ranges ? [t('view_sum_edited_lines', p), lost].filter(Boolean).join(' ') : lost
	}
	return t('view_sum_' + item.key, p)
}

export const APPLIED_KEYS = ['applied_pending', 'applied_by', 'applied_plugin', 'applied_skipped', 'applied_never']

// "Was it applied?" in words: Aplicado el <fecha> por <persona>, Instalado por el plugin, Pendiente..., Omitido por ti, Nunca se aplico.
export function appliedText(applied, t) {
	const a = applied && APPLIED_KEYS.indexOf(applied.key) !== -1 ? applied : { key: 'applied_never' }
	const p = Object.assign({ date: '', who: '' }, a.params || {})
	if (a.key === 'applied_by' && !p.who) return t('view_sum_applied_by_anon', p)
	return t('view_sum_' + a.key, p)
}

// The sentence at the top of the reader: what is the file now (the first entry of the summary that is not the "applied" one).
export function headline(view, t) {
	const first = ((view && view.summary) || []).find(s => APPLIED_KEYS.indexOf(s.key) === -1)
	return first ? sentence(first, t) : t('view_sum_unreadable')
}

// The other things worth saying under the headline (masked, cut, no factory copy...), without the applied one.
export function notes(view, t) {
	return ((view && view.summary) || []).filter((s, i) => i > 0 && APPLIED_KEYS.indexOf(s.key) === -1).map(s => sentence(s, t))
}

// Tone of the header: success, warning or error colour name of Vuetify.
export function tone(view) {
	if (!view || !view.present) return view && view.state === 'absent' ? 'grey' : 'error'
	if (view.status === 'edited' || view.status === 'attention') return 'warning'
	return 'success'
}

export function hasComparison(view) {
	return !!(view && view.factory && view.factory.available)
}

export function changedCount(view) {
	if (!hasComparison(view)) return 0
	return (view.diff_lines || []).filter(l => l.flag !== 'same').length + (view.factory.removed || []).reduce((n, r) => n + r.lines.length, 0)
}

// Every row to draw: the lines of the card (with their flag) and, in place, the lines of the factory that the file lost (flag 'factory', no number).
export function rows(view) {
	if (!view || view.content === null || view.content === undefined) return []
	const base = view.diff_lines || String(view.content).split('\n').map((text, i) => ({ n: i + 1, text, flag: 'same' }))
	const gone = (view.factory && view.factory.removed) || []
	const out = []
	const put = after => gone.filter(r => r.after === after).forEach(r => r.lines.forEach(text => out.push({ n: null, text, flag: 'factory' })))
	put(0)
	for (const l of base) {
		out.push({ n: l.n, text: l.text, flag: l.flag })
		put(l.n)
	}
	return out
}

// "Solo lo que cambio": the rows that differ with `ctx` rows around them; a stretch left out becomes {gap: true, count}.
export function visibleRows(all, onlyChanged, ctx) {
	if (!onlyChanged) return all
	const c = ctx === undefined ? CONTEXT : ctx
	const keep = new Array(all.length).fill(false)
	all.forEach((r, i) => {
		if (r.flag === 'same') return
		for (let k = Math.max(0, i - c); k <= Math.min(all.length - 1, i + c); k++) keep[k] = true
	})
	const out = []
	let skipped = 0
	all.forEach((r, i) => {
		if (keep[i]) {
			if (skipped) out.push({ gap: true, count: skipped })
			skipped = 0
			out.push(r)
		} else skipped++
	})
	if (skipped && out.length) out.push({ gap: true, count: skipped })
	return out
}

// What "Copiar" puts in the clipboard: the text as it is on the card (the masked one).
export function copyText(view) {
	return view && typeof view.content === 'string' ? view.content : ''
}

// A failed reading as a short sentence with what to do. Never empty. Keys: err_role, err_login, err_unavailable, err_refused, err_other.
export function friendlyError(e, t) {
	const kind = errorKind(e)
	if (kind === 'role') return t('err_role')
	if (kind === 'login') return t('err_login')
	if (kind === 'unavailable' || kind === 'outdated') return t('err_unavailable')
	if (e && (e.code === 'invalid_args' || e.code === 'bad_request')) return t('err_refused')
	return t('err_other')
}

// Why the administrator's diff shows nothing: the first refusal of startup.integrity.restore.preview that explains it, or ''.
// board_busy is not a reason here (the preview does not change anything).
const WHY = ['already_ok', 'factory_missing', 'factory_mismatch', 'wrong_kind', 'not_in_manifest', 'not_a_file']
export function diffWhy(preview) {
	const codes = ((preview && preview.refusals) || []).map(r => r.code)
	const hit = WHY.find(c => codes.indexOf(c) !== -1)
	return hit ? 'diff_why_' + hit : ''
}
