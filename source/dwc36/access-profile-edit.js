'use strict'

// Pure helpers of the profile EDITOR (DISENO-PANTALLAS step 3, sections 2.2, 5 and 7). No DOM, no calls: the components draw and call, these functions
// build documents, check them the way the service will, and describe a change. The service is the judge (access.profiles.validate and
// access.profiles.set refuse what is not allowed); the checks here only stop the obvious mistakes before the call and keep the builder from offering a
// stop to a deny rule. A test feeds every document this file builds or refuses to the real service (dsf/test_access_profile_edit_golden.py).
//
//   contextOf(rolesList)                  { caps, byId, stopOps, notDelegable, known } from the answer of roles.list (the one origin of those lists)
//   emptyDoc(name) / cloneDoc(doc) / sameDoc(a, b) / nextRuleId(doc)
//   addRule(doc, decision) / removeRule(doc, i) / moveRule(doc, i, delta) / setRule(doc, i, rule)
//   toggleEntry(rule, entry) / addEntry(rule, entry) / setTargets(rule, list) / setWhen(rule, key, value)    rules are copied, never changed in place
//   offered(ctx, decision)                what the builder offers a rule: { groups, locked } (a deny rule is never offered a stop; nothing undelegable is offered to allow)
//   checkDoc(doc, ctx)                    [{ code, detail, rule, params }] the mistakes the service would refuse (detail is its code) plus 'undelegable'
//   probeVerdict(doc, ctx)                'ok' | the detail of the first mistake (for the cross check with the service)
//   parseJson(text) / buildable(doc)     { doc } or { line }; true when the Builder can draw it
//   duplicateDoc(doc, ctx)                a copy of a base profile that a custom profile may hold (no tiers, no undelegable, at most 100 entries a rule)
//   riskOf(ctx)                           function(entry) -> 1..4 | 0
//   changeSize(diff)                        { gains, loses } entries an allow rule gains or loses (a deny rule the other way round)
//   canReview(state)                      true when "Review changes" may open (nothing refused, validated, changed)

import { entryCovers, capabilityGroups } from './access-profile-view.js'

export const SCHEMA_VERSION = 1
export const NAME_RE = /^[A-Za-z][A-Za-z0-9_.-]{0,63}$/
export const RULE_ID_RE = /^[A-Za-z0-9]{1,64}$/
export const OP_RE = /^[a-z0-9_.*?-]{1,64}$/
export const NS_OP_RE = /^([a-z][a-z0-9_]{0,31}):([a-z0-9_.*?-]{1,64})$/
export const UI_OP_RE = /^ui:([a-z][a-z0-9_]{0,31}|\*):open$/
// the things a call can be about, by plugin: [plugin, [types]] (the table of dsf/access_targets.py, which a test compares with this one)
export const TARGET_KINDS = Object.freeze([
	['camera', ['camera', 'media', 'timelapse']],
	['lights', ['scene', 'zone', 'strip', 'state', 'pin']],
	['printing', ['recipe', 'pellet', 'bedzone', 'file', 'folder']],
	['workbench', ['interrupted']],
	['power', ['meter', 'timer']],
	['vision', ['path']]
])
export const TARGET_ID_RE = /^[A-Za-z0-9_.\-/%]{1,90}$/
export const TARGET_RE = /^workshop:([a-z0-9_]{1,32}|\*):([A-Za-z0-9_.\-/*%]{1,100})$/
export const CONDITION_KEYS = Object.freeze(['mode', 'job_running', 'machine_on', 'via', 'risk_max'])
export const MODES = Object.freeze(['laser', 'cnc', 'fff'])
export const VIAS = Object.freeze(['session', 'key', 'macro', 'local'])
export const MODE_VARIABLE = '${person.modes}'
export const MAX_RULES = 50
export const MAX_ENTRIES = 100
const RULE_FIELDS = ['id', 'decision', 'operations', 'targets', 'when']
const DOC_FIELDS = ['version', 'name', 'rules']
const TIME_WORDS = ['time', 'date', 'hour', 'day', 'week', 'month', 'year', 'expir', 'ip', 'addr', 'cidr', 'schedule', 'until', 'before', 'after', 'mfa']

const list = v => (Array.isArray(v) ? v : [])
export const cloneDoc = doc => JSON.parse(JSON.stringify(doc === undefined ? null : doc))

function canonical(v) {
	if (Array.isArray(v)) return v.map(canonical)
	if (v && typeof v === 'object') return Object.keys(v).sort().reduce((o, k) => { o[k] = canonical(v[k]); return o }, {})
	return v
}
export const sameDoc = (a, b) => JSON.stringify(canonical(a === undefined ? null : a)) === JSON.stringify(canonical(b === undefined ? null : b))

export function emptyDoc(name) {
	return { version: SCHEMA_VERSION, name: String(name || ''), rules: [] }
}

function glob(pattern, text) {
	if (pattern.indexOf('*') < 0 && pattern.indexOf('?') < 0) return pattern === text
	return new RegExp('^' + pattern.replace(/[.+^${}()|[\]\\]/g, '\\$&').replace(/\*/g, '.*').replace(/\?/g, '.') + '$').test(text)
}

export function contextOf(answer) {
	const a = answer || {}
	const caps = list(a.capabilities)
	const byId = {}
	const known = []
	caps.forEach(c => {
		byId[c.id] = c
		list(c.ops).forEach(o => { if (known.indexOf(o) < 0) known.push(o) })
	})
	return { caps, byId, stopOps: list(a.stop_ops), notDelegable: list(a.not_delegable), known, categories: list(a.categories) }
}

// ---- building ----

export function nextRuleId(doc) {
	const used = list(doc && doc.rules).map(r => r.id)
	let n = used.length + 1
	while (used.indexOf('Rule' + n) >= 0) n++
	return 'Rule' + n
}

export function addRule(doc, decision) {
	const d = cloneDoc(doc)
	d.rules.push({ id: nextRuleId(d), decision: decision === 'deny' ? 'deny' : 'allow', operations: [] })
	return d
}

export function removeRule(doc, i) {
	const d = cloneDoc(doc)
	d.rules.splice(i, 1)
	return d
}

export function moveRule(doc, i, delta) {
	const d = cloneDoc(doc)
	const j = i + delta
	if (i < 0 || j < 0 || i >= d.rules.length || j >= d.rules.length) return d
	const r = d.rules[i]
	d.rules[i] = d.rules[j]
	d.rules[j] = r
	return d
}

export function setRule(doc, i, rule) {
	const d = cloneDoc(doc)
	d.rules[i] = cloneDoc(rule)
	return d
}

// the order of the fields of a rule is always the same, and an empty list or an empty condition is left out
function tidy(rule) {
	const out = { id: rule.id, decision: rule.decision, operations: list(rule.operations).slice() }
	if (list(rule.targets).length) out.targets = rule.targets.slice()
	if (rule.when && Object.keys(rule.when).length) out.when = cloneDoc(rule.when)
	return out
}

export function addEntry(rule, entry) {
	const e = String(entry || '').trim()
	const r = tidy(rule)
	if (e && r.operations.indexOf(e) < 0) r.operations.push(e)
	return r
}

export function toggleEntry(rule, entry) {
	const r = tidy(rule)
	const at = r.operations.indexOf(entry)
	if (at >= 0) r.operations.splice(at, 1)
	else r.operations.push(entry)
	return r
}

export function setTargets(rule, targets) {
	const r = tidy(rule)
	const t = list(targets).map(x => String(x).trim()).filter(Boolean)
	if (t.length) r.targets = t
	else delete r.targets
	return r
}

// value undefined (or an empty list) removes the condition
export function setWhen(rule, key, value) {
	const r = tidy(rule)
	const w = Object.assign({}, r.when || {})
	if (value === undefined || value === null || (Array.isArray(value) && !value.length)) delete w[key]
	else w[key] = value
	if (Object.keys(w).length) r.when = w
	else delete r.when
	return r
}

// ---- what the builder offers ----

// The capabilities by category with what each rule may take. A deny rule is never offered a stop (deniable false); nothing undelegable is offered
// to anything. `locked` says why a row has no box: 'admin' (nobody can be granted it) or 'stop' (a stop cannot be denied).
export function offered(ctx, decision) {
	const groups = capabilityGroups(ctx.caps, ctx.categories, null)
	return groups.map(g => ({
		id: g.id,
		title: g.title,
		items: g.items.map(i => Object.assign({}, i, { lock: i.locked ? 'admin' : (decision === 'deny' && i.alwaysAllowed ? 'stop' : '') }))
	}))
}

// ---- the checks ----

// true when a deny entry covers stopping and nothing else (the rule of access_profile._stop_only), or is a capability that holds a stop
export function stopDenied(entry, ctx) {
	if (entry.indexOf('cap:') === 0) {
		const c = ctx.byId[entry.slice(4)]
		return !!c && c.deniable === false
	}
	if (entry.indexOf('tier:') === 0) return false
	const hit = ctx.known.concat(ctx.stopOps.filter(o => ctx.known.indexOf(o) < 0)).filter(o => entryCovers(entry, o))
	return hit.length > 0 && hit.every(o => ctx.stopOps.indexOf(o) >= 0)
}

// true when nothing an allow entry covers can be granted by a custom profile
export function undelegable(entry, ctx) {
	if (entry.indexOf('cap:') === 0) {
		const c = ctx.byId[entry.slice(4)]
		return !!c && c.delegable === false
	}
	if (entry.indexOf('tier:') === 0 || entry.indexOf(':') >= 0) return false
	const locked = o => ctx.notDelegable.some(p => glob(p, o))
	if (entry.indexOf('*') < 0 && entry.indexOf('?') < 0) return locked(entry)
	const hit = ctx.known.filter(o => entryCovers(entry, o))
	return hit.length > 0 && hit.every(locked)
}

function entryIssue(entry, ctx) {
	if (typeof entry !== 'string') return 'invalid_operation'
	if (entry.indexOf('cap:') === 0) return ctx.byId[entry.slice(4)] ? '' : 'unknown_capability'
	if (entry.indexOf('tier:') === 0) return 'reserved_namespace'
	if (OP_RE.test(entry) || UI_OP_RE.test(entry)) return ''
	const m = NS_OP_RE.exec(entry)
	if (!m) return 'invalid_operation'
	return m[1] === 'cap' || m[1] === 'tier' ? 'reserved_namespace' : ''
}

function conditionIssues(when) {
	if (!when || typeof when !== 'object' || Array.isArray(when)) return [{ detail: 'invalid_condition', key: '' }]
	const out = []
	Object.keys(when).forEach(k => {
		const v = when[k]
		if (CONDITION_KEYS.indexOf(k) < 0) {
			const low = k.toLowerCase()
			out.push({ detail: TIME_WORDS.some(w => low.indexOf(w) >= 0) ? 'forbidden_condition' : 'invalid_condition', key: k })
		} else if (k === 'job_running' || k === 'machine_on') {
			if (typeof v !== 'boolean') out.push({ detail: 'invalid_condition', key: k })
		} else if (k === 'risk_max') {
			if (typeof v !== 'number' || !Number.isInteger(v) || v < 1 || v > 4) out.push({ detail: 'invalid_condition', key: k })
		} else {
			const ok = k === 'mode' ? MODES : VIAS
			if (!Array.isArray(v) || !v.length || v.length > 8 || v.some(x => typeof x !== 'string' || (ok.indexOf(x) < 0 && !(k === 'mode' && x === MODE_VARIABLE)))) out.push({ detail: 'invalid_condition', key: k })
		}
	})
	return out
}

// Every mistake of a document, in the order of the document. code is the key of the sentence (area `access`, check_<code>); detail the code the
// service answers with (`undelegable` is only ours: the service accepts it and its evaluator never grants it).
export function checkDoc(doc, ctx) {
	const out = []
	const add = (code, detail, rule, params) => out.push({ code, detail, rule: rule || '', params: Object.assign({ rule: rule || '' }, params || {}) })
	if (!doc || typeof doc !== 'object' || Array.isArray(doc)) return [{ code: 'document', detail: 'invalid_document', rule: '', params: {} }]
	Object.keys(doc).filter(k => DOC_FIELDS.indexOf(k) < 0).forEach(k => add('field', 'unknown_field', '', { field: k }))
	if (doc.version !== SCHEMA_VERSION) add('version', 'invalid_version')
	if (typeof doc.name !== 'string' || !NAME_RE.test(doc.name)) add('name', 'invalid_name')
	const rules = doc.rules
	if (!Array.isArray(rules) || !rules.length) {
		add('rules_empty', 'invalid_document')
		return out
	}
	if (rules.length > MAX_RULES) add('rules_max', 'too_many', '', { max: MAX_RULES })
	const seen = []
	rules.forEach((r, i) => {
		const where = r && typeof r.id === 'string' && r.id ? r.id : String(i + 1)
		if (!r || typeof r !== 'object') return add('document', 'invalid_rule', where)
		Object.keys(r).filter(k => RULE_FIELDS.indexOf(k) < 0).forEach(k => add('field', 'unknown_field', where, { field: k }))
		if (typeof r.id !== 'string' || !RULE_ID_RE.test(r.id)) add('rule_id', 'invalid_id', where)
		else if (seen.indexOf(r.id) >= 0) add('rule_dup', 'duplicate_id', where)
		seen.push(r.id)
		if (r.decision !== 'allow' && r.decision !== 'deny') add('decision', 'invalid_decision', where)
		const ops = r.operations
		if (!Array.isArray(ops) || !ops.length) add('ops_empty', 'invalid_rule', where)
		else if (ops.length > MAX_ENTRIES) add('ops_max', 'invalid_rule', where, { max: MAX_ENTRIES })
		list(ops).forEach(e => {
			const bad = entryIssue(e, ctx)
			if (bad) return add('entry', bad, where, { entry: String(e) })
			if (r.decision === 'deny' && stopDenied(e, ctx)) add('stop_deny', 'stop_deny', where, { entry: e })
			else if (r.decision === 'allow' && undelegable(e, ctx)) add('undelegable', 'undelegable', where, { entry: e })
		})
		if ('targets' in r) {
			if (!Array.isArray(r.targets) || !r.targets.length || r.targets.length > MAX_ENTRIES) add('target_form', 'invalid_rule', where)
			else r.targets.forEach(t => { if (typeof t !== 'string' || !(t === '*' || TARGET_RE.test(t))) add('target_form', 'invalid_target', where, { entry: String(t) }) })
		}
		if ('when' in r) conditionIssues(r.when).forEach(c => add(c.detail === 'forbidden_condition' ? 'when_forbidden' : 'when_invalid', c.detail, where, { key: c.key }))
	})
	return out
}

export function probeVerdict(doc, ctx) {
	const first = checkDoc(doc, ctx)[0]
	return first ? first.detail : 'ok'
}

// ---- JSON ----

// true when the Builder can draw the document (rules are objects with a list of operations); anything else stays in the JSON until it is fixed
export function buildable(doc) {
	return !!doc && typeof doc === 'object' && !Array.isArray(doc) && Array.isArray(doc.rules) &&
		doc.rules.every(r => r && typeof r === 'object' && !Array.isArray(r) && Array.isArray(r.operations) && r.operations.every(e => typeof e === 'string') &&
			(r.targets === undefined || (Array.isArray(r.targets) && r.targets.every(t => typeof t === 'string'))) && (r.when === undefined || (r.when && typeof r.when === 'object' && !Array.isArray(r.when))))
}

export function parseJson(text) {
	try {
		return { doc: JSON.parse(String(text)) }
	} catch (e) {
		const msg = String((e && e.message) || '')
		const at = /\(line (\d+) column/.exec(msg)
		if (at) return { line: Number(at[1]) }
		return { line: firstBadLine(String(text)) }
	}
}

// the engine does not always say where: the first line whose addition makes the text wrong rather than merely unfinished
function firstBadLine(text) {
	const lines = text.split('\n')
	for (let k = 1; k <= lines.length; k++) {
		const prefix = lines.slice(0, k).join('\n')
		try {
			JSON.parse(prefix)
			return Math.min(k + 1, lines.length) // a complete value, so what follows it is the mistake
		} catch (e) {
			const m = String((e && e.message) || '')
			const pos = /position (\d+)/.exec(m)
			const unfinished = /end of (json )?(input|data)|unterminated/i.test(m) || (pos && Number(pos[1]) >= prefix.length)
			if (!unfinished) return k
		}
	}
	return lines.length
}

// ---- duplicating a base profile ----

// A base profile lists operations by name (hundreds), with the escalation tiers; a custom profile keeps at most 100 entries a rule, no tier, and what is
// not delegable cannot be granted. The copy swaps the names a capability covers entirely for `cap:<id>`, drops what a custom profile cannot hold and
// leaves the rest as it was; the screen asks the service to validate the copy before anything is saved.
export function duplicateDoc(doc, ctx) {
	const out = emptyDoc('')
	list(doc && doc.rules).forEach(r => {
		let ops = list(r.operations).filter(e => e.indexOf('tier:') !== 0)
		if (ops.length > MAX_ENTRIES) {
			const caps = []
			ctx.caps.forEach(c => {
				const pats = list(c.ops)
				if (c.delegable !== false && pats.length && pats.every(p => ops.some(e => entryCovers(e, p)))) caps.push(c)
			})
			const covered = o => caps.some(c => list(c.ops).indexOf(o) >= 0)
			ops = caps.map(c => 'cap:' + c.id).concat(ops.filter(o => !covered(o) && !undelegable(o, ctx)))
		}
		ops = ops.filter(o => !undelegable(o, ctx))
		if (!ops.length) return
		out.rules.push(tidy(Object.assign({}, cloneDoc(r), { operations: ops })))
	})
	return out
}

// ---- describing a change ----

export function riskOf(ctx) {
	return entry => {
		if (typeof entry !== 'string') return 0
		if (entry.indexOf('cap:') === 0) return ((ctx.byId[entry.slice(4)] || {}).risk) | 0
		let risk = 0
		ctx.caps.forEach(c => {
			if (list(c.ops).some(o => entryCovers(entry, o)) && c.risk > risk) risk = c.risk
		})
		return risk
	}
}

export function changeSize(diff) {
	let gains = 0
	let loses = 0
	list(diff && diff.rules).forEach(r => {
		const allow = (r.after || r.before || {}).decision === 'allow'
		const added = r.operations.added.length
		const removed = r.operations.removed.length
		if (allow) { gains += added; loses += removed } else { gains += removed; loses += added }
	})
	return { gains, loses }
}

// `s`: { issues, refused, validating, valid, changed, damaged, busy }
export function canReview(s) {
	return !!s && !s.damaged && !s.busy && !s.refused && !s.validating && !!s.valid && !!s.changed && !(s.issues && s.issues.length)
}
