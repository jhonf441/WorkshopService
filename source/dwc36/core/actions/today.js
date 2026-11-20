'use strict'

// The everyday actions of the machine, ONE owner each: the home ("Actions of today") and Machine > Automations draw the same
// action objects, so a change made in one place is seen in the other without reloading.
//
// All of them answer a sentence that proves nothing: each one is verified against what the service publishes (or the global of the
// board) and says "not confirmed" when that does not change in time. One write at a time (group `today`).
//
//   afterJob.run({ armed })     power.after_job : arming asks a second touch, disarming does not ; verified on global.powerOffOnFinish
//   timer.run({ minutes })      power.timer     : second touch ; verified when shutdownTimer is published
//   timerCancel.run()           power.timer_cancel : one touch ; verified when shutdownTimer is gone
//   closeJob.run()              job.close       : second touch ; verified when the live job is no longer active
//   airAuto.run({ on })         air.auto        : one touch ; verified on airAssistAuto

import { createAction } from '../store/action.js'
import { get, liveJob, powerOffOnFinish, shutdownTimer } from '../live/published.js'

export const VERIFY_MS = 5000
const GROUP = 'today'

export const afterJob = createAction({
	op: 'power.after_job', group: GROUP, arm: args => (args && args.armed ? 'double' : 'none'),
	verify: { until: (data, args) => powerOffOnFinish() === !!args.armed, timeoutMs: VERIFY_MS }
})

export const timer = createAction({
	op: 'power.timer', group: GROUP, arm: 'double',
	verify: { until: () => shutdownTimer() !== null, timeoutMs: VERIFY_MS }
})

export const timerCancel = createAction({
	op: 'power.timer_cancel', group: GROUP,
	verify: { until: () => shutdownTimer() === null, timeoutMs: VERIFY_MS }
})

export const closeJob = createAction({
	op: 'job.close', group: GROUP, arm: 'double',
	verify: { until: () => { const job = liveJob(); return !job || !job.active }, timeoutMs: VERIFY_MS }
})

export const airAuto = createAction({
	op: 'air.auto', group: GROUP,
	verify: { until: (data, args) => get('airAssistAuto') === !!args.on, timeoutMs: VERIFY_MS }
})
