'use strict'

// How each operation answers. The envelope of the API says ok true for three different things (annex B 0.2 of the redesign):
//
//   object      result is the data (the typed operations): nothing to do. The default for an operation that is not listed.
//   okflag      HTTP 200 with result { ok: false, error: '<sentence>' } when the service refuses (old handlers that answer JSON)
//   errorfield  HTTP 200 with result { error: '<sentence>' } when it refuses
//   text        result is null and message is a sentence, for a success AND for a refusal: the answer proves nothing, the action
//               that calls it checks the published data afterwards (createAction `verify`)
//
// An entry is an operation name or a prefix that ends in '.' ; the longest match wins. tests/core-api.test.js checks that every
// entry names operations of dsf/golden/api_contract.json, and the integration test runs them against the real service.

export const SHAPES = Object.freeze({
	'processes.': 'okflag',
	'modules.set': 'okflag',
	'db.': 'okflag',
	'bridge.service.set': 'okflag',
	'config.': 'okflag',
	'examples.': 'okflag',
	'bridge.test': 'errorfield',
	'history.': 'errorfield',
	'activity.': 'errorfield',
	'notifications.': 'errorfield',
	'movement.lock': 'text',
	'power.after_job': 'text',
	'power.timer': 'text',
	'power.timer_cancel': 'text',
	'air.': 'text',
	'job.close': 'text',
	'blackbox.show': 'text',
	'blackbox.hide': 'text',
	'camera.start': 'text',
	'camera.stop': 'text',
	'comms.get': 'text',
	// a refusal of these three is an error of the envelope since the backend changes CB-1 and CB-2; the sentence of a success is shown
	'comms.set': 'text',
	'password.set': 'text',
	'password.clear': 'text'
})

export function shapeOf(op) {
	const name = String(op || '')
	if (Object.prototype.hasOwnProperty.call(SHAPES, name)) return SHAPES[name]
	let best = ''
	Object.keys(SHAPES).forEach(k => { if (k[k.length - 1] === '.' && name.indexOf(k) === 0 && k.length > best.length) best = k })
	return best ? SHAPES[best] : 'object'
}

const isObject = v => !!v && typeof v === 'object' && !Array.isArray(v)

// The refusal hidden in a 200 answer: { message, code } or null. `value` is what api() of workshop-api.js resolved (result, else message).
export function refusalIn(op, value) {
	const shape = shapeOf(op)
	if (!isObject(value)) return null
	if (shape === 'okflag' && value.ok === false) return { message: textOf(value.error) || textOf(value.message), code: codeOf(value.error) }
	if (shape === 'errorfield' && value.error) return { message: textOf(value.error), code: codeOf(value.error) }
	return null
}

// { data, text }: what a caller gets. A sentence is never data and an object is never a sentence.
export function split(op, value) {
	if (value === null || value === undefined) return { data: null, text: '' }
	if (typeof value === 'string') return { data: null, text: value }
	return { data: value, text: isObject(value) && typeof value.message === 'string' ? value.message : '' }
}

function textOf(v) {
	if (typeof v === 'string') return v
	if (isObject(v) && typeof v.message === 'string') return v.message
	return v === null || v === undefined ? '' : String(v)
}

// a refusal written as a short code ("unknown_process") is kept as the reason, so a screen can choose its own words
function codeOf(v) {
	return typeof v === 'string' && /^[a-z][a-z0-9_]{2,40}$/.test(v) ? v : ''
}
