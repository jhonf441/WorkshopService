'use strict'

// The two forms of the bridge card (security and settings) as pure functions: reading the settings file into a form, checking a form, and
// writing a form over the file that was read again (the key, its hash and the trusted addresses belong to the bridge: they are never touched here).
// No texts: a check answers with a key of the area bridgeCard and its parameters. tests/bridge-forms.test.js pins every rule.

export const DEFAULT_CONFIG = { port: 23, exclusive: true, queries: ['M114', 'M115', 'M105', 'M119', 'M122', 'M408', 'M503', 'M27', 'M20', 'M36'], names: {}, extended_greeting: false, skip_material_macro: false, debug: false, debug_timeout_min: 30, debug_renew: true }

const clamp = (v, lo, hi, dflt) => Math.max(lo, Math.min(hi, Number(v) || dflt))

// ---- security: who can connect and the limits
export function secFormFrom(c) {
	const allowed = c.allowed || []
	return {
		modeIp: allowed.length ? 'list' : 'local',
		allowed: allowed.slice(),
		max_connections: c.max_connections || 8,
		attempts_key: c.password_attempts || 5,
		block_min: Math.round((c.block_seconds || 300) / 60),
		wait_order: c.order_timeout_s || 15,
		queries_in_job: c.queries_in_job !== false
	}
}

// -> { allowed } (the list to save, empty for "my local network") or { error: { key, params } }
export function checkSecurity(f) {
	const allowed = f.modeIp === 'list' ? (f.allowed || []).map((x) => String(x).trim()).filter(Boolean) : []
	if (f.modeIp === 'list' && !allowed.length) return { error: { key: 'add_at_least_one_ip_or' } }
	const bad = allowed.filter((x) => !/^\d{1,3}(\.\d{1,3}){3}(\/\d{1,2})?$/.test(x))
	if (bad.length) return { error: { key: 'not_understood_x_use', params: { x: bad.join(', ') } } }
	return { allowed }
}

export function applySecurity(current, f, allowed) {
	return Object.assign(current, {
		allowed,
		max_connections: clamp(f.max_connections, 1, 50, 8),
		password_attempts: clamp(f.attempts_key, 1, 50, 5),
		block_seconds: clamp(f.block_min, 1, 1440, 5) * 60,
		order_timeout_s: clamp(f.wait_order, 1, 300, 15),
		queries_in_job: !!f.queries_in_job
	})
}

// ---- settings: port, mode, names by address, queries, debug
export function configFrom(c) {
	const config = Object.assign({}, DEFAULT_CONFIG, c)
	return {
		config,
		names: Object.entries(config.names || {}).map(([ip, name]) => ({ ip, name })),
		queriesTxt: (config.queries || []).join(', ')
	}
}

export function validPort(p) {
	return Number.isInteger(p) && p >= 1 && p <= 65535
}

export function applyConfig(current, config, port, names, queriesTxt) {
	return Object.assign(current, {
		port,
		exclusive: !!config.exclusive,
		extended_greeting: !!config.extended_greeting,
		skip_material_macro: !!config.skip_material_macro,
		debug_timeout_min: clamp(config.debug_timeout_min, 1, 1440, 30),
		debug_renew: config.debug_renew !== false,
		names: Object.fromEntries(names.filter((n) => n.ip && n.name).map((n) => [n.ip, n.name])),
		queries: queriesTxt.split(/[\s,]+/).map((x) => x.trim().toUpperCase()).filter(Boolean)
	})
}
