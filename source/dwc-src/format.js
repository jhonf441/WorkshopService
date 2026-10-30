'use strict'

// Number and time formatting shared by the process cards of the service page.
import { i18n } from './dwc-host.js'

const T = 'plugins.WorkshopService.servicePage.'

export function sec(v) {
	if (v == null) return ''
	return v < 1 ? Math.round(v * 1000) + ' ms' : (v < 60 ? v.toFixed(1) + ' s' : Math.round(v / 60) + ' min')
}

export function duration(s) {
	if (s == null) return ''
	if (s < 60) return Math.round(s) + ' s'
	if (s < 3600) return Math.round(s / 60) + ' min'
	if (s < 86400) return Math.floor(s / 3600) + ' h ' + Math.round((s % 3600) / 60) + ' min'
	return Math.floor(s / 86400) + ' d ' + Math.round((s % 86400) / 3600) + ' h'
}

export function age(s) {
	s = Math.max(0, Math.round(s))
	if (s < 3) return i18n.t(T + 'now')
	if (s < 60) return i18n.t(T + 'ago_t', { t: s + ' s' })
	if (s < 3600) return i18n.t(T + 'ago_t', { t: Math.round(s / 60) + ' min' })
	if (s < 86400) return i18n.t(T + 'ago_t', { t: Math.floor(s / 3600) + ' h ' + Math.round((s % 3600) / 60) + ' min' })
	return i18n.t(T + 'ago_n_days', { n: Math.round(s / 86400) })
}

// Heartbeat pace: average interval over the expected one (1 = on time).
export function rhythm(p) {
	if (!p || p.interval_avg == null || !p.expected_s) return null
	const r = p.interval_avg / p.expected_s
	return { ratio: r, pct: Math.round(r * 100), color: r <= 1.2 ? 'success' : (r <= 2 ? 'warning' : 'error') }
}
