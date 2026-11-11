'use strict'

// The CAUSE of a notice and its sentence (ESTANDAR 2: one cause, one color, one sentence). Pure logic: the translator is passed in, so
// tests/notice-standard.test.js loads this file in node.
//
//   noticeKindOf({ reason, serviceDown, error })   'session' | 'role' | 'down' | 'error' | ''
//                                                  reason = what accessReason() of workshop-auth.js answers ('signed_out' | 'role' | '')
//   noticeText(kind, { needed, role, state, action }, t)  the one sentence of that cause; needed / role are role ids ('operator', ...); action = what was
//                                                  refused, already translated ("Saving the zones"): the 403 sentence then names it (notice_role_action)
//   roleLabel(role, t)                             "Operador", "Técnico"... (the lockrole_* texts)
//   noticeActionOf(kind, variant, act)             the button of a notice: 'sign-in' | 'change-role' | 'retry' | '' (act = what the page asked, null = the default)
//   NOTICE_ICONS                                   the mdi icon of each cause
//   NOTICE_COLORS                                  the semantic color token of each cause (family.css --wf-c-<color>, SESSION-TOKENS.md)

export const NOTICE_ICONS = {
	session: 'mdi-account-lock-outline',
	role: 'mdi-lock-outline',
	down: 'mdi-power-plug-off-outline',
	error: 'mdi-alert-circle-outline',
	empty: 'mdi-information-outline',
	resolving: 'mdi-timer-sand'
}

// ONE color per meaning (the --wf-c-* tokens of family.css): a person who must sign in is blue, one without permission is gray, a wait or a service
// that is down is orange, only a real failure is red. 'resolving' is calm gray: nothing is red while the session is still being asked.
export const NOTICE_COLORS = { session: 'info', role: 'neutral', down: 'warning', error: 'error', empty: 'neutral', resolving: 'neutral' }

// The button of a notice. The default of the standard (7c): a cover offers "Sign in" only through the chip of the bar (none here) and "Retry" when
// the service is down; a section note has none. A page whose surface has no bar chip asks for act 'sign-in': on a role cause it is drawn as
// "Change role" (owner rule 2026-11-06: floating panels and locked launchers carry the way out), the same dialog that keeps the current session.
export function noticeActionOf(kind, variant, act) {
	const given = act === null || act === undefined ? (variant === 'cover' && kind === 'down' ? 'retry' : '') : act
	if (given === 'sign-in' && kind === 'role') return 'change-role'
	if (given === 'change-role' && kind === 'session') return 'sign-in'
	return given
}

export function noticeKindOf({ reason, serviceDown, error } = {}) {
	if (reason === 'signed_out') return 'session'
	if (reason === 'role') return 'role'
	if (serviceDown) return 'down'
	if (error) return 'error'
	return ''
}

// explicit keys (not built at run time) so the i18n checks of the plugins can see that each one is used
const ROLE_KEYS = { viewer: 'lockrole_viewer', operator: 'lockrole_operator', technician: 'lockrole_technician', admin: 'lockrole_admin' }

export function roleLabel(role, t) {
	return t(ROLE_KEYS[role] || ROLE_KEYS.viewer)
}

// state = sessionState() of workshop-auth.js: an 'expired' session and a 'pin-locked' one say what happened instead of the generic sentence
export function noticeText(kind, { needed, role, state, action } = {}, t) {
	if (kind === 'resolving') return t('notice_resolving')
	if (kind === 'session') {
		if (state === 'expired') return t('notice_session_expired')
		if (state === 'pin-locked') return t('notice_pin_locked')
		return t('notice_session_reason')
	}
	if (kind === 'role' && action) return t('notice_role_action', { action, needed: roleLabel(needed, t), role: roleLabel(role, t) })
	if (kind === 'role') return t('notice_role_reason', { needed: roleLabel(needed, t), role: roleLabel(role, t) })
	if (kind === 'down') return t('notice_down_reason')
	return ''
}
