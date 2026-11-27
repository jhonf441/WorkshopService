'use strict'

// The place of the page lives in the address (?s=&t=&a=) and nowhere else: this reads it into core/page-state.js and writes it back.
//
//   readPlace()        the place the address means now (an old address included), written into pageState; if the address was an old
//                      or an incomplete one it is replaced by today's form (no step is added to the history)
//   go(place, opts)    go there: a change of section is a step of the history (Back returns), a change of tab or anchor replaces;
//                      opts.replace: never a step (closing a sheet does not leave it behind in the history)
//   hrefOf(place)      the link of a place, for real <a href> (open in a new tab, copy the link)
//
// Back and forward work because the shell calls readPlace() whenever the query of the route changes.

import { query, setQuery, t, te } from '../core/dwc.js'
import { pageState } from '../core/page-state.js'
import { anyDirty, passNextRoute, setPlaceHooks } from '../ui/unsaved-guard.js'
import { placeOf, queryOf, samePlace } from './places.js'

export const PATH = '/Plugins/WorkshopService'

function apply(place) {
	pageState.section = place.s
	pageState.tab = place.t
	pageState.anchor = place.a
	pageState.filter = place.f || ''
	return place
}

export function currentPlace() {
	const here = { s: pageState.section, t: pageState.tab, a: pageState.anchor }
	return pageState.filter ? Object.assign(here, { f: pageState.filter }) : here
}

export function readPlace() {
	const q = query()
	const place = placeOf(q)
	const canonical = queryOf(place)
	const same = Object.keys(canonical).length === Object.keys(q).length && Object.keys(canonical).every(k => String(q[k]) === canonical[k])
	if (!same) setQuery(canonical, false)
	return apply(place)
}

export function go(to, opts) {
	const place = placeOf(queryOf(to))
	const before = currentPlace()
	if (samePlace(place, before)) return place
	// the guard of the page asks before a change of section or tab when an editor holds changes (unsaved-guard.js routeGuard): then the place
	// is written only when the route really changed, never before the answer (to "Keep editing" the page must stay where it is)
	const asks = anyDirty() && !(opts && opts.pass) && (place.s !== before.s || String(place.t || '') !== String(before.t || ''))
	if (opts && opts.pass) passNextRoute()
	const done = setQuery(queryOf(place), !(opts && opts.replace) && place.s !== before.s)
	if (asks && done && typeof done.then === 'function') {
		done.then(() => apply(place), () => {})
		return place
	}
	return apply(place)
}

// the place of the page for the guard: where an editor got dirty, how a person reads it, and the way back to it
setPlaceHooks({
	place: currentPlace,
	go: place => go(place, { replace: true, pass: true }),
	name: place => {
		const s = place && place.s
		if (!s) return ''
		const section = te('shell.nav_' + s) ? t('shell.nav_' + s) : ''
		const tab = place.t && te('shell.tab_' + s + '_' + place.t) ? t('shell.tab_' + s + '_' + place.t) : ''
		return [section, tab].filter(Boolean).join(' / ')
	}
})

export function hrefOf(place) {
	const q = queryOf(place)
	return PATH + '?' + Object.keys(q).map(k => k + '=' + encodeURIComponent(q[k])).join('&')
}
