'use strict'

// The page's reader of bridge-state.json: the SAME rules as dsf/bridge_contract.py (bridge/CONTRACT.md sections 2 and 3), proven equal by
// the shared vectors bridge/contract/vectors.json (tests/bridge-contract.test.js here, dsf/test_bridge_contract.py there). A change of a
// rule changes the vectors first, so the two readers cannot drift. Pure functions, no texts: BridgeCard.vue turns the result into words.
//
// The age of the state is NOT read from the absolute times inside the file (a browser may read them rounded to about 3 hours): the caller
// passes `ageS`, how long ago the file last CHANGED (the card counts the seconds since `seq` last moved).

export const SCHEMAS = [2]
export const ALIVE_S = 15 // older than this: the bridge is not running
export const FRESH_S = 10 // "orders pending" proves something only in a file younger than this
export const DEFAULT_PORT = 23
export const CONTRACT = 1 // the CONTRACT.md version this reader implements

const isNum = (v) => typeof v === 'number' && Number.isFinite(v)
const isInt = (v) => isNum(v) && Number.isInteger(v)
const isObj = (v) => v !== null && typeof v === 'object' && !Array.isArray(v)
// Python truthiness of a JSON value ([] and {} are falsy there)
const truthy = (v) => !(v === null || v === false || v === 0 || v === '' || (Array.isArray(v) && v.length === 0) || (isObj(v) && Object.keys(v).length === 0))

// raw: the text of the file, or an object already parsed. Returns { status: 'ok' | 'garbage' | 'incompatible', state, ageS, schema, version,
// contract, legacy, newer }. Never throws. ('missing' is the caller's: no file / HTTP error / network down.)
export function parse(raw, ageS) {
	let state = raw
	if (typeof raw === 'string') {
		try {
			state = JSON.parse(raw)
		} catch (e) {
			return { status: 'garbage', state: {}, ageS: ageS == null ? null : ageS }
		}
	}
	if (!isObj(state)) return { status: 'garbage', state: {}, ageS: ageS == null ? null : ageS }
	const schema = state.schema === undefined ? null : state.schema
	const schemaOk = schema === null || (isInt(schema) && SCHEMAS.includes(schema))
	let contract = state.contract === undefined ? null : state.contract
	let legacy = contract === null
	if (legacy) contract = 1
	else if (!isInt(contract) || contract < 1) {
		contract = 1
		legacy = true
	}
	const version = typeof state.version === 'string' ? state.version : null
	const base = { ageS: ageS == null ? null : ageS, schema, version, contract, legacy }
	if (!schemaOk) return Object.assign({ status: 'incompatible', state: {}, newer: false }, base)
	return Object.assign({ status: 'ok', state, newer: contract > CONTRACT }, base)
}

export function missing() {
	return { status: 'missing', state: {}, ageS: null }
}

export function alive(read, maxAgeS) {
	return !!read && read.status === 'ok' && read.ageS != null && read.ageS <= (maxAgeS == null ? ALIVE_S : maxAgeS)
}

// one word: 'down' | 'incompatible' | 'newer' | 'ok'
export function health(read) {
	if (!read || read.status === 'missing' || read.status === 'garbage') return 'down'
	if (read.status === 'incompatible') return 'incompatible'
	if (!alive(read)) return 'down'
	return read.newer ? 'newer' : 'ok'
}

// the contract of the bridge for a chip: 'ok' (this reader's version), 'newer' (ahead of the page), 'old' (declares nothing: a bridge written
// before the contract, run install.sh again), or null when nothing can be said (no readable state of a known schema)
export function contractKind(read) {
	if (!read || read.status !== 'ok') return null
	if (read.legacy) return 'old'
	return read.newer ? 'newer' : 'ok'
}

const num = (v) => (isNum(v) ? v : 0)

// seconds since the last non-query line of any client, or null if unknown; 0 while an order is pending in a fresh file
export function ordersAgeS(read, nowS) {
	if (!read || read.status !== 'ok') return null
	const state = read.state
	const fileAge = read.ageS || 0
	const now = nowS == null ? Date.now() / 1000 : nowS
	const cls = state.clients
	if (Array.isArray(cls) && cls.some((c) => isObj(c) && 'last_order_age_s' in c)) {
		let val = null
		for (const c of cls) {
			if (!isObj(c)) continue
			if (num(c.pending_orders) > 0 && fileAge <= FRESH_S) return 0
			if (isNum(c.last_order_age_s)) {
				const h = c.last_order_age_s + fileAge
				val = val === null ? h : Math.min(val, h)
			}
		}
		return val
	}
	const act = state.activity
	if (isObj(act)) {
		const fresh = isNum(act.generated_at) && now - act.generated_at <= FRESH_S
		if (fresh && num(act.pending_orders) > 0) return 0
		return isNum(act.last_order_at) ? Math.max(0, now - act.last_order_at) : null
	}
	return null
}

export function port(read, defaultPort) {
	const dflt = defaultPort == null ? DEFAULT_PORT : defaultPort
	if (!read || read.status !== 'ok') return dflt
	const v = read.state.port
	if (!truthy(v)) return dflt
	if (typeof v === 'boolean') return 1
	if (isNum(v)) return Math.trunc(v)
	if (typeof v === 'string' && /^\s*[+-]?\d+\s*$/.test(v)) return parseInt(v.trim(), 10)
	return dflt
}

export function clients(read) {
	return read && read.status === 'ok' && Array.isArray(read.state.clients) ? read.state.clients.filter(isObj) : []
}

// true: this bridge has the safe stop; false: old or incomplete install; null: unknown
export function liveStopEnabled(read) {
	if (!read || read.status !== 'ok') return null
	const ls = read.state.live_stop
	return isObj(ls) ? truthy(ls.enabled) : false
}
