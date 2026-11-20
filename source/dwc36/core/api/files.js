'use strict'

// Files of the SD card through DWC's own file API (/machine/file/<path>), for the few things the service shares through files instead of the
// API: the state, the settings and the order file of the G-code bridge. Sends the session key of DWC; never caches; a PUT is always
// application/octet-stream (anything else makes DWC answer 400 and leaves the file EMPTY).
//
//   readJson(path)          { status, data, error }   status 200 (data is the parsed file), 404 (not there), another HTTP status or 0 (no answer)
//   writeJson(path, data)   resolves, or throws Error('HTTP <status>')

const url = path => '/machine/file/' + encodeURIComponent(path)

function headers(extra) {
	const h = Object.assign({}, extra || {})
	if (typeof window !== 'undefined' && window.__workshopSession) h['X-Session-Key'] = window.__workshopSession
	return h
}

export async function readJson(path) {
	try {
		const r = await fetch(url(path), { headers: headers(), cache: 'no-store' })
		if (r.status === 404) return { status: 404, data: null, error: '' }
		if (!r.ok) return { status: r.status, data: null, error: 'HTTP ' + r.status }
		return { status: 200, data: await r.json(), error: '' }
	} catch (e) {
		return { status: 0, data: null, error: (e && e.message) || String(e) }
	}
}

export async function writeJson(path, data) {
	const r = await fetch(url(path), { method: 'PUT', headers: headers({ 'Content-Type': 'application/octet-stream' }), body: JSON.stringify(data, null, 2) })
	if (!r.ok) throw new Error('HTTP ' + r.status)
}
