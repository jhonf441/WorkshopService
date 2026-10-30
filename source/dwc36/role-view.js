'use strict'

// What each ROLE sees on a page (F3-V of the redesign, 2026-10-21). The service applies the roles; this file only decides what is
// worth showing, using the same table the service sends in auth.whoami (workshopCan of workshop-auth.js). One rule: while the
// service has not answered (or there are no users yet) everything is shown, hiding is a courtesy and the service decides.
//
//   roleAtLeast('technician')              true when the current role is a technician or an administrator
//   visibleItems(sections)                 the items whose `min` role the person has (an item without `min` is for everybody)
//   pickAllowed(sections, 'crash')         'crash' when the person may see it, else the first section they may see
//
// A role is tested through one operation that only that role and the ones above it can call (RANK_OPS), so the single source of
// truth stays the table of the service (WorkshopService dsf/permissions.py). Pure logic: `can` can be replaced in tests.

import { workshopCan } from './workshop-auth.js'

export const RANK_OPS = { viewer: '', operator: 'light.set', technician: 'settings.set', admin: 'power.off' }

// without a browser (tests, no session yet) workshopCan cannot read the identity: nothing is hidden
function currentCan(op) {
	try {
		return workshopCan(op)
	} catch (e) {
		return true
	}
}

export function roleAtLeast(min, can) {
	const op = RANK_OPS[min]
	if (op === undefined) return false
	return op === '' ? true : (can || currentCan)(op)
}

export function visibleItems(items, can) {
	return (items || []).filter(i => !i.min || roleAtLeast(i.min, can))
}

export function pickAllowed(items, id, can) {
	const ok = visibleItems(items, can)
	if (ok.some(i => i.id === id)) return id
	return ok.length ? ok[0].id : id
}
