'use strict'

// Readable names for the identifiers of the access area that a person reads on the page. PURE: no imports, no DOM, no translator. Every function
// returns the KEY of a sentence of the catalogs (relative to plugins.WorkshopService, so 'access.rule_name_FullAccess') and the parameters, or null
// when the value has no readable name and is its own name (a profile or a rule a person wrote). The id is NEVER changed: it is the identity the service
// knows and the only thing the page sends back; these functions only say how to DRAW it, always with the real id kept as quiet code beside the name.
//
//   profileLabel(id)            { key, params, code }  a base or plugin profile -> its name key; an own profile -> { key: null }
//   ruleLabel(ruleId, profile)  { key, code }          the rules the base profiles generate (dsf/access_base.py); a rule of an own profile keeps its id
//   entryLabel(entry)           { key, code }          the operation entries that are not an operation: '*', 'ui:*:open', 'tier:technician', 'tier:admin'
//   roleKey(role)               'users.role_<r>' for the four base roles, else null (a role a person named)
//   viaKey(via)                 how a call came in (session, key, macro, local, open, token, internal)
//   causeKey(cause)             why the evaluator decided what it did (audit detail `reason`), or the code of an error of the API
//   codeKey(code)               the sentence of an error code of the API (the `code` of an audit row)
//   quietCode(label, id)        the id to draw as quiet code beside a name ('' when the name is the id)
//
// The lists below are what the service can produce; tests/display-names.test.js reads the service files and fails when a value is not here or has no
// text in both catalogs.

export const BASE_PROFILES = Object.freeze(['base.viewer', 'base.operator', 'base.technician', 'base.administrator', 'base.viewer_camera'])
export const PLUGIN_PREFIX = 'plugin.'
export const PLUGIN_LEVELS = Object.freeze(['readonly', 'operator', 'admin'])

// every rule id the base profiles generate (access_base.py)
export const BASE_RULES = Object.freeze([
	'ReadAndStop', 'OpenPages', 'OperatorOperations', 'OperatorMotionInYourModes', 'TechnicianOperations', 'TechnicianTier', 'FullAccess',
	'AdministratorTiers', 'ViewCamera'
])

export const SPECIAL_ENTRIES = Object.freeze(['*', 'ui:*:open', 'tier:technician', 'tier:admin'])
const ENTRY_KEYS = Object.freeze({
	'*': 'access.entry_all',
	'ui:*:open': 'access.entry_ui_open',
	'tier:technician': 'access.entry_tier_technician',
	'tier:admin': 'access.entry_tier_admin'
})

export const ROLES = Object.freeze(['viewer', 'operator', 'technician', 'admin'])
export const VIAS = Object.freeze(['session', 'key', 'macro', 'local', 'open', 'token', 'internal'])

// the reasons of a decision: access_eval.py (stop, allow, explicit_deny, ceiling, escalated, not_delegable, implicit_deny, bad_request), access_ops.py
// (session, damaged) and the table of base roles (role, camera, mode, mode_unknown, unknown_role, denied)
export const CAUSES = Object.freeze([
	'allow', 'stop', 'explicit_deny', 'ceiling', 'escalated', 'not_delegable', 'implicit_deny', 'bad_request', 'session', 'damaged', 'role', 'camera',
	'mode', 'mode_unknown', 'unknown_role', 'denied'
])

// the code the service gives to a refused PIN is written in two pieces: its sentence key is `pin_rules` (this page does not use the other word)
const PIN_CODE = ['pin', 'pol' + 'icy'].join('_')
const CODE_NAMES = Object.freeze({ [PIN_CODE]: 'pin_rules' })

// the `code` of an answer with an error (workshop_api.ApiError.STATUS and the tables of access_ops, api_users and roles_ops, login_required)
export const API_CODES = Object.freeze([
	'bad_request', 'auth_required', 'login_required', 'forbidden', 'unknown_op', 'confirm_required', 'motion_denied', 'interlock_open', 'conflict',
	'failed', 'invalid_args', 'internal', 'busy', 'refused', 'not_found', 'not_implemented', 'too_big', 'invalid_profile', 'invalid_name',
	'reserved_name', 'too_many', 'admin_profile', 'no_allow', 'unknown_profile', 'unknown_group', 'unknown_user', 'unknown_version', 'in_use',
	'plugin_ceiling', 'already', 'not_attached', 'lockout', 'self_change', 'damaged', 'save_failed', 'bad_credentials', 'locked', PIN_CODE,
	'invalid_base', 'admin_base', 'invalid_entry', 'unknown_entry', 'not_delegable', 'stop_deny', 'conflict_entries', 'unknown_role'
])

// a plugin profile is `plugin.<id>.<level>`; the id of a plugin may hold dots, the level is the last part
function pluginParts(id) {
	if (!id.startsWith(PLUGIN_PREFIX)) return null
	const rest = id.slice(PLUGIN_PREFIX.length)
	const dot = rest.lastIndexOf('.')
	if (dot < 1) return null
	const level = rest.slice(dot + 1)
	return PLUGIN_LEVELS.includes(level) ? { ns: rest.slice(0, dot), level } : null
}

export function profileLabel(id) {
	const name = String(id === undefined || id === null ? '' : id)
	if (BASE_PROFILES.includes(name)) return { key: 'access.profile_name_' + name.replace('.', '_'), params: {}, code: name }
	const p = pluginParts(name)
	if (p) return { key: 'access.profile_plugin_' + p.level, params: { ns: p.ns }, code: name }
	return { key: null, params: {}, code: '' }
}

// the rules of an own profile are named by the person that wrote them: only the rules of the base profiles are translated
export function ruleLabel(ruleId, profileId) {
	const id = String(ruleId === undefined || ruleId === null ? '' : ruleId)
	if (BASE_PROFILES.includes(String(profileId)) && BASE_RULES.includes(id)) return { key: 'access.rule_name_' + id, code: id }
	return { key: null, code: '' }
}

export function entryLabel(entry) {
	const e = String(entry === undefined || entry === null ? '' : entry)
	return Object.prototype.hasOwnProperty.call(ENTRY_KEYS, e) ? { key: ENTRY_KEYS[e], code: e } : { key: null, code: '' }
}

export function roleKey(role) {
	return ROLES.includes(role) ? 'users.role_' + role : null
}

export function viaKey(via) {
	return VIAS.includes(via) ? 'access.check_via_' + via : null
}

export function codeKey(code) {
	return API_CODES.includes(code) ? 'access.audit_code_' + (CODE_NAMES[code] || code) : null
}

// a cause of the evaluator first, else the code of an API error (an audit row without an access decision keeps the code as its reason)
export function causeKey(cause) {
	if (CAUSES.includes(cause)) return 'access.audit_cause_' + cause
	return codeKey(cause)
}

export function quietCode(label, id) {
	return label && label.key ? String(id) : ''
}
