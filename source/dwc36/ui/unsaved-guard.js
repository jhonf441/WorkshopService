'use strict'

// "Unsaved changes": ONE guard for every editor of the page that has Save / Cancel (profiles, keys, people, settings, the bridge...). Nothing saves by itself.
//
//   sameContent(a, b)           true when two values hold the same content (a deep copy compare, key order and undefined-vs-null do not count): a touch that changed nothing is not a change
//   snapshot(v)                 a deep copy: the baseline an editor compares its draft with
//   saveWithAction(action, start)  "Save and leave" for a Save that goes through a store action: Promise<bool>
//   registerGuard(g)            an editor says it can hold changes: g = { dirty(): bool, save(): Promise<bool | 'later'>, discard?(), label?(): string }; returns the function that takes it away
//   anyDirty() / dirtyGuards()  who holds unsaved changes now
//   confirmLeave(go, stay?)     the one door out: runs go() at once when nothing is unsaved, else asks (SvUnsavedDialog.vue) with three answers:
//                                 keepEditing()   stay (stay() runs)          saveAndLeave()  every editor saves, then go()          discardAndLeave()  go() without saving
//                               'later' from save(): the editor opened its own review (a before / after dialog) and calls resumeLeave() when it saved, or dropLeave() if the person cancelled it
//   routeGuard(to, from, next)  the in-component guard of the page (vue-router: beforeRouteUpdate / beforeRouteLeave): a change of section or tab, the Back button and DWC's own menu
//                               ask first; an anchor inside the same tab does not
//   The state of the dialog is `unsaved` (reactive). beforeunload (reload, close the tab) is the browser's own message while something is unsaved.

import Vue from 'vue'

export const unsaved = Vue.observable({ list: [], pending: null, waiting: false, error: '' })

const isObject = v => v !== null && typeof v === 'object'

function canonical(v) {
	if (Array.isArray(v)) return v.map(canonical)
	if (isObject(v)) {
		const out = {}
		Object.keys(v).sort().forEach(k => { if (v[k] !== undefined) out[k] = canonical(v[k]) })
		return out
	}
	return v === undefined ? null : v
}

export function sameContent(a, b) {
	return JSON.stringify(canonical(a)) === JSON.stringify(canonical(b))
}

// a deep copy of what was saved or loaded: the baseline an editor compares its draft with
export function snapshot(v) {
	return v === undefined ? null : JSON.parse(JSON.stringify(v))
}

// "Save and leave" for an editor that saves through a store action (core/store/action.js): starts it and says, once it ends, whether it was saved (false: refused before
// sending, failed or took too long). `start` is what the Save button does.
export function saveWithAction(action, start) {
	return new Promise(resolve => {
		if (action.reset) action.reset()
		start()
		let n = 0
		let later = false
		const tick = () => {
			if (action.state === 'confirming' && !later) { later = true; resolve('later') } // the action asks its own confirmation: this dialog steps aside until it ends
			if (action.state === 'done') return later ? resumeLeave() : resolve(true)
			if (action.state === 'error' || (action.state === 'idle' && n === 0)) return later ? dropLeave() : resolve(false)
			if (action.state === 'idle' && later) return dropLeave()
			if (++n > 600) return later ? dropLeave() : resolve(false)
			setTimeout(tick, 100)
		}
		tick()
	})
}

export function registerGuard(g) {
	unsaved.list.push(g)
	return () => {
		const i = unsaved.list.indexOf(g)
		if (i >= 0) unsaved.list.splice(i, 1)
	}
}

export function dirtyGuards() {
	return unsaved.list.filter(g => { try { return !!g.dirty() } catch (e) { return false } })
}

export function anyDirty() {
	return dirtyGuards().length > 0
}

// true when the person was asked (go() waits), false when nothing was unsaved and go() already ran
export function confirmLeave(go, stay) {
	if (!anyDirty()) {
		go()
		return false
	}
	unsaved.error = ''
	unsaved.waiting = false
	unsaved.pending = { go, stay: stay || (() => {}) }
	return true
}

export function keepEditing() {
	const p = unsaved.pending
	unsaved.pending = null
	unsaved.waiting = false
	unsaved.error = ''
	if (p) p.stay()
}

function finish() {
	const p = unsaved.pending
	unsaved.pending = null
	unsaved.waiting = false
	unsaved.error = ''
	if (p) p.go()
}

export function discardAndLeave() {
	// an editor may discard asynchronously (it re-reads its file): wait for it, and go anyway when it fails
	const waits = []
	dirtyGuards().forEach(g => {
		try {
			const r = g.discard ? g.discard() : null
			if (r && typeof r.then === 'function') waits.push(r.catch(() => { /* the editor goes anyway */ }))
		} catch (e) { /* the editor goes anyway */ }
	})
	if (!waits.length) { finish(); return undefined }
	return Promise.all(waits).then(finish)
}

export async function saveAndLeave() {
	if (!unsaved.pending) return false
	unsaved.error = ''
	for (const g of dirtyGuards()) {
		let r = false
		try { r = await g.save() } catch (e) { r = false }
		if (r === 'later') { unsaved.waiting = true; return 'later' } // the editor asks its own confirmation and tells us when it is done
		if (!r) { unsaved.error = 'unsaved_failed'; return false }
	}
	finish()
	return true
}

export function resumeLeave() {
	if (unsaved.pending && unsaved.waiting) saveAndLeave()
}

export function dropLeave() {
	if (unsaved.pending && unsaved.waiting) keepEditing()
}

// vue-router: to / from are routes; only a different section or tab leaves an editor
export function routeGuard(to, from, next) {
	const q = r => (r && r.query) || {}
	const same = to && from && to.path === from.path && String(q(to).s || '') === String(q(from).s || '') && String(q(to).t || '') === String(q(from).t || '')
	if (same || !anyDirty()) return next()
	confirmLeave(() => next(), () => next(false))
}

// reload and closing the tab: the message is the browser's own (the page cannot change its words)
export function beforeUnload(e) {
	if (!anyDirty()) return undefined
	e.preventDefault()
	e.returnValue = ''
	return ''
}

if (typeof window !== 'undefined' && typeof window.addEventListener === 'function' && !window.__workshopUnsavedGuard) {
	window.__workshopUnsavedGuard = true
	window.addEventListener('beforeunload', beforeUnload)
}
