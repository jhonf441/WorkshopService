'use strict'

// The home, gathered from what the page already knows (published data, the session, one read): the inputs of view.js.
// Reactive: call it inside a computed. The shell calls the same function for its status chip and the counts of its navigation, so
// the header, the navigation and the home always tell one number.
//
//   homeModel() -> { state: { running, restarting, hasData }, rows, verdict, badges, readinessFailed }

import { get, processes, serviceRunning } from '../../core/live/published.js'
import { statesOf } from '../../core/live/process-state.js'
import { pageState } from '../../core/page-state.js'
import { readiness } from '../../core/resources.js'
import { can, session } from '../../core/store/session.js'
import { attentionRows, badges, readinessPending, verdict } from './view.js'

const ADMIN_SECTIONS = ['access', 'security']
const ADMIN_OP = 'access.profiles.list'

// a row is drawn (and counted) only when the person can open the place that fixes it
export function canOpen(place) {
	if (!place || ADMIN_SECTIONS.indexOf(place.s) < 0) return true
	return can(ADMIN_OP).state === 'ok'
}

export function homeModel() {
	const internal = get('servicesInternal') || null
	const running = serviceRunning()
	const state = { running, restarting: !!pageState.restarting, hasData: !!internal, unchecked: readiness.status === 'error', noSession: ['signed-out', 'signing-in', 'expired', 'pin-locked'].indexOf(session.state) >= 0 || !!session.unknown }
	const input = {
		processes: statesOf(processes()), guard: get('guardStatus') || null, risk: get('riskActive') || [], communication: get('communication') || null,
		health: get('healthPi') || null, box: get('boxBlack') || null, modules: (internal && internal.modules) || {},
		readinessPending: readiness.status === 'ready' || readiness.status === 'empty' ? readinessPending(readiness.data) : null,
		session: { configured: session.state === 'resolving' ? null : session.configured, usersOff: session.usersOff, damaged: session.damaged },
		chainBroken: !!pageState.chainBroken
	}
	// with the service stopped what is published is old: nothing of it is counted as a notice of now
	const rows = running && internal ? attentionRows(input, canOpen) : []
	return { state, rows, verdict: verdict(state, rows), badges: badges(rows), readinessFailed: readiness.status === 'error' }
}
