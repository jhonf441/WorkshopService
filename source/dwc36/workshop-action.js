'use strict'

// The state machine of ONE write (FASE2 of the style unification, promoted from WorkshopService core/store/action.js). A person touches a control, the
// control says what happens next, and the page never keeps loose `sending / message / error` fields of its own.
//
//   const save = createAction({
//     run: (args, ctx) => api('notifications.type', args),     the call (a promise; ctx.confirmed is true after a confirmation the page asked)
//     permission: args => ({ state: 'ok' | 'resolving' | 'session' | 'role', text }),    optional: asked before anything else
//     arm: 'none' | 'double' | args => ..,                      'double' = a second touch within armMs (a first touch only arms the control)
//     confirm: args => null | { level: 3 | 4, title, text, check },    a dialog (WfConfirm) before the call; null = no dialog
//     verify: { until: (data, args) => bool, timeoutMs, everyMs },     for answers that prove nothing: wait until the published data shows it
//     after: (data, args) => promise | [promises],              what to read again once it is done
//     group: 'machine',                                         one write at a time per group (none = no limit)
//     onBusy: 'ignore' | 'refuse',                              a touch while ANOTHER action of the group works: 'ignore' (default) does nothing; 'refuse' ends in
//                                                               state 'error' with { code: 'busy', message: busyText } for doneMs, so the page can say WHY (WfResult draws it)
//     busyText: string | args => string                         the reason said by a busy refusal (translated by the page; empty = WfResult's own sentence)
//     armMs, doneMs                                             times (defaults ARM_MS = 4000 and 6000)
//   })
//   save.state     'idle' | 'armed' | 'confirming' | 'sending' | 'verifying' | 'done' | 'error'
//   save.error     the error of the call, or { code: 'unverified' } when the data never showed the change     save.text / save.data   what it answered
//   save.confirm   { level, check, title, text } while state is 'confirming'
//   save.run(args) the control was touched        save.accept() / save.cancel()   the answer to the dialog        save.retry()   run again with the last arguments
//   save.hold(true)  keyboard focus is on the armed control: its time does not run        save.reset()        save.busy()        save.dispose()
//   outcomeOf(state, error)  the six things a person can read next to the control (see below)
//
// Order, always: permission -> arm (double touch) -> confirmation -> call -> verification -> after. While it sends, verifies or waits for a dialog, a
// second touch does nothing: ONE request per action. A person who is not allowed never sees an arm or a dialog.
// The module is pure but for `Vue.observable` (what the page reads must be reactive); a test hands its own `observable` and `clock` (nothing here
// reads the DWC store, the session or the API: whoever creates the action brings them).
//
// The double touch time is ARM_MS (arm-ms.js: 4000 ms for the whole family, DESIGN.md section 5); WF_ARM_WINDOW is the same constant under the name the pages already import.

import Vue from 'vue'
import { ARM_MS } from './arm-ms.js'

export { ARM_MS as WF_ARM_WINDOW }
export const WF_DONE_WINDOW = 6000    // "done" leaves by itself after this (design guide 6.7)
export const WF_VERIFY_TIMEOUT = 10000
export const WF_VERIFY_EVERY = 500
export const WF_BUSY_STATES = Object.freeze(['confirming', 'sending', 'verifying'])

const REAL_CLOCK = {
	now: () => Date.now(),
	set: (fn, ms) => setTimeout(fn, ms),
	clear: id => clearTimeout(id)
}

const holders = new Map()    // group -> the action that holds it

// What a person reads next to the control: 'none' | 'sending' | 'verifying' | 'done' | 'refused' | 'unverified'.
// 'unverified' is the answer that proved nothing: the service answered but the change was not seen (never shown as done, never as a plain failure).
export function outcomeOf(state, error) {
	if (state === 'sending') return 'sending'
	if (state === 'verifying') return 'verifying'
	if (state === 'done') return 'done'
	if (state === 'error') return error && error.code === 'unverified' ? 'unverified' : 'refused'
	return 'none'
}

function asError(e) {
	if (e && typeof e === 'object') return e
	return { code: 'internal', message: String(e) }
}

// Why a write ended without being a plain failure: 'refusal' (the session or the role does not allow it: login_required / forbidden, or error.cause === 'refusal'),
// 'busy' (another write of the group holds the machine) or '' (a real failure). WfResult reads it; a page may too.
export function causeOf(error) {
	if (!error || typeof error !== 'object') return ''
	if (error.cause === 'refusal' || error.code === 'login_required' || error.code === 'forbidden') return 'refusal'
	if (error.code === 'busy') return 'busy'
	return ''
}

export function createAction(options) {
	const o = Object.assign({ arm: 'none', armMs: ARM_MS, doneMs: WF_DONE_WINDOW, onBusy: 'ignore' }, options || {})
	if (typeof o.run !== 'function') throw new Error('createAction: run is required')
	const observable = o.observable || Vue.observable
	const clock = o.clock || REAL_CLOCK
	const a = observable({ state: 'idle', error: null, text: '', data: null, confirm: null, armedUntil: 0 })
	const x = { args: {}, held: false, generation: 0, handle: null }

	const stop = () => { if (x.handle !== null) { clock.clear(x.handle); x.handle = null } }
	const later = (ms, fn) => { stop(); x.handle = clock.set(() => { x.handle = null; fn() }, ms) }
	const release = () => { if (o.group && holders.get(o.group) === a) holders.delete(o.group) }
	const finish = (state, error) => {
		stop()
		release()
		Object.assign(a, { state, error: error || null, confirm: null, armedUntil: 0 })
		if (state === 'done') later(o.doneMs, () => { if (a.state === 'done') a.state = 'idle' })
	}

	// the answer proved nothing: look at what the service publishes until it shows, or say that it could not be confirmed
	const verify = () => {
		const mine = x.generation
		const deadline = clock.now() + ((o.verify && o.verify.timeoutMs) || WF_VERIFY_TIMEOUT)
		const every = (o.verify && o.verify.everyMs) || WF_VERIFY_EVERY
		a.state = 'verifying'
		const look = () => {
			if (mine !== x.generation) return
			let ok = false
			try { ok = !!o.verify.until(a.data, x.args) } catch (e) { ok = false }
			if (ok) return settle()
			if (clock.now() >= deadline) return finish('error', { code: 'unverified', message: a.text || '' })
			later(every, look)
		}
		look()
	}

	const settle = async () => {
		const mine = x.generation
		try {
			const more = o.after ? o.after(a.data, x.args) : null
			if (more) await Promise.all([].concat(more))
		} catch (e) { /* the action itself was done: a failed reload shows in its own zone */ }
		if (mine === x.generation) finish('done')
	}

	const send = async confirmed => {
		const mine = x.generation
		stop()
		Object.assign(a, { state: 'sending', confirm: null, error: null })
		if (o.group) holders.set(o.group, a)
		let res
		try {
			res = await o.run(x.args, { confirmed: !!confirmed })
		} catch (e) {
			if (mine !== x.generation) return
			const err = asError(e)
			return finish(err.cancelled || err.kind === 'cancelled' ? 'idle' : 'error', err.cancelled || err.kind === 'cancelled' ? null : err)
		}
		if (mine !== x.generation) return
		a.text = (res && typeof res === 'object' && res.text) || ''
		a.data = res && typeof res === 'object' && 'data' in res ? res.data : res
		if (o.verify) return verify()
		return settle()
	}

	a.run = args => {
		if (WF_BUSY_STATES.indexOf(a.state) >= 0) return undefined
		const holder = o.group ? holders.get(o.group) : null
		const occupied = !!holder && holder !== a
		if (occupied && o.onBusy !== 'refuse') return undefined
		const perm = o.permission ? o.permission(args) : null
		if (perm && perm.state === 'resolving') return undefined
		if (perm && perm.state && perm.state !== 'ok') {
			return finish('error', { code: perm.state === 'session' ? 'login_required' : 'forbidden', message: perm.text || '' })
		}
		// the group is held by another action and this one asked to say so: the person reads why nothing happened (a person who is not allowed read the refusal above)
		if (occupied) {
			const text = typeof o.busyText === 'function' ? o.busyText(args) : o.busyText
			finish('error', { code: 'busy', message: text || '' })
			later(o.doneMs, () => { if (a.state === 'error' && a.error && a.error.code === 'busy') finish('idle') })
			return undefined
		}
		x.args = args || {}
		const arm = (typeof o.arm === 'function' ? o.arm(x.args) : o.arm) || 'none'
		if (arm === 'double' && a.state !== 'armed') {
			Object.assign(a, { state: 'armed', error: null, armedUntil: clock.now() + o.armMs })
			later(o.armMs, function tick() {
				if (a.state !== 'armed') return
				// keyboard focus on the control: the time does not run; after the focus leaves, the deadline (armedUntil) was moved forward and is waited again
				if (x.held || clock.now() < a.armedUntil) { x.handle = clock.set(tick, 250); return }
				finish('idle')
			})
			return undefined
		}
		stop()
		a.error = null
		const c = o.confirm ? o.confirm(x.args) : null
		if (c) {
			Object.assign(a, { state: 'confirming', confirm: { level: c.level || 3, check: !!c.check || (c.level || 3) >= 4, title: c.title || '', text: c.text || '' } })
			if (o.group) holders.set(o.group, a)
			return undefined
		}
		return send(false)
	}
	a.accept = () => (a.state === 'confirming' ? send(true) : undefined)
	a.cancel = () => { if (a.state === 'confirming' || a.state === 'armed') finish('idle') }
	a.retry = () => { if (a.state === 'error' || a.state === 'idle' || a.state === 'done') return a.run(x.args) }
	// keyboard focus on the armed control: the time does not run; when the focus leaves, the full armMs counts again from that moment
	a.hold = on => {
		x.held = !!on
		if (!on && a.state === 'armed') { a.armedUntil = clock.now() + o.armMs }
	}
	a.reset = () => {
		x.generation += 1
		finish('idle')
		Object.assign(a, { text: '', data: null })
	}
	a.busy = () => WF_BUSY_STATES.indexOf(a.state) >= 0
	a.outcome = () => outcomeOf(a.state, a.error)
	a.dispose = () => { a.reset() }
	return a
}
