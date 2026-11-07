'use strict'

// The port of the G-code bridge: what its error means in plain words and what to say about a port before it is saved.
// Pure functions, no texts: BridgeCard.vue turns the result into the language of the page.

const OPEN_FAILED = /Could not open port (\d+): \[Errno (\d+)\]\s*(.*)$/

// the raw error the bridge publishes ("Could not open port 80: [Errno 98] Address already in use") -> { port, kind, detail } or null.
// kind: 'in_use' (errno 98), 'denied' (errno 13, a port below 1024 without the permission), 'other'.
export function parsePortError(raw) {
	const m = OPEN_FAILED.exec(String(raw || '').trim())
	if (!m) return null
	const errno = Number(m[2])
	return { port: Number(m[1]), kind: errno === 98 ? 'in_use' : errno === 13 ? 'denied' : 'other', detail: m[3] || '' }
}

// ports that something else on a Pi like this one normally uses
const USUAL = { 22: 'ssh', 80: 'web', 443: 'web_secure' }

// what to say about a port typed in the field: { kind: 'usual', who } | { kind: 'low' } | null (nothing to say / not a valid port)
export function portHint(value) {
	const p = Number(value)
	if (!Number.isInteger(p) || p < 1 || p > 65535) return null
	if (USUAL[p]) return { kind: 'usual', who: USUAL[p], port: p }
	if (p < 1024) return { kind: 'low', port: p }
	return null
}
