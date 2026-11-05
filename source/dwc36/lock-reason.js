'use strict'

// Why something does not move, in one sentence next to it (the AWS-console rule of the owner, 2026-11-04): the reason is told apart
// by its cause, because the person fixes each one differently.
//
//   lockReason('technician')   '' when the person may; "Sin sesión: inicia sesión..." when nobody is signed in;
//                              "Hace falta el rol de técnico (tu rol: operador)." when the role is too low
//   lockReasonOp('light.set')  the same for one operation of the service table
//
// Text keys are plugins.<Id>.shared.lock_* (shared-t.js). Not pure (it reads the identity and the language); the decision is
// roleAtLeast / workshopCan, the cause is accessReason of workshop-auth.js.

import { ts } from './shared-t.js'
import { RANK_OPS } from './role-view.js'
import { accessReason, workshopCan, workshopRole } from './workshop-auth.js'

// explicit keys (not built at run time) so the i18n checks of the plugins can see that each one is used
const ROLE_KEYS = { viewer: 'lockrole_viewer', operator: 'lockrole_operator', technician: 'lockrole_technician', admin: 'lockrole_admin' }

function roleName(role) {
	return ts(ROLE_KEYS[role] || ROLE_KEYS.viewer)
}

function sentence(reason, need) {
	if (!reason) return ''
	if (reason === 'signed_out') return ts('lock_signed_out')
	const role = workshopRole()
	return ts('lock_role', { needed: roleName(need), role: roleName(role) })
}

export function lockReasonOp(op, need, ctx) {
	return sentence(accessReason(op, ctx), need || 'technician')
}

export function lockReason(min) {
	const op = RANK_OPS[min]
	if (op === undefined || op === '') return ''
	return sentence(workshopCan(op) ? '' : accessReason(op), min)
}
