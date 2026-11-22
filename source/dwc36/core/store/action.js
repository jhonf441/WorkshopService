'use strict'

// One thing a person does = one action = one control. A THIN LAYER over the shared state machine of the family (workshop-action.js): the machine owns
// the states, the double touch, the dialog, the one-write-per-group rule, the verification and the clock; this file only brings what is the SERVICE's:
// the call (`call(op, args, { confirm })`), the permission (`can(op)`), the confirmation the service asks for (428) with its own texts, the group that
// defaults to the operation, the errors as `ServiceError` and the forgetting of what a person who left had started.
//
//   const restart = createAction({
//     op: 'service.restart',                       the operation (also what the permission is asked for)
//     args: () => ({}),                            optional: the arguments when run() is called without them
//     arm: 'double',                               page confirmation: 'none' | 'double' (second touch within 4 s) | 'dialog' | 'dialog-check';
//                                                  or a function of the arguments (arming asks, disarming does not)
//     verify: { until: () => bool, timeoutMs },    for answers that prove nothing: wait until the published data shows it
//     after: () => [users.reload()],               what to read again once it is done
//     group: 'machine'                             one write at a time per group (default: the operation name)
//   })
//   restart.state    'idle' | 'armed' | 'confirming' | 'sending' | 'verifying' | 'done' | 'error'
//   restart.error    ServiceError | null        restart.text / restart.data   what the service answered
//   restart.confirm  { level, check, title, text } while state is 'confirming' (WfConfirm shows it)
//   restart.run(args)   the control was touched         restart.accept() / restart.cancel()   the answer to the dialog
//   restart.hold(true)  keyboard focus is on the armed control: the 4 s do not run       restart.reset()
//   restart.permission()  can(op): 'ok' | 'session' | 'role' | 'resolving' with its text (to lock the control and say why)
//
// Order, always: permission -> page confirmation -> call -> confirmation asked by the service (428) -> verification -> after.
// While it sends or verifies, a second touch does nothing: ONE request per action. A person who is not allowed never sees a dialog.
//
// Asked of the shared machine (to drop the two workarounds below): a hook `onServerConfirm` for the answer 428, and `permission` able to return the error itself.

import { call } from '../api/call.js'
import { ServiceError } from '../api/errors.js'
import { can, onSessionChange } from './session.js'
import { every, timeNow } from '../clock.js'
import { locale } from '../dwc.js'
import { ARM_MS } from '../../arm-ms.js'
import { createAction as createSharedAction, WF_DONE_WINDOW } from '../../workshop-action.js'

export { ARM_MS }
export const DONE_MS = WF_DONE_WINDOW      // the outcome "done" leaves by itself after this (design guide 6.7)

const all = new Set()
let offSession = null

const asError = (e, op) => (e instanceof ServiceError ? e : new ServiceError({ op, code: 'internal', message: (e && e.message) || String(e), raw: e }))

// the shared machine asks a clock for one-shot timers; the service has ONE clock (core/clock.js: every second, replaceable by a test)
const clock = {
	now: () => timeNow(),
	set(fn, ms) {
		const at = timeNow() + ms
		const off = every(1, () => { if (timeNow() >= at) { off(); fn() } })
		return off
	},
	clear: off => { if (typeof off === 'function') off() }
}

// the texts of a confirmation the service asks for (428): the ones of the language of the page
function serverConfirm(error) {
	const c = (error.extra && error.extra.confirm) || {}
	const texts = c.texts || {}
	const mine = texts[locale()] || texts.en || texts.es || {}
	return { source: 'server', level: c.level || 3, check: (c.level || 3) >= 4, key: c.key || '', title: mine.title || '', text: mine.text || error.message }
}

export function createAction(options) {
	const o = Object.assign({ arm: 'none' }, options || {})
	if (!o.op) throw new Error('createAction: op is required')
	let args = {}
	let asked = false      // the person is answering a question the SERVICE asked: the call goes again with confirm
	const arm = a => (typeof o.arm === 'function' ? o.arm(a) : o.arm) || 'none'
	const inner = createSharedAction({
		clock,
		group: o.group || o.op,
		arm: a => (arm(a) === 'double' ? 'double' : 'none'),
		confirm: a => { const m = arm(a); return m === 'dialog' || m === 'dialog-check' ? { source: 'page', level: m === 'dialog' ? 3 : 4, check: m === 'dialog-check', key: o.op, title: '', text: '' } : null },
		verify: o.verify ? { until: o.verify.until, timeoutMs: o.verify.timeoutMs || 10000, everyMs: 1000 } : undefined,
		after: o.after,
		run: async (a, ctx) => {
			const confirm = !!ctx.confirmed && asked
			asked = false
			try {
				return await call(o.op, a, { confirm })
			} catch (e) {
				const error = asError(e, o.op)
				if (error.kind === 'confirm' && !confirm) {
					// the service wants a question first: the action waits in 'confirming' (workaround: the machine has no hook for it, so this call never answers)
					asked = true
					Object.assign(inner, { state: 'confirming', error: null, confirm: serverConfirm(error) })
					return new Promise(() => {})
				}
				throw error.kind === 'cancelled' ? Object.assign(error, { cancelled: true }) : error
			}
		}
	})
	const a = Object.assign(inner, { op: o.op })
	a.permission = pargs => can(o.op, pargs ? { args: pargs } : undefined)
	const shared = { run: inner.run, reset: inner.reset, accept: inner.accept }
	a.run = pargs => {
		if (a.busy()) return undefined
		const p = a.permission(pargs)
		if (p.state === 'resolving') return undefined
		if (!p.allowed) {
			// workaround: the machine builds its own refusal; the service's carries the cause (reason) and the sentence of the lock
			a.reset()
			Object.assign(a, { state: 'error', error: new ServiceError({ op: o.op, code: p.state === 'session' ? 'login_required' : 'forbidden', reason: p.cause, message: p.text }) })
			return undefined
		}
		args = pargs || (o.args ? o.args() : {})
		return shared.run(args)
	}
	a.dispose = () => { a.reset(); all.delete(a) }
	all.add(a)
	if (!offSession) offSession = onSessionChange(() => all.forEach(x => x.reset()))   // what was in the air belonged to the person who left
	return a
}

export function actionCount() {
	return all.size
}
