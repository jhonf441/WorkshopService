'use strict'

// Health chip of the page header (2026-10-23): one chip per plugin with the WORST state of what the plugin watches.
//   reasons: [{ level: 'warn' | 'error', text }]   (an empty list = everything fine)
// The pages build their own list; the header adds the service problem and the session by itself. Pure logic, tested in
// tests/page-health.test.js.

export const LEVELS = ['ok', 'warn', 'error']

export function healthLevel(reasons) {
	let n = 0
	;(reasons || []).forEach(r => {
		if (!r) return
		n = Math.max(n, r.level === 'error' ? 2 : 1)
	})
	return LEVELS[n]
}

// color (Vuetify meaning, DESIGN.md section 2), icon and text key of each level
export const LEVEL_UI = {
	ok: { color: 'success', icon: 'mdi-check-circle-outline', key: 'header_health_ok' },
	warn: { color: 'warning', icon: 'mdi-alert-outline', key: 'header_health_warn' },
	error: { color: 'error', icon: 'mdi-alert-circle-outline', key: 'header_health_error' }
}

// A Vuetify color name of a chip (the pages' own chips) as a health level: red = error, orange / amber = warn, the rest = fine
export function levelOfColor(color) {
	const c = String(color || '')
	if (c.indexOf('error') === 0 || c.indexOf('red') === 0) return 'error'
	if (c.indexOf('warning') === 0 || c.indexOf('orange') === 0 || c.indexOf('amber') === 0) return 'warn'
	return 'ok'
}
