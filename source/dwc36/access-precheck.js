'use strict'

// The dry run of a change of a person or of a group, asked BEFORE the confirmation dialog opens (DISENO-PANTALLAS 2.5): the service runs the same checks as the
// real operation on a copy (access.attach.validate, access.detach.validate, access.ceiling.validate, access.groups.validate) and answers the same refusal, so the
// screen can say "this would be refused: ..." instead of letting the person confirm and fail. Nothing is written by it. The service stays the judge: when the
// dry run itself cannot be answered (the service is busy, the session ended) the dialog opens as before and the real call tells.
//
//   precheckPlan(change)          [method, ...arguments] of accessApi for a change of access-edit-view.js, or null for a kind it does not know
//   precheck(api, change)         '' when the change would be accepted (or the dry run could not be answered), else the sentence of the refusal

import { refusalOf } from './access-edit-view.js'

export function precheckPlan(change) {
	const c = change || {}
	if (c.kind === 'attach') return ['attachValidate', c.subject, { profile: c.profile }]
	if (c.kind === 'detach') return ['detachValidate', c.subject, { profile: c.profile }]
	if (c.kind === 'join') return ['attachValidate', c.subject, { memberOf: c.group }]
	if (c.kind === 'leave') return ['detachValidate', c.subject, { memberOf: c.group }]
	if (c.kind === 'ceiling') return ['ceilingValidate', c.subject, c.profile]
	if (c.kind === 'group_save') return ['groupsValidate', { name: c.name, description: c.description || '', profiles: [] }, false]
	if (c.kind === 'group_remove') return ['groupsValidate', { name: c.name }, true]
	return null
}

export async function precheck(api, change) {
	const plan = precheckPlan(change)
	if (!plan) return ''
	try {
		await api[plan[0]](...plan.slice(1))
		return ''
	} catch (e) {
		const r = refusalOf(e)
		return r.handled && r.text ? r.text : ''
	}
}
