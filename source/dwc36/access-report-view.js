'use strict'

// Pure helpers of the read-only screen Security > Report (DISENO-PANTALLAS section 2.8). No imports of the page, no DOM; a test loads this file in node.
// The report is the service's (access.report): this file filters, sorts and arranges it, and works out how long ago a time was from the clock of the ANSWER
// (`generated`), never from the clock of the browser, so the screen and the test agree.
//
// The answer of access.report (dsf/access_report.py people_and_keys):
//   { generated, damaged, locked: [names], people: [{ name, role, groups, profiles, governed, last_login, sessions, pin_changed, pin_age_days,
//       locked_for_s, last_used: { capability: epoch }, last_use }], keys: [{ id, name, enabled, created, last_used, uses, expires, breadth, idle_days }] }
//
//   PEOPLE_SORTS / KEY_SORTS                     the fields each table can be sorted by
//   peopleRows(answer, text, sort)               rows of the people table, filtered by text and sorted
//   keyRows(answer, text, sort)                  rows of the keys table
//   usedList(row)                                the last use of each capability of a person, the newest first
//   summaryOf(answer)                            { locked, never, unusedKeys } counts for the line on top
//   agoText(t, now, epoch) / durationText(t, s)  "3 h", "ago 3 days", through the translator t(key, params) of the screen (a key 'users.x' is of the area users)
//   reportText(answer, t)                        the report as plain text (to copy)
//   isNarrowScreen(env)                          true under 900 px wide: LAYOUT only (one open rule, folded filters); no feature depends on it

import { BASE_ROLES } from './access-people-view.js'
import { dateText, clockText } from './access-review-view.js'

export const PEOPLE_SORTS = Object.freeze(['name', 'role', 'last_login', 'pin_age', 'lock', 'last_use'])
export const KEY_SORTS = Object.freeze(['name', 'state', 'last_use', 'idle', 'created', 'reach'])
export const NARROW_QUERY = '(max-width: 900px)'

const MIN = 60
const HOUR = 3600
const DAY = 86400

function list(x) {
	return Array.isArray(x) ? x.slice() : []
}

function num(x) {
	return typeof x === 'number' && Number.isFinite(x) ? x : null
}

function has(haystack, needle) {
	return String(haystack || '').toLowerCase().includes(needle)
}

function compare(a, b) {
	if (a === b) return 0
	if (a === null || a === undefined) return -1
	if (b === null || b === undefined) return 1
	return typeof a === 'string' ? a.localeCompare(b, undefined, { sensitivity: 'base' }) : a - b
}

function sortRows(rows, sort, valueOf) {
	const dir = sort && sort.dir === 'desc' ? -1 : 1
	const field = sort && sort.field
	return rows.map((r, i) => ({ r, i })).sort((x, y) => (compare(valueOf(x.r, field), valueOf(y.r, field)) * dir) || (x.i - y.i)).map((x) => x.r)
}

export function usedList(row) {
	const used = (row && row.lastUsed) || {}
	return Object.keys(used).map((c) => ({ capability: c, at: used[c] })).sort((a, b) => (b.at - a.at) || a.capability.localeCompare(b.capability))
}

function personRow(p) {
	const locked = (p.locked_for_s | 0) > 0
	const lastLogin = num(p.last_login)
	return {
		name: String(p.name),
		role: String(p.role || ''),
		customRole: !BASE_ROLES.includes(p.role),
		groups: list(p.groups),
		profiles: list(p.profiles),
		governed: !!p.governed,
		lastLogin,
		neverSignedIn: lastLogin === null,
		sessions: p.sessions | 0,
		pinAgeDays: num(p.pin_age_days),
		locked,
		lockedFor: locked ? p.locked_for_s | 0 : 0,
		lastUse: num(p.last_use),
		lastUsed: p.last_used && typeof p.last_used === 'object' ? Object.assign({}, p.last_used) : {}
	}
}

const PERSON_VALUE = {
	name: (r) => r.name,
	role: (r) => r.role,
	last_login: (r) => r.lastLogin,
	pin_age: (r) => r.pinAgeDays,
	lock: (r) => r.lockedFor,
	last_use: (r) => r.lastUse
}

export function peopleRows(answer, text, sort) {
	const needle = String(text || '').trim().toLowerCase()
	const rows = list(answer && answer.people).map(personRow)
		.filter((r) => !needle || has(r.name, needle) || has(r.role, needle) || r.groups.some((g) => has(g, needle)) || r.profiles.some((g) => has(g, needle)))
	return sortRows(rows, sort || { field: 'name', dir: 'asc' }, (r, f) => (PERSON_VALUE[f] || PERSON_VALUE.name)(r))
}

function keyRow(k) {
	const lastUse = num(k.last_used)
	return {
		id: String(k.id || ''),
		name: String(k.name || ''),
		enabled: k.enabled !== false,
		created: num(k.created),
		lastUse,
		unused: lastUse === null,
		idleDays: num(k.idle_days),
		uses: k.uses | 0,
		breadth: k.breadth | 0,
		expires: num(k.expires)
	}
}

const KEY_VALUE = {
	name: (r) => r.name,
	state: (r) => (r.enabled ? 1 : 0),
	last_use: (r) => r.lastUse,
	idle: (r) => r.idleDays,
	created: (r) => r.created,
	reach: (r) => r.breadth
}

export function keyRows(answer, text, sort) {
	const needle = String(text || '').trim().toLowerCase()
	const rows = list(answer && answer.keys).map(keyRow).filter((r) => !needle || has(r.name, needle))
	return sortRows(rows, sort || { field: 'name', dir: 'asc' }, (r, f) => (KEY_VALUE[f] || KEY_VALUE.name)(r))
}

export function summaryOf(answer) {
	const people = list(answer && answer.people).map(personRow)
	return { locked: people.filter((p) => p.locked).length, never: people.filter((p) => p.neverSignedIn).length, unusedKeys: list(answer && answer.keys).map(keyRow).filter((k) => k.unused).length }
}

export function durationText(t, seconds) {
	const s = Math.max(0, Math.round(seconds))
	if (s < MIN) return t('report_dur_s', { n: s })
	if (s < HOUR) return t('report_dur_min', { n: Math.round(s / MIN) })
	if (s < DAY) return t('report_dur_h', { n: Math.floor(s / HOUR) })
	const days = Math.floor(s / DAY)
	return t('report_dur_d', { n: days }, days)
}

export function agoText(t, now, epoch) {
	if (epoch === null || epoch === undefined) return t('common_never')
	const s = Math.max(0, now - epoch)
	return s < MIN ? t('report_now') : t('report_ago', { time: durationText(t, s) })
}

export function reportText(answer, t) {
	const now = (answer && answer.generated) | 0
	const lines = [t('report_title') + ' (' + clockText(now) + ')', '', t('report_people_title')]
	peopleRows(answer, '', { field: 'name', dir: 'asc' }).forEach((r) => {
		const role = r.customRole ? r.role : t('users.role_' + r.role)
		const pin = r.pinAgeDays === null ? '-' : t('report_pin_days', { n: r.pinAgeDays }, r.pinAgeDays)
		const lock = r.locked ? t('report_locked', { time: durationText(t, r.lockedFor) }) : '-'
		lines.push([r.name, role, agoText(t, now, r.lastLogin), pin, lock, r.lastUse === null ? '-' : agoText(t, now, r.lastUse)].join(' | '))
	})
	lines.push('', t('report_keys_title'))
	keyRows(answer, '', { field: 'name', dir: 'asc' }).forEach((k) => {
		lines.push([k.name, t(k.enabled ? 'report_key_active' : 'report_key_suspended'), agoText(t, now, k.lastUse), k.idleDays === null ? '-' : t('report_idle_days', { n: k.idleDays }, k.idleDays), k.created === null ? '-' : dateText(k.created)].join(' | '))
	})
	return lines.join('\n')
}

// the translator of the report components: rt('report_title') is of the area `access`, rt('users.role_admin') of the area `users` (the names of the base roles)
export const translatorMixin = {
	methods: {
		// with `count` the text has a singular and a plural form (the count decides which one)
		rt(key, params, count) {
			const full = key.startsWith('users.') ? 'plugins.WorkshopService.' + key : 'plugins.WorkshopService.access.' + key
			return count === undefined ? this.$t(full, params) : this.$tc(full, count, params)
		}
	}
}

export function isNarrowScreen(env) {
	try {
		const w = env || (typeof window !== 'undefined' ? window : null)
		return !!(w && w.matchMedia && w.matchMedia(NARROW_QUERY).matches)
	} catch (e) {
		return false
	}
}
