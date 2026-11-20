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
