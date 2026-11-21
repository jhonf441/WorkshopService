'use strict'

// Where the person is and whether the page is being looked at. One reactive object for the whole page; the shell (app/) writes it,
// the data layer reads it to know when to rest.
//
//   active    the page is the visible route of DWC (keep-alive: the page is not destroyed when the person leaves it)
//   visible   the browser tab is visible
//   section / tab / anchor   the place, mirrored in the address (?s=&t=&a=); filter = the filters of a screen (?f=), '' when none
//   width     's' | 'm' | 'l': the room the page really has (measured on its container, never the window)
//   retry     { n, total } while the transport retries a call (the service is restarting), else null
//   restarting   the page asked the service to restart and it has not come back yet (the verdict says so)
//   chainBroken  the chain of the recorded activity was found broken by a verification made in this visit
//
//   awake()   active and visible: the only moment something may refresh, tick or verify

import Vue from 'vue'

export const pageState = Vue.observable({ active: false, visible: true, section: '', tab: '', anchor: '', filter: '', width: 'l', retry: null, restarting: false, chainBroken: false })

export function awake() {
	return pageState.active && pageState.visible
}

// the three widths of the design: s under 640 px, m from 640 to 1179, l from 1180
export const WIDTH_M = 640
export const WIDTH_L = 1180

export function widthOf(px) {
	const n = Number(px) || 0
	if (!n) return 'l' // not measured yet (no layout): the widest, as the old page did
	return n < WIDTH_M ? 's' : n < WIDTH_L ? 'm' : 'l'
}
