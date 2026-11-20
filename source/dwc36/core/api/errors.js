'use strict'

// ONE error for every way the service can say no (core/api/call.js throws nothing else).
//
//   ServiceError { op, kind, code, reason, field, message, key, params, status, body, raw, extra }
//     kind      what a screen does with it (table below): session | credentials | locked | role | damaged | confirm | validation |
//               conflict | blocked | rejected | unavailable | failed | cancelled
//     code      the code of the service (error.code), 'rejected' for a refusal that came with HTTP 200, 'unavailable' when nothing answered
//     reason    error.reason when the service gives one (forbidden: role, mode ...; failed: exists, last_admin ...)
//     field     the argument at fault, when the service names it
//     message   the sentence of the service, already in the language the page asked for
//     key/params  an i18n key of the page that says it better, when there is one (403 of workshop-api.js)
//     status    HTTP status ; body: the whole answer ; extra: the other fields of error (confirm, current, reasons, wait_s, errors ...)
//   kindOf(code, reason)        the kind of a code
//   fromApiError(e, op)         the ApiError of workshop-api.js -> ServiceError
//   rejected(op, message, raw)  a refusal that arrived inside a 200 answer (shapes.js)
//
// The family pieces that paint an error (friendly-error.js, ErrorNotice.vue) read code / status / body / message: a ServiceError keeps them.

// code -> kind. A code that is not here is 'failed' (the sentence of the service is shown as it is).
export const KINDS = Object.freeze({
	login_required: 'session', auth_required: 'session',
	bad_credentials: 'credentials',
	locked: 'locked',
	forbidden: 'role',
	damaged: 'damaged',
	confirm_required: 'confirm',
	cancelled: 'cancelled',
	invalid_args: 'validation', bad_request: 'validation', pin_policy: 'validation', invalid_name: 'validation', invalid_profile: 'validation',
	reserved_name: 'validation', unknown_entry: 'validation', too_big: 'validation', not_found: 'validation', unknown_op: 'validation',
	conflict: 'conflict', in_use: 'conflict', already: 'conflict', self_change: 'conflict', lockout: 'conflict',
	motion_denied: 'blocked', interlock_open: 'blocked', busy: 'blocked', refused: 'blocked',
	rejected: 'rejected',
	unavailable: 'unavailable', service_outdated: 'unavailable',
	failed: 'failed', internal: 'failed', not_implemented: 'failed', error: 'failed'
})

// `failed` with one of these reasons is a conflict with what exists (people, roles), not a breakdown
const FAILED_AS_CONFLICT = ['exists', 'last_admin', 'self_demote', 'too_many', 'in_use', 'missing', 'not_found', 'role_in_use', 'unknown_role']

export function kindOf(code, reason) {
	if (code === 'forbidden' && reason === 'damaged') return 'damaged'
	if (code === 'failed' && FAILED_AS_CONFLICT.indexOf(reason) >= 0) return 'conflict'
	return Object.prototype.hasOwnProperty.call(KINDS, code) ? KINDS[code] : 'failed'
}

export class ServiceError extends Error {
	constructor(fields) {
		const f = fields || {}
		super(f.message || f.code || 'error')
		this.name = 'ServiceError'
		this.op = f.op || ''
		this.code = f.code || 'error'
		this.reason = f.reason || ''
		this.kind = f.kind || kindOf(this.code, this.reason)
		this.field = f.field || ''
		this.key = f.key || ''
		this.params = f.params || null
		this.status = f.status || 0
		this.body = f.body || null
		this.raw = f.raw === undefined ? null : f.raw
		this.extra = f.extra || {}
	}

	// the person can try the same thing again and it may work (nothing answered, the service was busy)
	get retryable() {
		return this.kind === 'unavailable' || this.code === 'busy'
	}
}

const OWN = ['code', 'message', 'reason', 'field']

export function fromApiError(e, op) {
	if (e instanceof ServiceError) return e
	const body = (e && e.body) || null
	const err = (body && body.error) || {}
	const extra = {}
	Object.keys(err).forEach(k => { if (OWN.indexOf(k) < 0) extra[k] = err[k] })
	const code = (e && e.code) || err.code || 'error'
	return new ServiceError({
		op, code, reason: (e && e.reason) || err.reason || '', field: err.field || '',
		message: (e && e.message) || err.message || code, key: (e && e.key) || '', params: (e && e.params) || null,
		status: (e && e.status) || 0, body, raw: body, extra
	})
}

export function rejected(op, message, raw, code) {
	return new ServiceError({ op, code: 'rejected', kind: 'rejected', reason: code || '', message: message || 'rejected', status: 200, raw: raw === undefined ? null : raw })
}
