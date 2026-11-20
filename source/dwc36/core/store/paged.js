'use strict'

// A list the service gives in pages (audit, received commands, activity, start-up runs).
//
//   const audit = createPagedResource({
//     key: 'audit',
//     load: ({ limit, offset, filters, range }) => ops.audit.list(...),    resolves { rows: [...], total: n }
//     needs: 'audit.list', pageSize: 50, maxRows: 1000
//   })
//   audit.status    'idle' | 'loading' | 'ready' | 'empty' | 'error' | 'locked' | 'refreshing'      audit.more   true while the next page loads
//   audit.rows / audit.total / audit.hasMore / audit.capped (the list reached maxRows: narrow the filter) / audit.error / audit.lock
//   audit.filters / audit.range      what the rows on screen were asked with
//   audit.show() / audit.hide()      as a resource: loads the first page the first time its screen is visible
//   audit.setFilters(filters, range) a new question: the list starts again from the first page
//   audit.loadMore()                 the next page, added at the end           audit.reload()   the same question again, from the start
//
// The range of dates is fixed when the filters are applied (never "until now"): a row that arrives meanwhile cannot shift the pages
// that are already on screen. An answer that arrives after a newer question, or after the person changed, is dropped.

import Vue from 'vue'
import { can, onSessionChange } from './session.js'
import { ServiceError } from '../api/errors.js'
import { timeNow } from '../clock.js'

const all = new Set()
let offSession = null

const asError = e => (e instanceof ServiceError ? e : new ServiceError({ code: 'internal', message: (e && e.message) || String(e), raw: e }))

function gate(x) {
	const r = x.r
	if (!x.o.needs) return true
	const c = can(x.o.needs)
	if (c.state === 'ok') { r.lock = null; return true }
	if (c.state === 'resolving') { r.lock = null; if (!r.rows.length) r.status = 'loading'; return false }
	Object.assign(r, { lock: { state: c.state, cause: c.cause, neededRole: c.neededRole, text: c.text }, rows: [], total: 0, hasMore: false, error: null, status: 'locked' })
	return false
}

function accept(x, page, offset) {
	const r = x.r
	const rows = Array.isArray(page && page.rows) ? page.rows : []
	const list = (offset ? r.rows.concat(rows) : rows).slice(0, x.o.maxRows)
	const total = typeof (page && page.total) === 'number' ? page.total : list.length
	r.rows = list
	r.total = total
	r.capped = list.length >= x.o.maxRows && total > list.length
	r.hasMore = !r.capped && list.length < total && rows.length > 0
	r.error = null
	r.loadedAt = x.now()
	r.status = list.length ? 'ready' : 'empty'
}

function refuse(x, e) {
	const r = x.r
	r.error = asError(e)
	if (r.error.kind === 'session' || r.error.kind === 'role') {
		Object.assign(r, { lock: { state: r.error.kind, cause: r.error.reason || r.error.kind, neededRole: '', text: r.error.message }, rows: [], total: 0, hasMore: false, status: 'locked' })
	} else r.status = r.rows.length ? 'ready' : 'error'
}

// offset 0 = the question from the start; else the next page
function fetchPage(x, offset) {
	const r = x.r
	if (x.flight && x.flightOffset === offset) return x.flight
	if (!gate(x)) return Promise.resolve(r)
	const mine = ++x.generation
	const current = () => mine === x.generation
	if (offset) r.more = true
	else r.status = r.rows.length ? 'refreshing' : 'loading'
	x.flightOffset = offset
	x.flight = Promise.resolve().then(() => x.o.load({ limit: x.o.pageSize, offset, filters: r.filters, range: r.range }))
		.then(page => { if (current()) accept(x, page, offset) }, e => { if (current()) refuse(x, e) })
		.then(() => { if (current()) { x.flight = null; r.more = false } return r })
	return x.flight
}

function clear(x) {
	x.generation += 1
	x.flight = null
	Object.assign(x.r, { status: 'idle', rows: [], total: 0, hasMore: false, capped: false, more: false, error: null, lock: null, loadedAt: 0 })
}

export function createPagedResource(options) {
	const o = Object.assign({ pageSize: 50, maxRows: 1000, needs: '', filters: {}, range: null }, options || {})
	if (!o.key || typeof o.load !== 'function') throw new Error('createPagedResource: key and load are required')
	const r = Vue.observable({ key: o.key, status: 'idle', rows: [], total: 0, hasMore: false, capped: false, more: false, error: null, lock: null,
		loadedAt: 0, visible: false, filters: Object.assign({}, o.filters), range: o.range })
	const x = { r, o, generation: 0, flight: null, flightOffset: -1, now: () => (o.now ? o.now() : timeNow()) }
	r.reload = () => fetchPage(x, 0)
	r.show = () => {
		r.visible = true
		const waiting = r.status === 'loading' && !x.flight
		return r.status === 'idle' || r.status === 'locked' || waiting || (r.status === 'error' && !r.rows.length) ? fetchPage(x, 0) : Promise.resolve(r)
	}
	r.hide = () => { r.visible = false }
	r.setFilters = (filters, range) => {
		r.filters = Object.assign({}, filters || {})
		if (range !== undefined) r.range = range
		x.flight = null
		r.rows = []
		return fetchPage(x, 0)
	}
	r.loadMore = () => (r.hasMore && !r.more && r.status === 'ready' ? fetchPage(x, r.rows.length) : Promise.resolve(r))
	r.clear = () => clear(x)
	r.recheck = () => { clear(x); return r.visible ? fetchPage(x, 0) : Promise.resolve(r) }
	r.dispose = () => { clear(x); all.delete(r) }
	all.add(r)
	if (!offSession) offSession = onSessionChange(() => all.forEach(y => y.recheck()))
	return r
}
