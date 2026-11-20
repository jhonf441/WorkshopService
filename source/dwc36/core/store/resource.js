'use strict'

// One datum asked to the service, with its whole life: every screen of the new page reads its data through one of these, so
// "loading", "nothing", "it failed", "not for you" and "old" look and behave the same everywhere.
//
//   const users = createResource({
//     key: 'users',                      unique name
//     load: () => ops.users.list(),      returns the data (a promise); throws ServiceError
//     needs: 'users.list',               the operation that gates it: without permission NOTHING is sent and the status is 'locked'
//     staleMs: 30000,                    older than this, it is read again when its screen is shown again (0 = never by age)
//     empty: d => !d.users.length,       "there is nothing" (status 'empty')
//     sessionScoped: true,               default: forgotten when the person changes
//     watch: 'commands'                  optional tag: touch('commands') marks it old
//   })
//   users.status   'idle' | 'loading' | 'ready' | 'empty' | 'error' | 'locked' | 'refreshing' | 'stale'
//   users.data / users.error (ServiceError) / users.loadedAt (ms) / users.lock ({ state: 'session' | 'role', cause, neededRole, text })
//   users.show()    its screen is visible: loads the first time, reloads when old       users.hide()   its screen is not visible
//   users.reload()  ask again now (what is shown stays while it arrives: 'refreshing')   users.mutate(fn)   the action already has the new data
//   users.clear()   forget everything
//
// Rules: one request in flight per resource; an answer that arrives after the person changed, or after clear(), is dropped; a failed
// refresh keeps the data and leaves the error next to it; with the service stopped the data stays, marked 'stale'.

import Vue from 'vue'
import { can, onSessionChange } from './session.js'
import { awake } from '../page-state.js'
import { timeNow } from '../clock.js'
import { ServiceError } from '../api/errors.js'

const all = new Set()
let serviceDown = false
let offSession = null

const asError = e => (e instanceof ServiceError ? e : new ServiceError({ code: 'internal', message: (e && e.message) || String(e), raw: e }))

const lockOf = c => ({ state: c.state, cause: c.cause, neededRole: c.neededRole, text: c.text, fixed: !!c.fixed })
const settled = x => (x.r.data === null ? 'idle' : x.o.empty && x.o.empty(x.r.data) ? 'empty' : 'ready')

// may it be asked now? false = no (locked, or the session is not known yet: the change of session asks again)
function gate(x) {
	const r = x.r
	if (!x.o.needs) return true
	const c = can(x.o.needs)
	if (c.state === 'ok') { r.lock = null; return true }
	if (c.state === 'resolving') { r.lock = null; if (r.data === null) r.status = 'loading'; return false }
	Object.assign(r, { lock: lockOf(c), data: null, error: null, status: 'locked' })
	return false
}

function loaded(x, data) {
	const r = x.r
	Object.assign(r, { data: data === undefined ? null : data, error: null, loadedAt: x.now(), old: false })
	r.status = r.data === null ? 'empty' : settled(x)
}

function failed(x, e) {
	const r = x.r
	r.error = asError(e)
	// no permission after all (the table said yes, the service says no): the lock, not an error
	if (r.error.kind === 'session' || r.error.kind === 'role') {
		const lock = { state: r.error.kind, cause: r.error.reason || r.error.kind, neededRole: (r.error.extra && r.error.extra.needed_role) || '', text: r.error.message }
		Object.assign(r, { lock, data: null, status: 'locked' })
	} else r.status = r.data === null ? 'error' : settled(x)
}

function load(x) {
	const r = x.r
	if (x.flight) return x.flight
	if (!gate(x)) return Promise.resolve(r)
	if (serviceDown && r.data !== null) { r.status = 'stale'; return Promise.resolve(r) }
	const mine = x.generation
	const current = () => mine === x.generation
	r.status = r.data === null ? 'loading' : 'refreshing'
	x.flight = Promise.resolve().then(() => x.o.load())
		.then(data => { if (current()) loaded(x, data) }, e => { if (current()) failed(x, e) })
		.then(() => { if (current()) x.flight = null; return r })
	return x.flight
}

function show(x) {
	const r = x.r
	r.visible = true
	const aged = x.o.staleMs > 0 && r.loadedAt > 0 && x.now() - r.loadedAt > x.o.staleMs
	const waiting = r.status === 'loading' && !x.flight
	if (r.status === 'idle' || r.status === 'locked' || waiting || r.old || aged || (r.status === 'error' && r.data === null)) return load(x)
	return Promise.resolve(r)
}

function clear(x) {
	x.generation += 1
	x.flight = null
	Object.assign(x.r, { status: 'idle', data: null, error: null, loadedAt: 0, lock: null, old: false })
}

export function createResource(options) {
	const o = Object.assign({ staleMs: 0, sessionScoped: true, empty: null, needs: '', watch: '' }, options || {})
	if (!o.key || typeof o.load !== 'function') throw new Error('createResource: key and load are required')
	const r = Vue.observable({ key: o.key, status: 'idle', data: null, error: null, loadedAt: 0, lock: null, visible: false, old: false })
	const x = { r, o, generation: 0, flight: null, now: () => (o.now ? o.now() : timeNow()) }
	r.reload = () => load(x)
	r.show = () => show(x)
	r.hide = () => { r.visible = false }
	r.clear = () => clear(x)
	r.mutate = fn => {
		const next = fn(r.data)
		if (next !== undefined) r.data = next
		r.loadedAt = x.now()
		r.status = settled(x)
	}
	// something else changed what this shows: read again now if somebody looks, else when shown
	r.invalidate = () => {
		r.old = true
		return r.visible && awake() ? load(x) : Promise.resolve(r)
	}
	// the person changed (or is known at last): forget what belonged to the session, and read for this person if the screen is on
	r.recheck = () => {
		if (o.sessionScoped) clear(x)
		return r.visible ? load(x) : Promise.resolve(r)
	}
	r.dispose = () => { clear(x); all.delete(r) }
	r.options = Object.freeze({ needs: o.needs, watch: o.watch, sessionScoped: o.sessionScoped, staleMs: o.staleMs })
	all.add(r)
	if (!offSession) offSession = onSessionChange(() => all.forEach(y => y.recheck()))
	return r
}

// every resource that declared `watch: tag` is old now (a write somewhere else, a new command in the history)
export function touch(tag) {
	all.forEach(r => { if (r.options.watch === tag) r.invalidate() })
}

// the service stopped (its pid is gone) / came back: what is shown stays, marked old; back -> the visible ones are read again
export function setServiceDown(down) {
	const was = serviceDown
	serviceDown = !!down
	if (serviceDown && !was) all.forEach(r => { if (r.data !== null) r.status = 'stale' })
	if (!serviceDown && was) all.forEach(r => { if (r.status === 'stale') { r.old = true; r.status = r.data === null ? 'idle' : 'ready'; if (r.visible) r.reload() } })
}

export function resourceCount() {
	return all.size
}
