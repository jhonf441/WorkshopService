'use strict'

// After the service accepted to restart: the page says "restarting" everywhere until the service is back (it publishes a new start
// time), and never stays there for good.
//
//   restartOutcome(m)    pure. m: { startedBefore, startedNow (serviceStarted as published), running, elapsedS }
//                        'back' (a new start time and it runs) | 'not-restarted' (still the same one after 90 s: the service may
//                        accept and not restart) | 'waiting'. A service that never comes back stays 'waiting' here: the verdict of
//                        the page says "stopped" by itself (a stopped service wins over "restarting").
//   watchRestart()       starts the watch (called when service.restart was accepted)
//   restartWatch         { active, outcome: '' | 'back' | 'not-restarted', since (the start time it still has) } for the screen

import Vue from 'vue'
import { every, timeNow } from '../clock.js'
import { get, serviceRunning } from '../live/published.js'
import { pageState } from '../page-state.js'

export const SERVICE_RESTART_S = 90

export const restartWatch = Vue.observable({ active: false, outcome: '', since: '' })

let off = null

export function restartOutcome(m) {
	if (m.startedNow && m.startedNow !== m.startedBefore && m.running) return 'back'
	if (m.elapsedS >= SERVICE_RESTART_S && m.running) return 'not-restarted'
	return 'waiting'
}

function end(outcome) {
	if (off) off()
	off = null
	pageState.restarting = false
	Object.assign(restartWatch, { active: false, outcome, since: String(get('serviceStarted') || '') })
}

export function watchRestart() {
	if (off) off()
	const startedBefore = get('serviceStarted') || ''
	const t0 = timeNow()
	pageState.restarting = true
	Object.assign(restartWatch, { active: true, outcome: '', since: '' })
	off = every(1, () => {
		const outcome = restartOutcome({ startedBefore, startedNow: get('serviceStarted') || '', running: serviceRunning(), elapsedS: (timeNow() - t0) / 1000 })
		if (outcome !== 'waiting') end(outcome)
	})
}

export function clearRestartNote() {
	if (!restartWatch.active) restartWatch.outcome = ''
}
