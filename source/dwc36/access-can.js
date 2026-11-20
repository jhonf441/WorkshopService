'use strict'

// The answers of auth.can for the controls of a screen, asked in ONE batch and kept for the session (DISENO-PANTALLAS section 3.4, step 8).
// Pure: no Vue, no client, no identity of its own; the page that uses it passes the call and tells it when the identity changed.
//
//   const store = makeCanStore({ call, ttl })      call(items) -> the answer of auth.can with `operations: items` ({ items: [...] }), or throws
//   store.want(items)        Promise; asks what is not known yet (or is older than ttl) in one call; the calls of the same tick are one call;
//                            more than MAX_BATCH items are split in calls of MAX_BATCH. An item is an operation name or { operation, target }.
//   store.get(op, target)    the cached answer { allowed, reason, text, target } or null (never asks)
//   store.refresh()          forget the answers and ask again for everything that was wanted (identity change, a 403)
//   store.noteIdentity(key)  refresh when the key (role, signed in, person) is not the one of the last time
//   store.noteForbidden()    a call was refused with 403: the permission changed under the page; refresh
//   store.onChange(fn)       fn() when answers arrive or are forgotten; returns the off function
//
// A failed call leaves no answer (the page keeps what its role table says) and is not repeated by itself before RETRY_MS.

import { causeOfDecision } from './access-reason.js'

export const MAX_BATCH = 100 // auth.can takes up to 100 items per call
export const TTL_MS = 30000
export const RETRY_MS = 5000

export function itemOf(x) {
	if (typeof x === 'string') return { operation: x }
	const o = { operation: String((x && x.operation) || '') }
	if (x && x.target) o.target = String(x.target)
	return o
}

export function answerKey(op, target) {
	return String(op) + '|' + (target || '')
}

export function makeCanStore(options) {
	const o = options || {}
	const call = o.call
	const ttl = o.ttl === undefined ? TTL_MS : o.ttl
	const now = o.now || Date.now
	const warn = o.warn || (typeof console !== 'undefined' ? m => console.warn(m) : () => {})
	const answers = new Map() // key -> { answer, at }
	const wanted = new Map() // key -> item, everything a screen has asked for (what refresh() asks again)
	const listeners = []
	let queue = new Map()
	let scheduled = false
	let flights = 0
	let generation = 0
	let failedAt = -Infinity
	let identity = null
	let waiters = []
	const store = { calls: 0 }

	const changed = () => listeners.slice().forEach(fn => { try { fn() } catch (e) { /* a listener must not break the others */ } })
	const fresh = k => {
		const a = answers.get(k)
		return !!a && (ttl <= 0 ? false : now() - a.at < ttl)
	}

	async function send(items, gen) {
		store.calls++
		let r = null
		try {
			r = await call(items.map(itemOf))
		} catch (e) {
			failedAt = now()
			return
		}
		if (gen !== generation) return
		// an answer the page cannot use (no list of items, or no item with a decision) counts as a failed call: without it the page would ask
		// again at once, on every refresh, and never leave the loop (it was found by tests/session-reset.test.js, whose stub answers {})
		if (!r || !Array.isArray(r.items)) { failedAt = now(); return }
		let used = 0
		r.items.forEach((it, i) => {
			if (!it || typeof it.allowed !== 'boolean') return // an item the service could not use: no answer, the page keeps its table
			const src = itemOf(items[i])
			const key = answerKey(src.operation, src.target)
			answers.set(key, { answer: it, at: now() })
			used++
			if (it.allowed === false && causeOfDecision(it.reason) === 'unknown') warn('auth.can: unknown cause for ' + src.operation + ': ' + JSON.stringify(it.reason || null))
		})
		if (!used) failedAt = now()
	}

	async function flush() {
		scheduled = false
		const items = Array.from(queue.values())
		const mine = waiters
		queue = new Map()
		waiters = []
		if (!items.length) return mine.forEach(w => w())
		const gen = generation
		flights++
		const parts = []
		for (let i = 0; i < items.length; i += MAX_BATCH) parts.push(items.slice(i, i + MAX_BATCH))
		await Promise.all(parts.map(p => send(p, gen)))
		flights--
		mine.forEach(w => w())
		if (gen === generation) changed()
	}

	store.want = function (list) {
		let any = false
		;(list || []).forEach(x => {
			const it = itemOf(x)
			if (!it.operation) return
			const k = answerKey(it.operation, it.target)
			wanted.set(k, it)
			if (fresh(k) || queue.has(k)) return
			if (now() - failedAt < RETRY_MS) return
			queue.set(k, it)
			any = true
		})
		if (!any) return Promise.resolve()
		return new Promise(res => {
			waiters.push(res)
			if (!scheduled) {
				scheduled = true
				Promise.resolve().then(flush)
			}
		})
	}

	store.get = function (op, target) {
		const a = answers.get(answerKey(op, target))
		return a ? a.answer : null
	}

	store.pending = () => flights > 0 || queue.size > 0

	store.refresh = function () {
		generation++
		answers.clear()
		failedAt = -Infinity
		const all = Array.from(wanted.values())
		changed()
		return store.want(all)
	}

	store.noteIdentity = function (key) {
		if (identity === key) return Promise.resolve()
		identity = key // the first key is the baseline of the page; a different one (even from an unknown identity) is a change
		return store.refresh()
	}

	store.noteForbidden = () => store.refresh()
	store.onChange = fn => {
		listeners.push(fn)
		return () => {
			const i = listeners.indexOf(fn)
			if (i >= 0) listeners.splice(i, 1)
		}
	}
	store.forget = () => { wanted.clear() } // a screen left: what it asked is not asked again by refresh()
	return store
}
