'use strict'

// The CAUSE of a notice and its sentence (ESTANDAR 2: one cause, one color, one sentence). Pure logic: the translator is passed in, so
// tests/notice-standard.test.js loads this file in node.
//
//   noticeKindOf({ reason, serviceDown, error })   'session' | 'role' | 'down' | 'error' | ''
//                                                  reason = what accessReason() of workshop-auth.js answers ('signed_out' | 'role' | '')
//   noticeText(kind, { needed, role }, t)          the one sentence of that cause; needed / role are role ids ('operator', ...)
//   roleLabel(role, t)                             "Operador", "Técnico"... (the lockrole_* texts)
//   NOTICE_ICONS                                   the mdi icon of each cause

export const NOTICE_ICONS = {
	session: 'mdi-account-lock-outline',
	role: 'mdi-lock-outline',
	down: 'mdi-power-plug-off-outline',
	error: 'mdi-alert-circle-outline',
	empty: 'mdi-information-outline'
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

export function noticeText(kind, { needed, role } = {}, t) {
	if (kind === 'session') return t('notice_session_reason')
	if (kind === 'role') return t('notice_role_reason', { needed: roleLabel(needed, t), role: roleLabel(role, t) })
	if (kind === 'down') return t('notice_down_reason')
	return ''
}
