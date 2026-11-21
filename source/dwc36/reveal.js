'use strict'

// Show an object the person asked for ("Ver persona" of Security): scroll it into view under the fixed bar of DWC and mark it for a moment.
// What is above it (the accounts) is still being drawn when the card opens, so the placement is repeated a few times while the layout settles;
// the first thing the person does (wheel, touch, key) ends it.
//   reveal(el, barTop)   el = the element (nothing happens without it); barTop = height of DWC's fixed bar in px

export const FLASH_MS = 2600
export const AIR = 12
export const PASSES = Object.freeze([0, 300, 800, 1500])
const PERSON = ['wheel', 'touchstart', 'keydown']

export function revealDelta(top, barTop) {
	return Math.round((Number(top) || 0) - (Number(barTop) || 0) - AIR)
}

export function reveal(el, barTop) {
	if (!el || typeof el.getBoundingClientRect !== 'function' || typeof window === 'undefined') return
	let over = false
	const timers = []
	const stop = () => {
		over = true
		timers.forEach(clearTimeout)
		if (window.removeEventListener) PERSON.forEach(n => window.removeEventListener(n, stop, true))
	}
	if (window.addEventListener) PERSON.forEach(n => window.addEventListener(n, stop, { capture: true, passive: true }))
	PASSES.forEach((ms, i) => timers.push(setTimeout(() => {
		if (over) return
		const d = revealDelta(el.getBoundingClientRect().top, barTop)
		if (d) window.scrollBy(0, d)
		if (i === PASSES.length - 1) stop()
	}, ms)))
	el.setAttribute('data-flash', '')
	setTimeout(() => el.removeAttribute('data-flash'), FLASH_MS)
}

// ---- Where the result of a button appears (2026-11-20) ----
// A button whose result shows up in another part of the page (a form above, a card below) must bring that result into view, mark it for a moment, put the focus in its first
// field and say what happened. ONE rule for the whole page, so no button "seems to do nothing":
//   needsScroll(rect, viewH, min)      true when less than `min` px of the block (or all of it, when shorter) are inside the window
//   revealResult(el, { focus, highlight, barTop })
//                                      scrolls smoothly (instant under prefers-reduced-motion) ONLY when needsScroll; marks `el` with [data-revealed] for 1.8 s (the style of the jump of the
//                                      file reader); focus = true (first field of el), a selector inside el, or an element: gets the focus without scrolling again.
//                                      Returns { scrolled, far }: far = the result is still out of view (nothing could scroll), so the caller says it next to the button.
//   The text for the screen reader is the caller's (reveal-mixin.js: `said`, a status region) because only the page knows what happened.

export const MIN_VISIBLE = 320
export const RESULT_FLASH_MS = 1800
const FIELD = 'input:not([type="hidden"]):not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'

export function needsScroll(rect, viewH, min = MIN_VISIBLE) {
	if (!rect) return false
	const view = Math.max(0, Number(viewH) || 0)
	const visible = Math.min(rect.bottom, view) - Math.max(rect.top, 0)
	const want = Math.min(min, Math.max(0, rect.bottom - rect.top))
	return visible < want
}

export function revealResult(el, opts) {
	const o = opts || {}
	if (!el || typeof el.getBoundingClientRect !== 'function' || typeof window === 'undefined') return { scrolled: false, far: false }
	const calm = typeof window.matchMedia === 'function' && window.matchMedia('(prefers-reduced-motion: reduce)').matches
	const off = needsScroll(el.getBoundingClientRect(), window.innerHeight)
	let scrolled = false
	if (el.setAttribute) el.setAttribute('data-reveal', '') // gives it the air under the fixed bar (scroll-margin-top)
	if (off && typeof el.scrollIntoView === 'function') {
		el.scrollIntoView({ behavior: calm ? 'auto' : 'smooth', block: 'start' })
		scrolled = true
	}
	if (o.highlight !== false && el.setAttribute) {
		el.removeAttribute('data-revealed')
		void el.offsetWidth // restarts the mark when the same thing is revealed twice in a row
		el.setAttribute('data-revealed', '')
		setTimeout(() => el.removeAttribute('data-revealed'), RESULT_FLASH_MS)
	}
	const target = typeof o.focus === 'string' ? el.querySelector(o.focus) : o.focus === true ? el.querySelector(FIELD) : o.focus || null
	if (target && typeof target.focus === 'function') target.focus({ preventScroll: true })
	// with no animation the move is already done: if it is still out of view, nothing could bring it
	const far = off && (!scrolled || (calm && needsScroll(el.getBoundingClientRect(), window.innerHeight)))
	return { scrolled, far: !!far }
}
