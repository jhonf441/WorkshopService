'use strict'

// Pure helpers of the read-only screen Security > Review (DISENO-PANTALLAS section 2.7). No imports of the page, no DOM: the components only draw what these
// functions return and a test loads this file in node. The findings come from access.review exactly as the service sorted them (severity, then code, then
// subject) and with the sentence (`message`) the service wrote: this file does not recompute, reorder, translate or invent a finding.
//
// The answer of access.review (dsf/access_ops.py review):
//   { generated: epoch, damaged: bool, findings: [{ code, severity, subject, params, message }], counts: { high, medium, low, info }, high: n,
//     limits: { unused_key_days, admin_login_days, wide_key_breadth } }
//
//   SEVERITIES / SEVERITY_COLORS      the four severities and the color of each chip (one color, one meaning)
//   FINDING_TARGETS                   what object each of the six codes opens: 'profile' | 'person' | 'key'
//   findingRows(answer)               one row per finding, in the order of the service, with the object its button opens
//   severityCounts(answer)            [{ severity, count, color }] for the four chips, from `counts` of the answer (counted from the rows when missing)
//   highCount(answer)                 how many findings are of severity high
//   reviewLimits(answer)              the thresholds the service used, or null
//   clockText(epoch)                  "2026-11-11 10:50" in the time zone of the browser

export const SEVERITIES = Object.freeze(['high', 'medium', 'low', 'info'])
export const SEVERITY_COLORS = Object.freeze({ high: 'error', medium: 'warning', low: 'info', info: '' })

// profile_grants_risk4, deny_never_matches and profile_unattached name a profile; person_without_access and admin_no_recent_login a person; key_wide_unused a key
export const FINDING_TARGETS = Object.freeze({
	profile_grants_risk4: 'profile',
	deny_never_matches: 'profile',
	profile_unattached: 'profile',
	person_without_access: 'person',
	key_wide_unused: 'key',
	admin_no_recent_login: 'person'
})

export const OPEN_LABELS = Object.freeze({ profile: 'review_open_profile', person: 'review_open_person', key: 'review_open_key' })

function severityOf(f) {
	return SEVERITIES.includes(f && f.severity) ? f.severity : 'info'
}

// where the button of a finding goes: the object its `subject` names (a key by its id too, because two keys can share a name)
function targetOf(f) {
	const kind = Object.prototype.hasOwnProperty.call(FINDING_TARGETS, f.code) ? FINDING_TARGETS[f.code] : ''
	if (!kind || !f.subject) return null
	const target = { kind, name: String(f.subject) }
	if (kind === 'key') target.id = String((f.params && f.params.id) || '')
	return target
}

export function findingRows(answer) {
	const list = answer && Array.isArray(answer.findings) ? answer.findings : []
	return list.map((f, i) => {
		const severity = severityOf(f)
		const target = targetOf(f)
		return {
			id: i + ':' + f.code + ':' + f.subject,
			code: String(f.code || ''),
			severity,
			color: SEVERITY_COLORS[severity],
			subject: String(f.subject || ''),
			message: String(f.message || ''),
			target,
			openLabel: target ? OPEN_LABELS[target.kind] : ''
		}
	})
}

export function severityCounts(answer) {
	const given = (answer && answer.counts) || null
	const rows = findingRows(answer)
	return SEVERITIES.map((s) => ({ severity: s, color: SEVERITY_COLORS[s], count: given && Number.isFinite(given[s]) ? given[s] : rows.filter((r) => r.severity === s).length }))
}

export function highCount(answer) {
	return severityCounts(answer).find((c) => c.severity === 'high').count
}

export function reviewLimits(answer) {
	const l = answer && answer.limits
	if (!l || typeof l !== 'object') return null
	return { keyDays: l.unused_key_days | 0, adminDays: l.admin_login_days | 0, breadth: l.wide_key_breadth | 0 }
}

const two = (n) => (n < 10 ? '0' : '') + n

export function clockText(epoch) {
	if (!Number.isFinite(epoch) || epoch <= 0) return ''
	const d = new Date(epoch * 1000)
	return d.getFullYear() + '-' + two(d.getMonth() + 1) + '-' + two(d.getDate()) + ' ' + two(d.getHours()) + ':' + two(d.getMinutes())
}

export function dateText(epoch) {
	return clockText(epoch).slice(0, 10)
}
