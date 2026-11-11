'use strict'

// The difference between two states of an access object, for the one dialog that shows "before / after" (DISENO-PANTALLAS sections 2.2, 2.5).
// Pure: it compares two plain values and answers lists; it is presentation, never a rule of access (the service decides and refuses).
//
//   diffProfile(before, after, options)   two profile documents {version, name, rules: [{id, decision, operations, targets, when}]}
//                                         -> { name, rules: [{ id, status, before, after, decisionChanged, operations, targets, when }], added, removed,
//                                              changed, unchanged, hasChanges, nameChanged, highestRisk }
//                                         status: 'added' | 'removed' | 'changed' | 'same'; operations / targets: { added: [], removed: [] };
//                                         when: { added: [keys], removed: [keys], changed: [keys] }
//   nextVersion(versions, max)            the version a save would create and the one it would drop: { n, drops }  (versions: [{ n, active }])
//   diffAttachment(before, after)         { profiles, groups, ceiling } as the service keeps them (access.person.get / groups.get):
//                                         -> { profiles: {added, removed}, groups: {added, removed}, ceiling: { before, after, changed }, hasChanges }
//   diffCeiling(before, after)            the ceiling alone: { before, after, changed }
//   diffList(before, after)               { added, removed } of two lists, in the order they come

function list(v) {
	return Array.isArray(v) ? v : []
}

export function diffList(before, after) {
	const b = list(before)
	const a = list(after)
	return { added: a.filter(x => b.indexOf(x) < 0), removed: b.filter(x => a.indexOf(x) < 0) }
}

function same(a, b) {
	return JSON.stringify(a === undefined ? null : a) === JSON.stringify(b === undefined ? null : b)
}

function whenDiff(before, after) {
	const b = before && typeof before === 'object' ? before : {}
	const a = after && typeof after === 'object' ? after : {}
	const keys = Object.keys(a).concat(Object.keys(b)).filter((k, i, all) => all.indexOf(k) === i)
	return {
		added: keys.filter(k => !(k in b) && k in a),
		removed: keys.filter(k => k in b && !(k in a)),
		changed: keys.filter(k => k in b && k in a && !same(b[k], a[k]))
	}
}

function ruleDiff(b, a) {
	const row = { id: (a || b).id, before: b || null, after: a || null, decisionChanged: false, operations: { added: [], removed: [] }, targets: { added: [], removed: [] }, when: { added: [], removed: [], changed: [] } }
	if (!b) {
		row.status = 'added'
		row.operations.added = list(a.operations).slice()
		row.targets.added = list(a.targets).slice()
		row.when.added = Object.keys(a.when || {})
		return row
	}
	if (!a) {
		row.status = 'removed'
		row.operations.removed = list(b.operations).slice()
		row.targets.removed = list(b.targets).slice()
		row.when.removed = Object.keys(b.when || {})
		return row
	}
	row.decisionChanged = b.decision !== a.decision
	row.operations = diffList(b.operations, a.operations)
	row.targets = diffList(b.targets, a.targets)
	row.when = whenDiff(b.when, a.when)
	const touched = row.decisionChanged || row.operations.added.length || row.operations.removed.length || row.targets.added.length || row.targets.removed.length ||
		row.when.added.length || row.when.removed.length || row.when.changed.length
	row.status = touched ? 'changed' : 'same'
	return row
}

// The rules are matched by their id (a rule keeps its name when it is edited). `riskOf(entry)`, when given, returns 1..4 for an operations entry;
// highestRisk is then the highest risk among the entries an allow rule gains (0 when none).
export function diffProfile(before, after, options) {
	const b = before && typeof before === 'object' ? before : null
	const a = after && typeof after === 'object' ? after : null
	const bRules = list(b && b.rules)
	const aRules = list(a && a.rules)
	const rows = []
	aRules.forEach(r => rows.push(ruleDiff(bRules.find(x => x.id === r.id) || null, r)))
	bRules.forEach(r => {
		if (!aRules.some(x => x.id === r.id)) rows.push(ruleDiff(r, null))
	})
	const count = s => rows.filter(r => r.status === s).length
	const out = {
		name: (a && a.name) || (b && b.name) || '',
		nameChanged: !!(a && b && a.name !== b.name),
		rules: rows,
		added: count('added'),
		removed: count('removed'),
		changed: count('changed'),
		unchanged: count('same'),
		highestRisk: 0
	}
	out.hasChanges = out.added + out.removed + out.changed > 0 || out.nameChanged
	const riskOf = options && options.riskOf
	if (typeof riskOf === 'function') {
		rows.forEach(r => {
			if (!r.after || r.after.decision !== 'allow') return
			const entries = r.status === 'added' ? list(r.after.operations) : r.operations.added
			entries.forEach(e => {
				const v = Number(riskOf(e)) || 0
				if (v > out.highestRisk) out.highestRisk = v
			})
		})
	}
	return out
}

// The service keeps up to `max` versions and numbers the next one after the highest number ever used among the kept ones. When the list is full the
// oldest version that is not the active one goes. `versions` is access.profile.versions (newest first, any order is fine).
export function nextVersion(versions, max) {
	const vs = list(versions)
	const n = vs.reduce((m, v) => Math.max(m, Number(v && v.n) || 0), 0) + 1
	let drops = null
	if (max > 0 && vs.length >= max) {
		const old = vs.filter(v => !v.active).sort((x, y) => x.n - y.n)[0]
		drops = old ? old.n : null
	}
	return { n, drops }
}

export function diffCeiling(before, after) {
	const b = before || null
	const a = after || null
	return { before: b, after: a, changed: b !== a }
}

export function diffAttachment(before, after) {
	const b = before || {}
	const a = after || {}
	const out = { profiles: diffList(b.profiles, a.profiles), groups: diffList(b.groups, a.groups), ceiling: diffCeiling(b.ceiling, a.ceiling) }
	out.hasChanges = out.profiles.added.length + out.profiles.removed.length + out.groups.added.length + out.groups.removed.length > 0 || out.ceiling.changed
	return out
}
