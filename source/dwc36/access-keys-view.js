'use strict'

// What the screen Access > Keys shows (DISENO-PANTALLAS 2.4, step 7), from the answers of the service, as plain data. Pure: no calls, no clock of its own
// (`now` is an argument), nothing is decided here that the service does not say. Three answers are read:
//   keys.list      { keys: [{ id, name, created, last_used, uses, expires, enabled, kinds, ops, deny, allowed_ops, ... }], presets, kinds, max, cap_prefix }
//   access.report  { generated, damaged, keys: [{ id, name, enabled, created, last_used, uses, expires, breadth, idle_days }], people, locked }
//   access.review  { generated, damaged, findings: [{ code, severity, subject, params, message }], counts, limits: { unused_key_days, wide_key_breadth, ... } }
// Times are epoch seconds. A key is never shown by its value (the service does not send it). The "unused" mark is the review finding `key_wide_unused` of
// that key (params.id), never a count made here: without the finding there is no mark.
//
//   keyRows(list, report, review, text)      the rows of the table, in the order of the service
//   keyCard(row)                             the entries of one key by kind (classes, capabilities, other operations, denied)
//   unusedFinding(review, id)                the finding of a wide key that is not used, or null
//   dateOf(epoch)                            'YYYY-MM-DD HH:MM' in local time ('' without a value)
//   lastUseOf(row)                           { never, today, days } for the cell of the last use
//   expiryOf(row, now)                       { none, expired, soon, at } the expiry as the key stores it
//   statusOf(row, now)                       'ended' | 'off' | 'active': THE state of a key, one word for every screen (Access > Keys, Security > Report). A key past
//                                            its expiry is 'ended' (shown as Expired) whatever its switch says (the service refuses it); then a switched-off key is 'off'
//   canOf(row)                               { classes, ops, caps, wide } the parts of the ONE phrase of what a key can do ("Read, Move: 112 operations")

export const STATUS = Object.freeze({ active: 'active', off: 'off', ended: 'ended' })
export const UNUSED_FINDING = 'key_wide_unused'
export const SHOWN_OPS = 12
export const SOON_S = 7 * 86400   // an expiry within a week is flagged "expires soon"

const list = x => (Array.isArray(x) ? x : [])

function pad(n) {
	return n < 10 ? '0' + n : String(n)
}

export function dateOf(epoch) {
	if (!epoch && epoch !== 0) return ''
	const d = new Date(Number(epoch) * 1000)
	if (isNaN(d.getTime())) return ''
	return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate()) + ' ' + pad(d.getHours()) + ':' + pad(d.getMinutes())
}

export function unusedFinding(review, id) {
	const found = list(review && review.findings).find(f => f && f.code === UNUSED_FINDING && f.params && String(f.params.id) === String(id))
	return found || null
}

// the entries of a key by kind: `cap:<id>` entries are capabilities, the rest of `ops` are single operations or patterns
export function keyCard(row) {
	const caps = row.ops.filter(e => e.startsWith(row.capPrefix))
	return {
		classes: row.kinds.slice(),
		capabilities: caps,
		operations: row.ops.filter(e => !e.startsWith(row.capPrefix)),
		denied: row.deny.slice()
	}
}

export function keyRows(keysAnswer, report, review, text, now) {
	const answer = keysAnswer || {}
	const capPrefix = String(answer.cap_prefix || 'cap:')
	const byId = {}
	list(report && report.keys).forEach(k => { if (k && k.id !== undefined) byId[String(k.id)] = k })
	const wide = review && review.limits ? Number(review.limits.wide_key_breadth) : 0
	const q = String(text || '').trim().toLowerCase()
	const rows = list(answer.keys).filter(k => k && (!q || String(k.name || '').toLowerCase().includes(q))).map(k => {
		const rep = byId[String(k.id)] || null
		const ops = list(k.ops).map(String)
		const allowed = list(k.allowed_ops).map(String)
		const row = {
			id: String(k.id),
			name: String(k.name || ''),
			enabled: k.enabled !== false,
			kinds: list(k.kinds).map(String),
			ops,
			deny: list(k.deny).map(String),
			allowed,
			capPrefix,
			capCount: ops.filter(e => e.startsWith(capPrefix)).length,
			created: k.created || null,
			lastUsed: (rep ? rep.last_used : k.last_used) || null,
			uses: Number(rep ? rep.uses : k.uses) || 0,
			idleDays: rep && rep.idle_days !== undefined ? rep.idle_days : null,
			breadth: rep && rep.breadth !== undefined ? Number(rep.breadth) : list(k.kinds).length + ops.length,
			expires: k.expires || null
		}
		row.wide = wide > 0 && row.breadth >= wide
		row.status = statusOf(row, now)
		row.raw = k
		const f = unusedFinding(review, k.id)
		row.unused = f ? { days: Number(f.params.days) || 0, never: !!f.params.never } : null
		return row
	})
	return rows
}

// the cell of the last use: never, today, or so many days ago (the days come from the report of the service when it has them)
export function lastUseOf(row) {
	if (!row.lastUsed) return { never: true, today: false, days: 0 }
	const days = row.idleDays === null ? 0 : Number(row.idleDays) || 0
	return { never: false, today: days === 0, days }
}

export function expiryOf(row, now) {
	if (!row.expires) return { none: true, expired: false, soon: false, at: '' }
	const expired = Number(row.expires) < Number(now)
	return { none: false, expired, soon: !expired && Number(row.expires) - Number(now) < SOON_S, at: dateOf(row.expires) }
}

// the state of a key, always the same word: an expired key is expired even if its switch is on; without a clock (`now` missing) nothing is called expired
export function statusOf(row, now) {
	const ends = row && row.expires ? Number(row.expires) : 0
	if (ends && now && ends < Number(now)) return STATUS.ended
	return row && row.enabled === false ? STATUS.off : STATUS.active
}

// what a key can do, in parts: the classes in the order of the service, how many operations it may call (allowed_ops: what the service really lets it do,
// api_keys.why_not), how many capabilities it names and whether it is wide (the threshold of the review). The words are put together by the screen.
export function canOf(row) {
	return { classes: row.kinds.slice(), ops: row.allowed.length, caps: row.capCount, wide: !!row.wide }
}
