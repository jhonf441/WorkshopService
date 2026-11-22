'use strict'

// One rule for "this control needs a double tap" (page redesign, step 1; owner decision P-2). The double tap is ONE pattern (ArmButton.vue): the first tap
// arms the button (amber, "tap again"), the second tap does the action, and the button disarms by itself after ARM_MS.
//
// Pure module: no imports of the page, no timers. tests/page-arm.test.js checks this table against dsf/golden/api_contract.json.
//
//   ACTION_LEVELS     the operations the service page itself guards with a double tap (op -> 'double'); a control that is only a stop is never in it
//   needsArming(op, kind)   the API console: every operation that is not a read asks for the double tap, in every screen. An operation the list of the
//                     service has not described yet (kind unknown) is treated as dangerous, except the stop operations, which are never delayed
//   failureOf(e)      the error a card shows: the typed ApiError itself (ErrorNotice reads its kind and text), or null for a cancelled confirmation
//   resultText(r)     the text of an answer of the service (a message, or the JSON of a result)

import { STOP_OPS } from './access-reason.js'

import { ARM_MS } from './arm-ms.js'

export { ARM_MS }

export const ACTION_LEVELS = Object.freeze({
	'power.after_job': 'double', // only the direction that arms the shutdown at the end of the job; turning it off is one tap
	'movement.lock': 'double', // the mode "I handle it myself" and every time of the card (including "Never")
	'modules.set': 'double', // the mode of an internal process (auto / always / never)
	'job.close': 'double',
	'password.set': 'double',
	'password.clear': 'double',
	'comms.set': 'double' // the unlock of the channel change (the level 4 dialog replaces the second tap when the control bar is there)
})

export function needsArming(op, kind) {
	if (kind === 'read' || kind === 'stop') return false
	if (kind) return true
	return STOP_OPS.indexOf(op) < 0
}

export function failureOf(e) {
	return e && e.code === 'cancelled' ? null : (e || null)
}

export function resultText(r) {
	return typeof r === 'string' ? r.trim() : JSON.stringify(r)
}
