'use strict'

// What a person can do to the processes of the service, ONE action object per thing and per process (a second screen that shows
// the same process draws the same object).
//
//   processAction(kind, id)   kind 'pause' | 'resume' | 'restart': pausing and restarting ask a second touch, resuming does not.
//                             The answer says only that it was accepted: each one is verified against what the service publishes
//                             (paused / not paused / the pending restart gone). A restart that does not finish in a minute says so.
//   modeAction(id)            modules.set { process, mode }: how it runs (auto / on / off); verified on the stored mode. It applies
//                             when the service restarts (the service says which ones wait).
//   serviceRestart            service.restart: the service asks for the confirmation itself (its own title and text) and may refuse
//                             with the list of reasons. Whoever runs it watches the service come back (sections/health).
//   boxHide / boxShow         the report of the last unclean shutdown: reviewed / show it again; verified on the published report.

import { createAction } from '../store/action.js'
import { get, processes } from '../live/published.js'
import { watchRestart } from './service-restart.js'

export const VERIFY_MS = 5000
export const RESTART_WAIT_MS = 60000

const made = new Map()
const published = id => (processes() || {})[id] || {}

function once(key, make) {
	if (!made.has(key)) made.set(key, make())
	return made.get(key)
}

export function processAction(kind, id) {
	return once(kind + '|' + id, () => {
		// a restart is done when the pending mark was seen and is gone, or when the loop shows a younger age than before (it came and
		// went between two publications); "not pending" alone proves nothing: the mark takes a moment to be published
		let before = null
		let seen = false
		const restarted = () => {
			const p = published(id)
			if (p.restart_pending === true) { seen = true; return false }
			return seen || (before !== null && typeof p.active_s === 'number' && p.active_s < before)
		}
		const verify = kind === 'pause' ? { until: () => published(id).paused === true, timeoutMs: VERIFY_MS }
			: kind === 'resume' ? { until: () => published(id).paused !== true, timeoutMs: VERIFY_MS }
				: { until: restarted, timeoutMs: RESTART_WAIT_MS }
		const args = () => {
			const a = published(id).active_s
			before = typeof a === 'number' ? a : null
			seen = false
			return { process: id }
		}
		return createAction({ op: 'processes.' + kind, args, group: 'process-' + id, arm: kind === 'resume' ? 'none' : 'double', verify })
	})
}

export function modeAction(id) {
	return once('mode|' + id, () => createAction({
		op: 'modules.set', group: 'process-' + id,
		verify: {
			until: (data, args) => {
				const m = ((get('servicesInternal') || {}).modules || {})[id] || {}
				return (m.configured || m.mode) === args.mode
			},
			timeoutMs: VERIFY_MS
		}
	}))
}

export const serviceRestart = createAction({ op: 'service.restart', group: 'service', after: () => { watchRestart() } })

const report = () => (get('boxBlack') || {}).report || null

export const boxHide = createAction({ op: 'blackbox.hide', group: 'blackbox', verify: { until: () => report() === null, timeoutMs: VERIFY_MS } })
export const boxShow = createAction({ op: 'blackbox.show', group: 'blackbox', verify: { until: () => report() !== null, timeoutMs: VERIFY_MS } })
