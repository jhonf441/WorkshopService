'use strict'

// THE rule that says how one process of the service is doing, from what the service publishes about it
// (servicesInternal.processes[id]). Pure: no language, no clock; the screens choose the words and the colours.
//
//   processState(p, paused)  ->  { level, word }
//     word     'resting'   it waits because its plugin is stopped (calm)
//              'paused'    a person paused it and it still ticks (calm)
//              'stopped'   its loop is not alive: it crashed, the service is relaunching it        level 2
//              'unknown'   alive, but it has not completed a loop yet                              level 1
//              'late'      its last heartbeat is older than three times what it promises            level 1
//              'errors'    it ticks, and its last error is newer than its last good loop            level 1
//              'fine'      on time
//     level    0 nothing to look at, 1 a notice, 2 a failure (the same levels the header counts)
//   paused = a person paused it (processes-groups.pauseKey decides that from the item; the caller passes the answer)
//
// It is the rule of the old page (stateProcess of WorkshopService.vue), moved here unchanged so that the home, the header and the
// processes screen can never give two verdicts for the same process.

export const LATE_FACTOR = 3
export const ERROR_GRACE_S = 5

export function processState(p, paused) {
	const x = p || {}
	if (x.idle) return { level: 0, word: 'resting' }
	if (paused && x.live) return { level: 0, word: 'paused' }
	if (!x.live) return { level: 2, word: 'stopped' }
	if (x.age_ok_s === null || x.age_ok_s === undefined) return { level: 1, word: 'unknown' }
	if (x.age_ok_s > (x.expected_s || 0) * LATE_FACTOR) return { level: 1, word: 'late' }
	if (x.errorRecent && x.age_error_s < x.age_ok_s + ERROR_GRACE_S) return { level: 1, word: 'errors' }
	return { level: 0, word: 'fine' }
}

// every process the service publishes with its verdict: [{ id, level, word, process }] (the raw `errorRecent` rule of the old page: an
// error of the last hour counts; a process is paused when the service says so)
export const ERROR_RECENT_S = 3600

export function statesOf(processes) {
	const map = processes || {}
	return Object.keys(map).map(id => {
		const p = Object.assign({}, map[id])
		p.errorRecent = p.age_error_s !== null && p.age_error_s !== undefined && p.age_error_s < ERROR_RECENT_S
		const s = processState(p, p.paused === true)
		return { id, level: s.level, word: s.word, process: map[id] }
	})
}

// how many processes are at each level: { fine, notice, stopped, total } (resting and paused count as fine: nothing to look at)
export function tally(states) {
	const out = { fine: 0, notice: 0, stopped: 0, total: 0 }
	;(states || []).forEach(s => {
		out.total += 1
		if (s.level >= 2) out.stopped += 1
		else if (s.level === 1) out.notice += 1
		else out.fine += 1
	})
	return out
}
