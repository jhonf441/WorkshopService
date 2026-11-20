'use strict'

// The files of the G-code bridge on the SD card, as the service page reads and writes them (no texts, no component state).
// The bridge rewrites the state file; the page writes the action file (the bridge reads it every second), the settings file and the viewer
// heartbeat (the bridge turns debugging off by itself when nobody looks).

export const STATE_FILE = '0:/sys/workshop/data/bridge-state.json'
export const CONFIG_FILE = '0:/sys/workshop/config/bridge.json'
export const ACTION_FILE = '0:/sys/workshop/data/bridge-action.json'
export const VIEWER_FILE = '0:/sys/workshop/data/bridge-viewer.json'

export function fileUrl(p) {
	return '/machine/file/' + encodeURIComponent(p)
}

// a settings file that is not there or cannot be read is "nothing yet": null
export async function readJson(p) {
	try {
		const r = await fetch(fileUrl(p), { cache: 'no-store' })
		return r.ok ? await r.json() : null
	} catch (err) {
		return null
	}
}

export async function writeJson(p, data) {
	const r = await fetch(fileUrl(p), { method: 'PUT', body: JSON.stringify(data, null, 2), headers: { 'Content-Type': 'application/json' } })
	if (!r.ok) {
		throw new Error('HTTP ' + r.status)
	}
}
