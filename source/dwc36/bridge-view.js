'use strict'

// What the bridge card works out from the state file, as pure functions: no texts, no i18n, no DOM, no clock of its own (the time is passed in).
// BridgeCard.vue and its parts turn the results into words. tests/bridge-view.test.js pins every rule.

export const READ_MS = 3000 // the state file is read this often
export const READ_MAX_MS = 30000 // ... and this seldom when it is not there (404)
export const READ_FAILS = 3 // failed reads of the state file in a row before the card says it cannot read it
export const UNIT_EVERY = 4 // the unit of the Pi is read once every this many turns of the read
export const ARM_MS = 4000 // a double tap is armed for this long
export const ACTION_WAIT_MS = 8000 // the bridge has this long to answer an action
export const CHART_HEIGHT = 60

// ms until the next read: 3 s, doubling for every 404 in a row up to 30 s
export function readDelayMs(missing) {
	return missing ? Math.min(READ_MAX_MS, READ_MS * Math.pow(2, missing)) : READ_MS
}

// the card reads only while its page is active, the browser tab is shown and the element is in the document
export function mayRead(active, documentHidden, el) {
	return !!(active && !documentHidden && el && el.isConnected !== false)
}

// why the bridge cannot be restarted now: 'live_job' | 'recent_orders' | 'machine_job' | '' (it can). machineStatus: the status of the machine or undefined
export function inUseReason(state, machineStatus) {
	if (!state) return ''
	if (state.activity && state.activity.live_job && state.activity.live_job.active) return 'live_job'
	if ((state.clients || []).some((c) => c.last_order_age_s != null && c.last_order_age_s < 30)) return 'recent_orders'
	if (['processing', 'paused', 'pausing', 'resuming', 'simulating', 'cancelling'].includes(machineStatus)) return 'machine_job'
	return ''
}

// the bars of the last hour: history is [[orders, queries, rejections, connections], ...], one per minute
export function chartMax(history) {
	return Math.max(1, ...(history || []).map((x) => x[0] + x[1]))
}

export function chartBars(history, height) {
	const h = history || []
	const max = chartMax(h)
	return h.map((x, i) => {
		const tot = x[0] + x[1]
		const bar = tot ? Math.max(2, (tot / max) * (height - 4)) : 0
		const ho = tot ? bar * x[0] / tot : 0
		return { ho, hc: bar - ho, r: x[2] > 0, minutes: 59 - i, orders: x[0], queries: x[1], rejections: x[2], connections: x[3] }
	})
}

// [orders, queries, rejections] of the whole hour
export function hourTotals(history) {
	return (history || []).reduce((a, x) => [a[0] + x[0], a[1] + x[1], a[2] + x[2]], [0, 0, 0])
}

// the address typed to be trusted: a plain IPv4 or IPv6 address (the bridge compares trusted addresses as written, no networks)
export function isTrustValid(text) {
	const v = (text || '').trim()
	const v4 = /^(25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)(\.(25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)){3}$/.test(v)
	const v6 = v.indexOf(':') >= 0 && /^[0-9a-fA-F:.]+$/.test(v) && v.length <= 45
	return v4 || v6
}

// the connected clients whose address is not trusted yet, one per address
export function clientsToTrust(state, sec) {
	if (!state || !sec) return []
	const seen = new Set()
	return state.clients.filter((cl) => {
		if (cl.trusted || seen.has(cl.ip)) return false
		seen.add(cl.ip)
		return true
	})
}

// seconds since the last order to the machine, from the epoch second the bridge reports and the time now (ms)
export function secondsSince(epochS, nowMs) {
	return Math.max(0, Math.round((nowMs / 1000) - epochS))
}

export function ipOf(id) {
	return id ? id.split(':')[0] : ''
}

// the lines of the debug panel that are seen: after the last cleared one and, when a client is chosen, only its own
export function debugVisible(views, since, client) {
	return views.filter((l) => l.id > since && (!client || l.c === client))
}

// the clients named in the lines, sorted; the chosen one stays in the list even after it left
export function debugClients(views, chosen) {
	const names = [...new Set(views.map((l) => l.c).filter(Boolean))].sort()
	if (chosen && names.indexOf(chosen) < 0) names.push(chosen)
	return names
}

export function debugCopyText(lines) {
	return lines.map((l) => `${l.t} ${l.c} ${l.k} ${l.x}`).join('\n')
}

// ---- formats
export function dur(s) {
	if (s == null) {
		return ''
	}
	if (s < 60) {
		return s + ' s'
	}
	if (s < 3600) {
		return Math.round(s / 60) + ' min'
	}
	if (s < 86400) {
		return Math.floor(s / 3600) + ' h ' + Math.round((s % 3600) / 60) + ' min'
	}
	return Math.floor(s / 86400) + ' d ' + Math.round((s % 86400) / 3600) + ' h'
}

export function num(n) {
	return n == null ? '--' : Number(n).toLocaleString()
}

export function bytes(b) {
	if (b == null) {
		return '--'
	}
	if (b < 1024) {
		return b + ' B'
	}
	if (b < 1048576) {
		return (b / 1024).toFixed(1) + ' KB'
	}
	return (b / 1048576).toFixed(1) + ' MB'
}
