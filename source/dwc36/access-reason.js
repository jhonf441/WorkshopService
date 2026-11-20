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
//   conditionOfReason(reason, live) the phrase of the condition that failed (the service gives its key, not its value)
//   entryOfAnswer / groupFromAnswers  an answer of auth.can -> the entry / the one sentence of a group of operations
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
	session: 'session',
	unknown_role: 'role',
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

// The condition that did not hold, as the phrase that names it. The service says WHICH condition failed (failed_conditions), not what the rule asks for:
// a yes/no condition is named exactly only when the page tells the live value (live: { job_running, machine_on }: the rule wants the opposite), else the
// phrase says the condition without the value (cond_any_*). The legacy refusals by mode (code mode, mode_unknown) name the mode condition.
const ANY_CONDITION = Object.freeze({ mode: 'cond_any_mode', job_running: 'cond_any_job', machine_on: 'cond_any_machine', via: 'cond_any_via', risk_max: 'cond_any_risk' })

export function conditionOfReason(reason, live) {
	const r = reason || {}
	const failed = Array.isArray(r.failed_conditions) ? r.failed_conditions : []
	const key = failed.length ? failed[0] : r.code === 'mode' || r.code === 'mode_unknown' ? 'mode' : ''
	if (!ANY_CONDITION[key]) return null
	const l = live || {}
	if ((key === 'job_running' || key === 'machine_on') && typeof l[key] === 'boolean') return conditionPhrase(key, !l[key])
	return { key: ANY_CONDITION[key], params: {} }
}

function ruleOf(r) {
	return r.rule !== undefined && r.rule !== null ? r.rule : r.id !== undefined && r.id !== null ? r.id : ''
}

function paramsOf(cause, reason, extra) {
	const r = reason || {}
	const x = extra || {}
	if (cause === 'profile') return { profile: r.profile || '', rule: ruleOf(r) }
	if (cause === 'ceiling') return { ceiling: r.ceiling || r.profile || '' }
	if (cause === 'role') return { needed: x.needed || r.needed_role || '', role: x.role || '' }
	if (cause === 'condition') return { condition: x.condition || '' }
	return {}
}

function isStop(op, stopOps) {
	return (stopOps || STOP_OPS).indexOf(op) >= 0
}

const NONE = Object.freeze({ show: false, key: '', cause: '', params: {}, unknown: false, nested: null })

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
	if (cause === 'unknown') return { show: true, key: UNKNOWN_KEY, cause, params: {}, unknown: true, nested: null }
	const params = paramsOf(cause, e.reason, e)
	let key = BLOCK_KEYS[cause]
	let nested = null
	if (cause === 'profile' && !params.profile) {
		key = ROLE_DENIED_KEY // a custom role (not a profile) denies it: no profile to name
		params.role = e.roleName || ''
	} else if (cause === 'profile' && params.rule === '') key = PROFILE_ONLY_KEY
	if (cause === 'condition') {
		const c = e.conditionPhrase || conditionOfReason(e.reason, e.live)
		nested = c ? { param: 'condition', key: c.key, params: c.params } : null
		if (!nested) return { show: true, key: UNKNOWN_KEY, cause: 'unknown', params: {}, unknown: true, nested: null }
	}
	return { show: true, key, cause, params, unknown: false, nested }
}

// How the causes that only a profile-aware answer can give are drawn (the cause color of family.css: neutral gray, a condition is the orange of a wait)
export const CAUSE_LOOK = Object.freeze({
	profile: { css: 'role', icon: 'mdi-lock-outline' },
	ceiling: { css: 'role', icon: 'mdi-lock-outline' },
	no_rule: { css: 'role', icon: 'mdi-lock-outline' },
	not_delegable: { css: 'role', icon: 'mdi-shield-lock-outline' },
	surface: { css: 'role', icon: 'mdi-lock-outline' },
	unknown: { css: 'role', icon: 'mdi-lock-outline' },
	condition: { css: 'down', icon: 'mdi-timer-sand' }
})

// The sentence of a profile that denies without naming a rule, and of a custom role that denies (no profile): keys of the catalogs
export const PROFILE_ONLY_KEY = 'block_profile_only'
export const ROLE_DENIED_KEY = 'notice_role_denied'

// The page of a plugin (ui:<plugin>:open) refused: the cause is the surface, whatever the base role says
const SURFACE_OP = /^ui:[a-z0-9_]+:open$/

// One answer of auth.can ({ allowed, reason }) for one operation of a screen -> the entry of blockReason.
//   extra: { hasControl, roleName, live, target }; the entry is disabled by permissions exactly when the service said no.
export function entryOfAnswer(op, answer, extra) {
	const a = answer || {}
	const e = Object.assign({ op, hasControl: true, allowed: a.allowed === true, disabledByPermission: a.allowed === false, reason: a.reason || null }, extra || {})
	if (a.allowed === false && SURFACE_OP.test(op)) e.cause = 'surface'
	return e
}

// Several operations of ONE group of buttons, each with its answer (answerOf(op) -> the answer or null when not asked yet):
// { show, key, cause, params, unknown, nested, answered } ; answered = every operation of the group has an answer (so nothing else decides)
export function groupFromAnswers(ops, answerOf, extra, options) {
	const items = []
	let answered = true
	;(ops || []).forEach(op => {
		const a = answerOf(op)
		if (!a || typeof a.allowed !== 'boolean') {
			answered = false
			return
		}
		items.push(entryOfAnswer(op, a, extra))
	})
	return Object.assign({}, groupReason(items, options), { answered })
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
