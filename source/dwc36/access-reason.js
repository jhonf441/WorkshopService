'use strict'

// Why a control is locked, told by CAUSE (DISENO-PANTALLAS sections 3.2 and 3.3). Pure: no store, no identity, no translator; the page that
// draws the sentence passes what it knows and gets back the key of the sentence and its parameters.
//
//   CAUSES                         the nine causes in their FIXED order: when several apply, the first one is the one shown
//   BLOCK_KEYS                     cause -> key of the sentence in the area `access` of the catalogs (the `down` cause keeps today's sentence)
//   causeOfDecision(reason)        the cause of an answer of the service: the `reason` of access.check ({code, profile, id, ceiling, failed_conditions})
//                                  or the legacy reason of the base roles ('role', 'mode', 'mode_unknown', 'camera', 'denied', 'ceiling'); '' = nothing blocks
//   firstCause(list)               the cause of the list that comes first in CAUSES
//   conditionPhrase(key, want)     the key and the parameters of the phrase that names a condition ("the machine is in fff mode")
//   blockReason(entry, options)    the four-condition rule for ONE control or group of controls: { show, key, cause, params, unknown }
//   groupReason(items, options)    ONE sentence for a group of controls: the first cause that applies among the operations that are denied
//
// The sentence is drawn if and only if all four hold: (1) the person has the control in view, (2) it is disabled by PERMISSIONS (the machine state
// has its own written reason), (3) the cause is known (else `block_unknown`, and `unknown` tells the caller to write it to the console), (4) the
// operation is not a stop: STOP_OPS never carry a sentence and are never disabled. An allowed operation draws nothing.

// The stop operations of the service (dsf/permissions.py STOP_OPS): a test compares this list with the file, so the two cannot drift.
export const STOP_OPS = Object.freeze([
	'bedcal.stop', 'bedzones.off', 'frame.stop', 'jog.stop_axis', 'jog.stop_xy', 'jog.stop_z', 'layerrecipes.disarm', 'livejob.stop_safe',
	'machine.stop', 'pelletlayers.disarm', 'pid.cancel', 'power.off'
])

export const CAUSES = Object.freeze(['session', 'down', 'surface', 'profile', 'ceiling', 'no_rule', 'role', 'not_delegable', 'condition'])

export const UNKNOWN_KEY = 'block_unknown'

// explicit keys (not built at run time) so the i18n checks can see that each one is used
export const BLOCK_KEYS = Object.freeze({
	session: 'block_session',
	down: 'block_down',
	surface: 'block_plugin',
	profile: 'block_profile',
	ceiling: 'block_ceiling',
	no_rule: 'block_no_rule',
	role: 'block_role',
	not_delegable: 'block_admin_only',
	condition: 'block_condition'
})

// The code of a decision (access_eval.py, access_person.py) or of a legacy reason (permissions.decide) -> cause. '' = nothing blocks (allowed).
const CAUSE_OF_CODE = Object.freeze({
	stop: '',
	allow: '',
	'': '',
	explicit_deny: 'profile',
	denied: 'profile',
	ceiling: 'ceiling',
	not_delegable: 'not_delegable',
	escalated: 'role',
	role: 'role',
	camera: 'role',
	mode: 'condition',
	mode_unknown: 'condition',
	signed_out: 'session',
	login_required: 'session',
	unavailable: 'down',
	service_down: 'down',
	surface: 'surface'
})

// `reason` may be null (the service gave none): that is an unknown cause, not an allowed call
export function causeOfDecision(reason) {
	if (!reason || typeof reason !== 'object') return 'unknown'
	const code = String(reason.code === undefined || reason.code === null ? '' : reason.code)
	if (code === 'implicit_deny') {
		const failed = Array.isArray(reason.failed_conditions) ? reason.failed_conditions : []
		return failed.length ? 'condition' : 'no_rule'
	}
	return Object.prototype.hasOwnProperty.call(CAUSE_OF_CODE, code) ? CAUSE_OF_CODE[code] : 'unknown'
}

export function firstCause(list) {
	let best = ''
	let bestAt = CAUSES.length
	;(list || []).forEach(c => {
		const at = CAUSES.indexOf(c)
		if (at >= 0 && at < bestAt) {
			best = c
			bestAt = at
		}
	})
	return best
}

// A condition of a rule that did not hold (access_profile.CONDITION_KEYS) -> the phrase that names it. `want` is what the rule asks for.
export function conditionPhrase(key, want) {
	const list = Array.isArray(want) ? want : [want]
	if (key === 'mode') return { key: 'cond_mode', params: { mode: list.join(' / ') } }
	if (key === 'job_running') return { key: want === false ? 'cond_job_off' : 'cond_job_on', params: {} }
	if (key === 'machine_on') return { key: want === false ? 'cond_machine_off' : 'cond_machine_on', params: {} }
	if (key === 'via') return { key: 'cond_via', params: { via: list.join(' / ') } }
	if (key === 'risk_max') return { key: 'cond_risk', params: { n: want } }
	return null
}

function paramsOf(cause, reason, extra) {
	const r = reason || {}
	const x = extra || {}
	if (cause === 'profile') return { profile: r.profile || '', rule: r.id || '' }
	if (cause === 'ceiling') return { ceiling: r.ceiling || r.profile || '' }
	if (cause === 'role') return { needed: x.needed || '', role: x.role || '' }
	if (cause === 'condition') return { condition: x.condition || '' }
	return {}
}

function isStop(op, stopOps) {
	return (stopOps || STOP_OPS).indexOf(op) >= 0
}

const NONE = Object.freeze({ show: false, key: '', cause: '', params: {}, unknown: false })

// entry: { op, hasControl, disabledByPermission, allowed, cause | reason, ...params }
//   hasControl            (1) the control, or group of controls, is on the screen
//   disabledByPermission  (2) it is disabled because the service would say no to this person now (false: the machine state disables it)
//   cause | reason        (3) a cause of CAUSES, or the `reason` of an answer of the service (causeOfDecision); neither or an unknown one = block_unknown
//   allowed               true = the person may: nothing is drawn
// options: { stopOps }
export function blockReason(entry, options) {
	const e = entry || {}
	if (e.hasControl === false) return NONE
	if (e.allowed === true) return NONE
	if (e.disabledByPermission !== true) return NONE
	if (isStop(e.op, options && options.stopOps)) return NONE
	let cause = e.cause !== undefined && e.cause !== null ? e.cause : causeOfDecision(e.reason)
	if (cause === '') return NONE
	if (CAUSES.indexOf(cause) < 0) cause = 'unknown'
	if (cause === 'unknown') return { show: true, key: UNKNOWN_KEY, cause, params: {}, unknown: true }
	return { show: true, key: BLOCK_KEYS[cause], cause, params: paramsOf(cause, e.reason, e), unknown: false }
}

// items: the operations of ONE group of buttons, each one an entry of blockReason (hasControl and disabledByPermission may be set once in
// options.common). One sentence for the whole group: the first cause that applies, in the order of CAUSES; with the same cause, the first operation.
// Stop operations are left out of the group (they are never locked); a group of only stop operations draws nothing.
export function groupReason(items, options) {
	const common = (options && options.common) || {}
	const shown = []
	;(items || []).forEach(it => {
		const r = blockReason(Object.assign({}, common, it), options)
		if (r.show) shown.push(r)
	})
	if (!shown.length) return NONE
	const known = shown.filter(r => !r.unknown)
	if (!known.length) return shown[0]
	const cause = firstCause(known.map(r => r.cause))
	return known.find(r => r.cause === cause)
}
