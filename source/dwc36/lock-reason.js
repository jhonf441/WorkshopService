'use strict'

// Why something does not move, in one sentence next to it (the AWS-console rule of the owner, 2026-11-04): the reason is told apart
// by its cause, because the person fixes each one differently (ESTANDAR 2, notice-kind.js).
//
//   lockReason('technician')   '' when the person may; "Requiere iniciar sesión." when nobody is signed in;
//                              "Requiere el rol Técnico. Tu rol: Operador." when the role is too low
//   lockReasonOp('light.set')  the same for one operation of the service table
//   lockKind('technician')     the cause alone: '' | 'session' | 'role' (what <lock-reason> and <session-notice> are drawn with)
//   lockKindOp('light.set')
//
// Text keys are plugins.<Id>.shared.notice_* (shared-t.js). Not pure (it reads the identity and the language); the decision is
// roleAtLeast / workshopCan, the cause is accessReason of workshop-auth.js.

import { ts } from './shared-t.js'
import { RANK_OPS } from './role-view.js'
import { accessReason, workshopCan, workshopRole } from './workshop-auth.js'
import { noticeKindOf, noticeText } from './notice-kind.js'

function kindOf(reason) {
	return noticeKindOf({ reason })
}

function sentence(kind, need) {
	return kind ? noticeText(kind, { needed: need, role: workshopRole() }, ts) : ''
}

export function lockKindOp(op, need, ctx) {
	void need
	return kindOf(accessReason(op, ctx))
}

export function lockKind(min) {
	const op = RANK_OPS[min]
	if (op === undefined || op === '') return ''
	return kindOf(workshopCan(op) ? '' : accessReason(op))
}

export function lockReasonOp(op, need, ctx) {
	return sentence(lockKindOp(op, need, ctx), need || 'technician')
}

export function lockReason(min) {
	return sentence(lockKind(min), min)
}
