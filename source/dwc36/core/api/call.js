'use strict'

// The ONE door of the new page to the API of the service.
//
//   const { data, text } = await call('users.list')                 // data: the result object (or null), text: the sentence (or '')
//   await call('users.add', { name, pin, role })                    // throws ServiceError (core/api/errors.js), nothing else
//   await call('service.restart', {}, { confirm: true })            // the page already asked (core/store/action.js shows the dialog)
//
// The transport is api() of workshop-api.js (family twin): session headers, language, origin, the retries while the service restarts,
// the repeat after a sign-in and the 403 notice. What this adds:
//   * one shape of success: { data, text } (the twin resolves "result or else message");
//   * one shape of failure: the refusals that arrive with HTTP 200 (shapes.js) are thrown like every other error;
//   * the confirmation dialog of the twin is never opened from here (noDialog): a 428 comes back as a ServiceError of kind 'confirm'
//     with error.extra.confirm, and the action decides what to show.
//   * while the twin retries a call (the service does not answer) the page says so: pageState.retry = { n, total }, cleared when the
//     call ends; when it gives up the sentence is the page's own ("the service does not answer"), with the code of the twin;
//   * a call refused for lack of a session tells whoever listens (onSessionLost): the session mirror asks the service again, so the
//     chip changes and the background reads stop at the FIRST 401, not at the tenth.
// Options passed on to the twin: confirm, quiet (a background read), noLogin, onRetry(n, total), origin.

import { api } from '../../workshop-api.js'
import { fromApiError, rejected, ServiceError } from './errors.js'
import { refusalIn, split } from './shapes.js'
import { pageState } from '../page-state.js'
import { t } from '../dwc.js'

let transport = api
let sessionLost = null
const retrying = new Set()

// fn(error) is called when a call came back without a session; returns the function that stops listening
export function onSessionLost(fn) {
	sessionLost = fn
	return () => { if (sessionLost === fn) sessionLost = null }
}

// tests and the page harness replace the transport: fn(op, args, opts) -> what api() resolves, or throws what api() throws
export function setTransport(fn) {
	transport = fn || api
}

export async function call(op, args, opts) {
	const o = Object.assign({}, opts || {}, { noDialog: true })
	const mine = {}
	const told = o.onRetry
	o.onRetry = (n, total) => {
		retrying.add(mine)
		pageState.retry = { n, total }
		if (typeof told === 'function') told(n, total)
	}
	let value
	try {
		value = await transport(op, args || {}, o)
	} catch (e) {
		const error = e instanceof ServiceError ? e : fromApiError(e, op)
		if (error.kind === 'session' && sessionLost) { try { sessionLost(error) } catch (x) { /* the call fails with its own error */ } }
		if (error.code === 'unavailable') error.message = t('shell.no_answer')
		throw error
	} finally {
		if (retrying.delete(mine) && !retrying.size) pageState.retry = null
	}
	const refusal = refusalIn(op, value)
	if (refusal) throw rejected(op, refusal.message, value, refusal.code)
	return split(op, value)
}

// a read that may fail without anybody being told (background refresh): never asks to sign in, never raises a toast
export function quietCall(op, args, opts) {
	return call(op, args, Object.assign({ quiet: true, noLogin: true }, opts || {}))
}
