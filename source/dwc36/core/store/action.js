'use strict'

// One thing a person does = one action = one control. It replaces the loose `sending / message / error` fields of the old page.
//
//   const restart = createAction({
//     op: 'service.restart',                       the operation (also what the permission is asked for)
//     args: () => ({}),                            optional: the arguments when run() is called without them
//     arm: 'double',                               page confirmation: 'none' | 'double' (second touch within 5 s) | 'dialog' | 'dialog-check';
//                                                  or a function of the arguments (arming asks, disarming does not)
//     verify: { until: () => bool, timeoutMs },    for answers that prove nothing: wait until the published data shows it
//     after: () => [users.reload()],               what to read again once it is done
//     group: 'machine'                             one write at a time per group (default: the operation name)
//   })
//   restart.state    'idle' | 'armed' | 'confirming' | 'sending' | 'verifying' | 'done' | 'error'
//   restart.error    ServiceError | null        restart.text / restart.data   what the service answered
//   restart.confirm  { source: 'page' | 'server', level, check, title, text } while state is 'confirming' (the dialog of the kit shows it)
//   restart.run(args)   the control was touched         restart.accept() / restart.cancel()   the answer to the dialog
//   restart.hold(true)  keyboard focus is on the armed control: the 5 s do not run       restart.reset()
//   restart.permission()  can(op): 'ok' | 'session' | 'role' | 'resolving' with its text (to lock the control and say why)
//
// Order, always: permission -> page confirmation -> call -> confirmation asked by the service (428) -> verification -> after.
// While it sends or verifies, a second touch does nothing: ONE request per action. A person who is not allowed never sees a dialog.

import Vue from 'vue'
import { call } from '../api/call.js'
import { ServiceError } from '../api/errors.js'
import { can, onSessionChange } from './session.js'
import { every, timeNow } from '../clock.js'
import { locale } from '../dwc.js'

export const ARM_MS = 5000
export const DONE_MS = 6000      // the outcome "done" leaves by itself after this (design guide 6.7)
const BUSY = ['sending', 'verifying', 'confirming']

const all = new Set()
const groups = new Map()        // group -> the action that holds it
let offSession = null

const asError = (e, op) => (e instanceof ServiceError ? e : new ServiceError({ op, code: 'internal', message: (e && e.message) || String(e), raw: e }))

function finish(x, state, error) {
	const a = x.a
	x.stopTimer()
	if (groups.get(x.group) === a) groups.delete(x.group)
	Object.assign(a, { state, error: error || null, confirm: null, armedUntil: 0 })
	if (state === 'done') x.timerUntil(DONE_MS, () => { if (a.state === 'done') a.state = 'idle' })
}

function denied(x, permission) {
	finish(x, 'error', new ServiceError({ op: x.o.op, code: permission.state === 'session' ? 'login_required' : 'forbidden', reason: permission.cause, message: permission.text }))
}

// the texts of a confirmation the service asks for (428): the ones of the language of the page
function serverConfirm(error) {
	const c = (error.extra && error.extra.confirm) || {}
	const texts = c.texts || {}
	const mine = texts[locale()] || texts.en || texts.es || {}
	return { source: 'server', level: c.level || 3, check: (c.level || 3) >= 4, key: c.key || '', title: mine.title || '', text: mine.text || error.message }
}

async function send(x, confirmed) {
	const a = x.a
	const mine = x.generation
	a.state = 'sending'
	a.confirm = null
	groups.set(x.group, a)
	let res
	try {
		res = await call(x.o.op, x.args, { confirm: confirmed })
	} catch (e) {
		if (mine !== x.generation) return
		const error = asError(e, x.o.op)
		if (error.kind === 'confirm' && !confirmed) {
			Object.assign(a, { state: 'confirming', confirm: serverConfirm(error) })
			return
		}
		return finish(x, error.kind === 'cancelled' ? 'idle' : 'error', error.kind === 'cancelled' ? null : error)
	}
	if (mine !== x.generation) return
	a.text = res.text
	a.data = res.data
	if (x.o.verify) return verify(x)
	return settle(x)
}

// the answer did not prove it: look at what the service publishes until it shows, or say that it could not be confirmed
function verify(x) {
	const a = x.a
	const mine = x.generation
	const until = x.o.verify.until
	const deadline = x.now() + (x.o.verify.timeoutMs || 10000)
	a.state = 'verifying'
	const check = () => {
		if (mine !== x.generation) return x.stopTimer()
		let ok = false
		try { ok = !!until(a.data, x.args) } catch (e) { ok = false }
		if (ok) return settle(x)
		if (x.now() >= deadline) finish(x, 'error', new ServiceError({ op: x.o.op, code: 'unverified', kind: 'failed', message: a.text || '' }))
	}
	check()
	if (a.state === 'verifying') x.timer(check)
}

async function settle(x) {
	const mine = x.generation
	try {
		const more = x.o.after ? x.o.after(x.a.data, x.args) : null
		if (more) await Promise.all([].concat(more))
	} catch (e) { /* the action itself was done: a failed reload shows in its own resource */ }
	if (mine === x.generation) finish(x, 'done')
}

function run(x, args) {
	const a = x.a
	if (BUSY.indexOf(a.state) >= 0) return
	const holder = groups.get(x.group)
	if (holder && holder !== a) return
	const permission = can(x.o.op, args ? { args } : undefined)
	if (permission.state === 'resolving') return
	if (!permission.allowed) return denied(x, permission)
	x.args = args || (x.o.args ? x.o.args() : {})
	const arm = (typeof x.o.arm === 'function' ? x.o.arm(x.args) : x.o.arm) || 'none'
	if (arm === 'double' && a.state !== 'armed') {
		Object.assign(a, { state: 'armed', error: null, armedUntil: x.now() + ARM_MS })
		x.timer(() => { if (a.state === 'armed' && !x.held && x.now() >= a.armedUntil) finish(x, 'idle') })
		return
	}
	x.stopTimer()
	a.error = null
	if (arm === 'dialog' || arm === 'dialog-check') {
		Object.assign(a, { state: 'confirming', confirm: { source: 'page', level: arm === 'dialog' ? 3 : 4, check: arm === 'dialog-check', key: x.o.op, title: '', text: '' } })
		groups.set(x.group, a)
		return
	}
	return send(x, false)
}

function reset(x) {
	x.generation += 1
	finish(x, 'idle')
	Object.assign(x.a, { text: '', data: null })
}

export function createAction(options) {
	const o = Object.assign({ arm: 'none' }, options || {})
	if (!o.op) throw new Error('createAction: op is required')
	const a = Vue.observable({ op: o.op, state: 'idle', error: null, text: '', data: null, confirm: null, armedUntil: 0 })
	const x = { a, o, group: o.group || o.op, generation: 0, args: {}, held: false, off: null, now: () => (o.now ? o.now() : timeNow()) }
	x.stopTimer = () => { if (x.off) { x.off(); x.off = null } }
	x.timer = fn => { x.stopTimer(); x.off = every(1, fn) }
	x.timerUntil = (ms, fn) => { const at = x.now() + ms; x.timer(() => { if (x.now() >= at) { x.stopTimer(); fn() } }) }
	a.run = args => run(x, args)
	a.accept = () => (a.state === 'confirming' ? send(x, a.confirm && a.confirm.source === 'server') : undefined)
	a.cancel = () => { if (a.state === 'confirming' || a.state === 'armed') finish(x, 'idle') }
	// keyboard focus on the armed control: the time does not run; it starts again when the focus leaves
	a.hold = on => {
		x.held = !!on
		if (!on && a.state === 'armed') a.armedUntil = x.now() + ARM_MS
	}
	a.reset = () => reset(x)
	a.permission = args => can(o.op, args ? { args } : undefined)
	a.busy = () => BUSY.indexOf(a.state) >= 0
	a.dispose = () => { reset(x); all.delete(x) }
	all.add(x)
	if (!offSession) offSession = onSessionChange(() => all.forEach(reset))   // what was in the air belonged to the person who left
	return a
}

export function actionCount() {
	return all.size
}
