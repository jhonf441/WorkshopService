'use strict'

// While somebody looks at a live screen, the page tells the service every 10 s (view.heartbeat, topic health) so that it publishes
// its processes at the fast rate; with nobody looking the service goes back to its slow rate by itself.
//
//   const stop = startHeartbeat(() => wantsLive)     wantsLive(): true while the visible section declares live data
//
// It sends nothing without a session, nor while the session is being resolved (the operation is not open to a visitor: asking
// would only produce a 401 on every tick), nor with the page out of sight (the clock does not tick then).

import { every } from '../clock.js'
import { quietCall } from '../api/call.js'
import { can } from '../store/session.js'

export const HEARTBEAT_S = 10
export const HEARTBEAT_OP = 'view.heartbeat'

export function startHeartbeat(wantsLive, topic) {
	const beat = () => {
		if (!wantsLive() || can(HEARTBEAT_OP).state !== 'ok') return
		quietCall(HEARTBEAT_OP, { topic: topic || 'health' }).catch(() => { /* a missed beat only slows the publishing down */ })
	}
	beat()
	return every(HEARTBEAT_S, beat)
}
