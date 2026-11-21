'use strict'

// The REAL things a rule can be limited to ("Only these targets" of the rules editor): what to offer in the box "name or id" and how to say a target in words.
// The service already has a list of most of them (the same operations the plugins' own pages read); the others stay a text box with its help.
//
//   targetListOf(plugin, type)             { op, rows(answer) -> [{ id, name }] } | { fixed: [{ id, name?, nameKey?, params? }] } | null (no list: a text box)
//   targetOptions(plugin, type)            Promise<[{ id, name }] | null>   asks the service once per minute; null = no list, or it did not answer (text box)
//   parseTarget(pattern)                   { plugin, type, id } | null      for "workshop:<plugin>:<type>/<id>"; id '*' = every one of that type
//   describeTarget(pattern, t, names)      { text, id }  the sentence ("Cámara: todas las cámaras", "Impresión: perfil de pellet «Pellet PETG»") and the technical
//                                          pattern for the grey line; t(key, params) translates (area `access`); names = { '<plugin>:<type>': { id: name } }
//
// Pure except targetOptions (one read through the API client). Nothing here writes.

import { TARGET_KINDS } from './access-profile-edit.js'
import * as service from './workshop-api.js' // the namespace, so a page without the client (a test) simply has no lists

const list = (r, key) => (r && Array.isArray(r[key]) ? r[key] : [])
const text = v => (v === undefined || v === null ? '' : String(v))

// where the lights answer keeps its lists: lights.get wraps its configuration, and the wrapper may add a level
function lightsPart(r, key) {
	const seen = [r, r && r.config, r && r.state, r && r.settings, r && r.result]
	for (const o of seen) if (o && typeof o === 'object' && o[key] !== undefined) return o[key]
	return undefined
}

export const LISTS = Object.freeze({
	'printing:pellet': { op: 'pelletlayers.list', rows: r => list(r, 'profiles').map(p => ({ id: text(p.name), name: text(p.name) })) },
	'printing:recipe': { op: 'layerrecipes.list', rows: r => list(r, 'recipes').map(p => ({ id: text(p.name), name: text(p.name) })) },
	'workbench:interrupted': { op: 'livejob.interrupted.list', rows: r => list(r, 'records').map(p => ({ id: text(p.id), name: text(p.name) || text(p.id) })) },
	'lights:scene': {
		op: 'lights.get',
		rows: r => {
			const wl = lightsPart(r, 'work_light')
			return (wl && Array.isArray(wl.scenes) ? wl.scenes : []).map(s => ({ id: text(s.id), name: text(s.name) || text(s.id) }))
		}
	},
	'lights:state': {
		op: 'lights.get',
		rows: r => {
			const st = lightsPart(r, 'states')
			return st && typeof st === 'object' ? Object.keys(st).map(k => ({ id: k, name: text(st[k] && st[k].text) || k })) : []
		}
	},
	// things that always exist: no need to ask
	'printing:bedzone': { fixed: [1, 2, 3, 4, 5, 6, 7, 8, 9].map(n => ({ id: String(n), nameKey: 'target_fixed_bedzone', params: { n } })) },
	'power:timer': { fixed: [{ id: 'shutdown', nameKey: 'target_fixed_timer_shutdown' }, { id: 'after_job', nameKey: 'target_fixed_timer_after_job' }] }
})

export function targetListOf(plugin, type) {
	return LISTS[plugin + ':' + type] || null
}

const cache = {}
const TTL_MS = 60000

// the options of one kind, or null when the box stays a text box (no list, the answer is not usable, or the service did not answer)
export function targetOptions(plugin, type, t) {
	const def = targetListOf(plugin, type)
	if (!def) return Promise.resolve(null)
	if (def.fixed) return Promise.resolve(def.fixed.map(f => ({ id: f.id, name: f.nameKey && t ? t(f.nameKey, f.params) : f.name || f.id })))
	const key = plugin + ':' + type
	if (typeof service.api !== 'function') return Promise.resolve(null)
	const hit = cache[def.op]
	const now = Date.now()
	const ask = hit && now - hit.at < TTL_MS ? Promise.resolve(hit.answer) : service.api(def.op, {}, { quiet: true }).then(a => { cache[def.op] = { at: Date.now(), answer: a }; return a })
	return ask.then(a => def.rows(a).filter(r => r.id), () => { void key; return null })
}

export function clearTargetCache() {
	Object.keys(cache).forEach(k => delete cache[k])
}

const PATTERN = /^workshop:([a-z0-9_]{1,32}):([a-z0-9_]{1,32})\/(.+)$/

export function parseTarget(pattern) {
	const m = PATTERN.exec(text(pattern))
	if (!m) return null
	let id = m[3]
	try { id = decodeURIComponent(id) } catch (e) { /* an id with a stray % stays as it is */ }
	return { plugin: m[1], type: m[2], id }
}

export function describeTarget(pattern, t, names) {
	const p = parseTarget(pattern)
	const known = p && TARGET_KINDS.some(k => k[0] === p.plugin && k[1].indexOf(p.type) >= 0) // a kind the table does not name (another part of the service) is said as it is
	if (!p || !known) return { text: t('target_desc_other', { raw: text(pattern) }), id: text(pattern) }
	const plugin = t('target_plugin_' + p.plugin)
	if (p.id === '*') return { text: t('target_desc_all', { plugin, all: t('target_all_' + p.plugin + '_' + p.type) }), id: text(pattern) }
	const named = names && names[p.plugin + ':' + p.type] && names[p.plugin + ':' + p.type][p.id]
	return { text: t('target_desc_one', { plugin, kind: t('target_one_' + p.plugin + '_' + p.type), name: named || p.id }), id: text(pattern) }
}

// the kinds whose names are worth asking for to describe a list of patterns (the ones that have a list and are named one by one)
export function kindsToName(patterns) {
	const seen = {}
	;(patterns || []).forEach(x => {
		const p = parseTarget(x)
		if (p && p.id !== '*' && targetListOf(p.plugin, p.type)) seen[p.plugin + ':' + p.type] = [p.plugin, p.type]
	})
	return Object.keys(seen).map(k => seen[k])
}
