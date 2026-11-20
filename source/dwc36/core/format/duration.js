'use strict'

// ONE rule for every length of time the page shows (design guide, section 11):
//   under 60 s          "N s"
//   under 60 min        "N min"
//   a whole number of hours   "N h"          else   "N h M min"
//   from 48 hours       "N days"
// Pure: durationParts() says what to print, durationText() prints it with the translator it is given
// (t(key, params): keys duration_s, duration_min, duration_h, duration_h_min, duration_days of the page catalogs).

export function durationParts(seconds) {
	const s = Math.max(0, Math.round(Number(seconds) || 0))
	if (s < 60) return { unit: 's', n: s }
	const minutes = Math.floor(s / 60)
	if (minutes < 60) return { unit: 'min', n: minutes }
	const hours = Math.floor(minutes / 60)
	if (hours >= 48) return { unit: 'days', n: Math.floor(hours / 24) }
	const rest = minutes % 60
	return rest ? { unit: 'h_min', n: hours, m: rest } : { unit: 'h', n: hours }
}

export function durationText(seconds, t) {
	const p = durationParts(seconds)
	return t('duration_' + p.unit, p)
}

// "12 s ago": the age of a datum, from the moment it was received (ms) to now (ms); null when it was never received
export function ageSeconds(receivedAt, now) {
	if (!receivedAt) return null
	return Math.max(0, Math.round((now - receivedAt) / 1000))
}
