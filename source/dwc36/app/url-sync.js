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

import { query, setQuery } from '../core/dwc.js'
import { pageState } from '../core/page-state.js'
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
	setQuery(queryOf(place), !(opts && opts.replace) && place.s !== before.s)
	return apply(place)
}

export function hrefOf(place) {
	const q = queryOf(place)
	return PATH + '?' + Object.keys(q).map(k => k + '=' + encodeURIComponent(q[k])).join('&')
}
