'use strict'

// The ONE module of the new page that touches DuetWebControl: its translator, its store (the object model) and its router.
// Everything else asks here, so a screen never reads $store and a test replaces three small things instead of DWC.
//
//   t(key, params) / tc(key, n, params) / te(key)   texts of the page: a key that does not start with 'plugins.' is taken from the
//                                                   area of this plugin ('home.title' -> 'plugins.WorkshopService.home.title')
//   locale()                    'es' | 'en' ...
//   model()                     the object model of the machine (reactive: read it inside a computed)
//   plugin()                    the entry of this plugin in the model ({ pid, version, data }) or null
//   published(key)              one key of the data the service publishes, or undefined
//   globalVar(name)             a global variable of the board, or undefined when the model has none
//   machineStatus()             state.status of the board ('idle', 'processing' ...), or ''
//   machineMode()               state.machineMode of the board ('FFF', 'Laser', 'CNC'), or ''
//   darkTheme()                 the theme DWC is drawn in
//   query() / setQuery(q, push) the query of the address (?s=&t=&a=): read, and write (push = a step of the history, else replace)
//   notify(type, title, text)   a notification of DWC ('success' | 'info' | 'warning' | 'error'); false when DWC has none
//   pathExists(path) / goPath(path)   another page of DWC: is it registered, and go to it
//   readFile(path)              the text of a file of the machine (DWC's file API), or null
//   saveText(name, text)        gives a text to the person as a file to save
//   saveBase64(name, data, type) gives a file (its content in base64) to the person to save
//   pluginOn(key)               the plugin of the family with this key ('lights', 'camera' ...) is installed and enabled
//
// Never call t() while a module loads: the language of that moment would stay (tests/layers.test.js refuses it).

import Vue from 'vue'
import i18n from '../../../i18n'
import store from '../../../store'
import router from '../../../routes'
import { PLUGIN_ID } from '../plugin-id.js'
import { pluginActive } from '../workshop-ids.js'

const AREA = 'plugins.' + PLUGIN_ID + '.'
const full = key => (String(key).indexOf('plugins.') === 0 ? String(key) : AREA + key)

export function t(key, params) {
	return i18n.t(full(key), params)
}

export function tc(key, n, params) {
	return i18n.tc(full(key), n, Object.assign({ n }, params || {}))
}

export function te(key) {
	return i18n.te(full(key))
}

export function locale() {
	return String(i18n.locale || 'en').slice(0, 2)
}

export function model() {
	const m = store.state && store.state.machine
	return (m && m.model) || null
}

// the model keeps the plugins in a Map; a test may give a plain object
function entryOf(collection, id) {
	if (!collection) return null
	if (typeof collection.get === 'function') return collection.get(id) || null
	return collection[id] || null
}

export function plugin() {
	const m = model()
	return m ? entryOf(m.plugins, PLUGIN_ID) : null
}

export function published(key) {
	const p = plugin()
	const data = p && p.data
	if (!data) return undefined
	return typeof data.get === 'function' ? data.get(key) : data[key]
}

export function globalVar(name) {
	const m = model()
	const g = m && m.global
	if (!g) return undefined
	return typeof g.get === 'function' ? g.get(name) : g[name]
}

export function machineStatus() {
	const m = model()
	return (m && m.state && m.state.status) || ''
}

export function machineMode() {
	const m = model()
	return (m && m.state && m.state.machineMode) || ''
}

export function darkTheme() {
	const s = store.state && store.state.settings
	return !!(s && s.darkTheme)
}

export function query() {
	const r = router && router.currentRoute
	return (r && r.query) || {}
}

export function setQuery(next, push) {
	if (!router || !router.currentRoute) return
	const clean = {}
	Object.keys(next || {}).forEach(k => { if (next[k] !== '' && next[k] !== null && next[k] !== undefined) clean[k] = String(next[k]) })
	const now = query()
	const keys = Object.keys(clean)
	if (keys.length === Object.keys(now).length && keys.every(k => String(now[k]) === clean[k])) return
	const to = { path: router.currentRoute.path, query: clean }
	const done = push ? router.push(to) : router.replace(to)
	if (done && typeof done.catch === 'function') done.catch(() => {}) // the router rejects a navigation to where it already is
}

export function notify(type, title, text) {
	const make = Vue.prototype.$makeNotification
	if (typeof make !== 'function') return false
	make(type, title, text || null)
	return true
}

// ---- other pages of DWC and files of the machine ----

// is there a page at this path (its plugin registered a route)? A stopped plugin keeps its route until DWC is reloaded
export function pathExists(path) {
	try {
		const m = router && router.resolve(path).route.matched
		return !!(m && m.length && m[m.length - 1].path !== '*')
	} catch (e) {
		return false
	}
}

export function goPath(path) {
	if (!router || typeof router.push !== 'function') return
	const done = router.push(path)
	if (done && typeof done.catch === 'function') done.catch(() => {})
}

// the text of a file of the machine through DWC's own file API (no operation of the service), or null when it cannot be read
export async function readFile(path) {
	try {
		const headers = {}
		if (typeof window !== 'undefined' && window.__workshopSession) headers['X-Session-Key'] = window.__workshopSession
		const resp = await fetch('/machine/file/' + encodeURIComponent(path), { headers, cache: 'no-store' })
		return resp.ok ? await resp.text() : null
	} catch (e) {
		return null
	}
}

// hands a text to the person as a file to save
export function saveText(name, text) {
	if (typeof document === 'undefined' || typeof URL === 'undefined') return false
	const a = document.createElement('a')
	a.href = URL.createObjectURL(new Blob([text], { type: 'text/plain' }))
	a.download = name
	document.body.appendChild(a)
	a.click()
	setTimeout(() => { URL.revokeObjectURL(a.href); a.remove() }, 1000)
	return true
}

// a file of the SD card (a DSF path like "0:/sys/workshop/backups/x.tar.gz") handed to the person as a download; resolves true, or false when
// it could not be read (the caller says so). Binary-safe: the answer is kept as a blob.
export async function downloadFile(path, name) {
	if (typeof document === 'undefined' || typeof URL === 'undefined') return false
	try {
		const headers = {}
		if (typeof window !== 'undefined' && window.__workshopSession) headers['X-Session-Key'] = window.__workshopSession
		const resp = await fetch('/machine/file/' + encodeURIComponent(path), { headers, cache: 'no-store' })
		if (!resp.ok) return false
		const a = document.createElement('a')
		a.href = URL.createObjectURL(await resp.blob())
		a.download = name
		document.body.appendChild(a)
		a.click()
		setTimeout(() => { URL.revokeObjectURL(a.href); a.remove() }, 10000)
		return true
	} catch (e) {
		return false
	}
}

// a file whose bytes arrive as base64 (the package of the settings), handed to the person to save
export function saveBase64(name, data, type) {
	if (typeof document === 'undefined' || typeof URL === 'undefined') return false
	try {
		const raw = atob(String(data || ''))
		const bytes = new Uint8Array(raw.length)
		for (let i = 0; i < raw.length; i++) bytes[i] = raw.charCodeAt(i)
		const a = document.createElement('a')
		a.href = URL.createObjectURL(new Blob([bytes], { type: type || 'application/octet-stream' }))
		a.download = name
		document.body.appendChild(a)
		a.click()
		setTimeout(() => { URL.revokeObjectURL(a.href); a.remove() }, 10000)
		return true
	} catch (e) {
		return false
	}
}

export function pluginOn(key) {
	try {
		return pluginActive(store, key)
	} catch (e) {
		return false
	}
}
