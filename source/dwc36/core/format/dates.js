'use strict'

// The service writes moments in three ways; the page keeps ONE: milliseconds since the epoch (or null).
//   toMs(1794944929)               seconds since the epoch (keys, sessions)
//   toMs(1794944929123)            milliseconds (charts)
//   toMs('2026-11-17T14:48:52')    local time of the machine, with 'T' or with a space, with or without seconds
//   toMs('2026-11-17')             that day at 00:00
// Printing is done with the language of DWC: dateTime(ms, locale), date(ms, locale), time(ms, locale); '' for null.
// rangeOfDays(n, now) gives the fixed range { from, to } ('YYYY-MM-DD') the paged lists are asked with.

const LOCAL = /^(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2})(?::(\d{2}))?)?/

export function toMs(value) {
	if (value === null || value === undefined || value === '') return null
	if (typeof value === 'number') {
		if (!isFinite(value) || value <= 0) return null
		return value < 1e11 ? Math.round(value * 1000) : Math.round(value)
	}
	const m = LOCAL.exec(String(value))
	if (!m) return null
	const d = new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]), Number(m[4] || 0), Number(m[5] || 0), Number(m[6] || 0))
	return isNaN(d.getTime()) ? null : d.getTime()
}

const two = n => (n < 10 ? '0' : '') + n

export function dayOf(ms) {
	const d = new Date(ms)
	return d.getFullYear() + '-' + two(d.getMonth() + 1) + '-' + two(d.getDate())
}

function print(ms, locale, options) {
	if (ms === null || ms === undefined) return ''
	try {
		return new Intl.DateTimeFormat(locale || 'en', options).format(new Date(ms))
	} catch (e) {
		return new Date(ms).toISOString().slice(0, 16).replace('T', ' ')
	}
}

export const dateTime = (ms, locale) => print(ms, locale, { year: 'numeric', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
export const date = (ms, locale) => print(ms, locale, { year: 'numeric', month: 'short', day: 'numeric' })
export const time = (ms, locale) => print(ms, locale, { hour: '2-digit', minute: '2-digit', second: '2-digit' })

// the last `days` days up to today, as the lists take them (dates, both inclusive)
export function rangeOfDays(days, now) {
	const end = now || Date.now()
	return { from: dayOf(end - (Math.max(1, days) - 1) * 86400000), to: dayOf(end) }
}
