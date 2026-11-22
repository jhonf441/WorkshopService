'use strict'

// Placing the page (FASE4: moved from the service page to the family, vue/_shared36/scroll-home.js; the twin in WorkshopService/dwc36 is byte-equal).
// The header is the first of .sv-head (service), .wf-bar / .page-header (PageHeader of the family).
// Placing the page. DWC draws its status panels above every plugin page (from 960 px of width), so on a low screen (the kiosk)
// only a strip of this page is visible when it opens. The page does not touch DWC: when it is ACTIVATED (the person enters its
// route, loads it, or arrives by a link) and less than 320 px are visible under its header, it brings its header to the top of the
// visible area, with no animation.
//
// It is ONE placement that waits for the layout to settle: on a direct load DWC's panels get their final height only when the
// object model arrives, well after this page is drawn, so the measure is repeated every frame until what is above the page has
// not moved for a moment (or a few seconds passed). The first thing the person does (wheel, touch, key, mouse) ends it for good.
//
// Never: on a change of section, tab or filter; because data arrived later; if the person already moved; with the focus in a
// field; with a dialog or a sheet open. An anchor in the address wins (the page goes to the anchor). The keyboard focus is not moved.
//
//   placementDelta(m)     pure: how many px to scroll (0 = leave it). m = { headerTop, headerBottom (px from the top of the viewport),
//                         viewport (its height), barTop (height of DWC's fixed bar), anchor, scrolled, focusTag, dialogOpen }
//   settled(m)            pure: is the watch over? m = { now, startedAt, stableSince } (ms)
//   placeOnActivation(el, opts)   measures and scrolls; opts = { barTop, anchor } ; returns the function that ends the watch

export const MIN_VISIBLE = 320   // with this much of the page in view under its header, nothing moves
export const AIR = 8             // px left above the header
export const SETTLE_MS = 800     // what is above the page did not move for this long: the layout is final
export const WATCH_MS = 6000     // and it is never watched longer than this

const FIELDS = ['INPUT', 'SELECT', 'TEXTAREA']
const PERSON_EVENTS = ['wheel', 'touchstart', 'keydown', 'mousedown']

// a dialog is open: the veil of the service page (.sv-veil.on), the veil of the family pieces WfSheet / WfConfirm (.wf-veil: it exists only while open), the PIN pad, a Vuetify dialog or overlay
export const DIALOG_SELECTOR = '.sv-veil.on, .wf-veil, [data-tp-pin], .v-dialog--active, .v-overlay--active'
export function dialogIsOpen(doc) {
	return !!doc.querySelector(DIALOG_SELECTOR)
}

export function placementDelta(m) {
	const x = m || {}
	if (x.anchor || x.scrolled || x.dialogOpen) return 0
	if (FIELDS.indexOf(String(x.focusTag || '').toUpperCase()) >= 0) return 0
	const visible = (Number(x.viewport) || 0) - (Number(x.headerBottom) || 0)
	if (visible >= MIN_VISIBLE) return 0
	const delta = Math.round((Number(x.headerTop) || 0) - (Number(x.barTop) || 0) - AIR)
	return delta > 0 ? delta : 0     // only ever down the page: a header that is already above is the person's doing
}

export function settled(m) {
	return m.now - m.stableSince >= SETTLE_MS || m.now - m.startedAt >= WATCH_MS
}

export function placeOnActivation(el, opts) {
	const o = opts || {}
	if (typeof window === 'undefined' || typeof document === 'undefined' || !el || typeof el.getBoundingClientRect !== 'function') return () => {}
	const header = el.querySelector('.sv-head, .wf-bar, .page-header') || el
	const raf = window.requestAnimationFrame || (fn => setTimeout(fn, 16))
	const clock = () => Date.now()
	let over = false
	const stop = () => {
		if (over) return
		over = true
		PERSON_EVENTS.forEach(name => window.removeEventListener(name, stop, true))
	}
	PERSON_EVENTS.forEach(name => window.addEventListener(name, stop, { capture: true, passive: true }))
	const startedAt = clock()
	let stableSince = startedAt
	let lastTop = null
	const step = () => {
		if (over) return
		const r = header.getBoundingClientRect()
		// where the header is in the document: it moves only when something above the page changes its height
		const top = Math.round(r.top + (window.scrollY || window.pageYOffset || 0))
		if (top !== lastTop) { lastTop = top; stableSince = clock() }
		const active = document.activeElement
		const delta = placementDelta({
			headerTop: r.top, headerBottom: r.bottom, viewport: window.innerHeight, barTop: o.barTop, anchor: o.anchor, scrolled: false,
			focusTag: active && active.tagName, dialogOpen: dialogIsOpen(document)
		})
		if (delta) window.scrollBy(0, delta)
		if (settled({ now: clock(), startedAt, stableSince })) return stop()
		raf(step)
	}
	// after the layout of this activation: two frames (the page was display:none while another route was shown)
	raf(() => raf(step))
	return stop
}
