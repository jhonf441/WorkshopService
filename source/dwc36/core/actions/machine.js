'use strict'

// What a person can change about how the machine behaves by itself (Machine > Automations and Communication), ONE action object each.
// Most answer a sentence that proves nothing, so each is verified against what the service publishes (or reads again) and says "not
// confirmed" when that does not change in time. One write at a time per group.
//
//   moveMode.run({ mode })          movement.lock    'protected' | 'duet'; handing it over ("duet") asks a second touch
//   moveIdle.run({ idle_s })        movement.lock    seconds of quiet after which an open live job closes by itself (0 = never)
//   moveRelease.run({ release_s })  movement.lock    seconds of quiet that free the movement in protected mode
//   airDelay.run({ seconds })       air.delay        seconds the air stays on after the laser stops
//   guardEnable.run({ enabled })    guard.set        turning the guard OFF is a level 4 dialog of the page (the service asks nothing)
//   guardAction.run({ action })     guard.set        'notify' | 'pause'; lowering to "notify" is level 4
//   guardTune.run({ ...seconds })   guard.set        the tolerances; level 3
//   zonesSet.run(args)              bedzones.set     the whole configuration + the revision it was read at; a 409 says somebody saved first
//   relayStart / relayStop          camera.start / camera.stop    not saved: after a restart the saved setting applies; stopping asks a second touch
//   commsSet.run({ plugin_channel | jog_channel })   comms.set    the SERVICE asks (428, level 4) and may refuse ("not now: <reason>")
//
// airAuto (the automatic air switch) and the rest of the daily ones are in today.js: the home and this section draw the same objects.

import { createAction } from '../store/action.js'
import { get, motion } from '../live/published.js'
import { bedZones, cameraRelay, guardSettings } from '../resources.js'

export const VERIFY_MS = 5000
const GUARD_MS = 12000      // the guard publishes what it holds on its own beat, a few seconds after the change
const MOTION_MODES = { protegido: 'protected', protected: 'protected', duet: 'duet' }

// motion.settings as the page understands it: the service publishes the mode in Spanish ("protegido") on the machine
export function movementSettings() {
	const s = (motion() || {}).settings || {}
	return { mode: MOTION_MODES[s.mode] || '', release_s: s.release_s === undefined ? null : s.release_s, idle_s: s.idle_s === undefined ? null : s.idle_s }
}

export const moveMode = createAction({
	op: 'movement.lock', group: 'movement', arm: args => (args && args.mode === 'duet' ? 'double' : 'none'),
	verify: { until: (data, args) => movementSettings().mode === args.mode, timeoutMs: VERIFY_MS }
})
export const moveIdle = createAction({
	op: 'movement.lock', group: 'movement',
	verify: { until: (data, args) => movementSettings().idle_s === args.idle_s, timeoutMs: VERIFY_MS }
})
export const moveRelease = createAction({
	op: 'movement.lock', group: 'movement',
	verify: { until: (data, args) => movementSettings().release_s === args.release_s, timeoutMs: VERIFY_MS }
})

export const airDelay = createAction({
	op: 'air.delay', group: 'air',
	verify: { until: (data, args) => Number(get('airAssistDelay')) === Number(args.seconds), timeoutMs: VERIFY_MS }
})

const guard = () => get('guardStatus') || {}

export const guardEnable = createAction({
	op: 'guard.set', group: 'guard', arm: args => (args && args.enabled === false ? 'dialog-check' : 'none'),
	verify: { until: (data, args) => guard().enabled === args.enabled, timeoutMs: GUARD_MS }
})
export const guardAction = createAction({
	op: 'guard.set', group: 'guard', arm: args => (args && args.action === 'notify' ? 'dialog-check' : 'none'),
	verify: { until: (data, args) => guard().action === args.action, timeoutMs: GUARD_MS }
})
export const guardTune = createAction({ op: 'guard.set', group: 'guard', arm: 'dialog', after: () => [guardSettings.reload()] })

export const zonesSet = createAction({ op: 'bedzones.set', group: 'zones', after: () => [bedZones.reload()] })

// the relay is "done" when what the service reports now is what was asked: it is read again until it shows
const relayIs = running => () => {
	cameraRelay.reload()
	const d = cameraRelay.data
	return !!d && d.running === running
}
export const relayStart = createAction({ op: 'camera.start', group: 'relay', verify: { until: relayIs(true), timeoutMs: 8000 } })
export const relayStop = createAction({ op: 'camera.stop', group: 'relay', arm: 'double', verify: { until: relayIs(false), timeoutMs: 8000 } })

export const commsSet = createAction({
	op: 'comms.set', group: 'comms',
	verify: {
		until: (data, args) => {
			const c = get('communication') || {}
			return (args.plugin_channel === undefined || c.channel_cfg === args.plugin_channel) && (args.jog_channel === undefined || c.channel_jog_cfg === args.jog_channel)
		},
		timeoutMs: 8000
	}
})
