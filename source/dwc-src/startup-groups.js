'use strict'

// Machine setup card (StartupMaster.vue): how the rows are grouped and measured. Pure functions, no Vue, so a test can feed them
// every case. The same file is in both page trees (dwc-src and dwc36).

const DEFS = [
	{ id: 'pending', icon: 'mdi-alert-circle-outline', color: 'warning', test: r => !!r.entry && r.entry.pending > 0 },
	{ id: 'unchecked', icon: 'mdi-help-circle-outline', color: 'grey', test: r => !r.entry },
	{ id: 'ready', icon: 'mdi-check-circle-outline', color: 'success', test: r => !!r.entry && !(r.entry.pending > 0) }
];

// Pending first (what the person has to do), then what was never checked, then what is ready. Empty groups are left out.
// Without a session nothing is known about any row: one group "unchecked" holds them all.
export function buildGroups(rows, needsLogin) {
	if (needsLogin) {
		return rows.length ? [Object.assign({}, DEFS[1], { rows: rows.slice() })] : [];
	}
	return DEFS.map(d => Object.assign({}, d, { rows: rows.filter(d.test) })).filter(g => g.rows.length);
}

// Steps already done and the share of them, 0..100 (a report with a pending count above its total does not go negative).
export function doneSteps(entry) {
	return entry ? Math.max(0, (entry.total || 0) - (entry.pending || 0)) : 0;
}

export function donePercent(entry) {
	return entry && entry.total > 0 ? Math.min(100, Math.round(100 * doneSteps(entry) / entry.total)) : 0;
}
