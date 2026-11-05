'use strict'

// The time range of a search (Activity, Machine history, Consumption history), shaped like the range picker of CloudWatch: a few quick
// ranges, a relative range (the last N minutes / hours / days / weeks / months) and an absolute one (from a date and time to another).
// Pure helpers; RangePicker.vue draws it and the page asks `resolve` for the two moments when it searches.
//
//   value   { type: 'relative', amount, unit }            the last `amount` `unit`s until now (it moves with the clock)
//           { type: 'absolute', from: 'YYYY-MM-DDTHH:MM', to: 'YYYY-MM-DDTHH:MM' }   local time, the end is inclusive to the minute

export const UNITS = ['minutes', 'hours', 'days', 'weeks', 'months']

// the quick ranges, shortest first (the page also keeps "custom" for the other two tabs)
export const QUICK = [
	{ amount: 5, unit: 'minutes' },
	{ amount: 30, unit: 'minutes' },
	{ amount: 1, unit: 'hours' },
	{ amount: 3, unit: 'hours' },
	{ amount: 12, unit: 'hours' },
	{ amount: 1, unit: 'days' },
	{ amount: 3, unit: 'days' },
	{ amount: 1, unit: 'weeks' },
	{ amount: 1, unit: 'months' }
]

export const MAX_AMOUNT = 999

const two = n => String(n).padStart(2, '0')

// 'YYYY-MM-DDTHH:MM' of a Date in local time (what the inputs of date and time hold)
export function localText(d) {
	return d.getFullYear() + '-' + two(d.getMonth() + 1) + '-' + two(d.getDate()) + 'T' + two(d.getHours()) + ':' + two(d.getMinutes())
}

// the Date of a local text 'YYYY-MM-DDTHH:MM' (or only a day: the start of it), or null when it is not one
export function parseLocal(text) {
	const m = /^(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2}))?$/.exec(String(text || '').trim())
	if (!m) return null
	const d = new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]), Number(m[4] || 0), Number(m[5] || 0), 0, 0)
	return d.getFullYear() === Number(m[1]) && d.getMonth() === Number(m[2]) - 1 && d.getDate() === Number(m[3]) ? d : null
}

function back(now, amount, unit) {
	const d = new Date(now.getTime())
	if (unit === 'minutes') d.setMinutes(d.getMinutes() - amount)
	else if (unit === 'hours') d.setHours(d.getHours() - amount)
	else if (unit === 'days') d.setDate(d.getDate() - amount)
	else if (unit === 'weeks') d.setDate(d.getDate() - 7 * amount)
	else d.setMonth(d.getMonth() - amount)
	return d
}

// checks a value; returns { ok: true } or { ok: false, why } (why: 'amount' | 'unit' | 'from' | 'to' | 'order')
export function check(value) {
	const v = value || {}
	if (v.type === 'relative') {
		if (!UNITS.includes(v.unit)) return { ok: false, why: 'unit' }
		const n = Number(v.amount)
		if (!Number.isInteger(n) || n < 1 || n > MAX_AMOUNT) return { ok: false, why: 'amount' }
		return { ok: true }
	}
	if (v.type === 'absolute') {
		const a = parseLocal(v.from)
		const b = parseLocal(v.to)
		if (!a) return { ok: false, why: 'from' }
		if (!b) return { ok: false, why: 'to' }
		if (b.getTime() < a.getTime()) return { ok: false, why: 'order' }
		return { ok: true }
	}
	return { ok: false, why: 'unit' }
}

// the two moments of a value: { from: Date, to: Date } (the end of an absolute range is the end of its last minute), or null
export function resolve(value, now) {
	if (!check(value).ok) return null
	if (value.type === 'relative') {
		const end = now ? new Date(now.getTime()) : new Date()
		return { from: back(end, Number(value.amount), value.unit), to: end }
	}
	const to = parseLocal(value.to)
	to.setSeconds(59, 999)
	return { from: parseLocal(value.from), to }
}

// the same two moments as local texts 'YYYY-MM-DDTHH:MM:SS' (what a search that takes a date and time asks for) and as epoch seconds
export function asTexts(range) {
	const t = d => localText(d) + ':' + two(d.getSeconds())
	return { from: t(range.from), to: t(range.to) }
}

export function asEpoch(range) {
	return { from: Math.floor(range.from.getTime() / 1000), to: Math.floor(range.to.getTime() / 1000) }
}

// the quick range a relative value is, or null
export function quickOf(value) {
	return value && value.type === 'relative' ? QUICK.find(q => q.amount === Number(value.amount) && q.unit === value.unit) || null : null
}

export function relative(amount, unit) {
	return { type: 'relative', amount, unit }
}

// an absolute value from the two local texts, or the day of today when they are empty
export function absolute(from, to) {
	return { type: 'absolute', from, to }
}

export function same(a, b) {
	return JSON.stringify(a) === JSON.stringify(b)
}
