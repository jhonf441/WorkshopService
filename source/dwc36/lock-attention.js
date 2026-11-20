'use strict'

// A touch on a control this person cannot use (a disabled button does not emit a click, so the area around it listens): no dialog and no
// card. The reason next to the control blinks and, when nobody is signed in, so does the sign-in chip of the bar; if it is out of view the
// page scrolls to it. Same behaviour as the other workshop pages (class .is-attention, design/family.css). Pure DOM, no texts.

const REASONS = '.wf-reason'
const CHIP = '.wf-session-chip:not(.is-role)'

function offScreen(el) {
	if (!el || typeof el.getBoundingClientRect !== 'function') return false
	const r = el.getBoundingClientRect()
	const h = (typeof window !== 'undefined' && window.innerHeight) || 800
	return r.bottom < 0 || r.top > h
}

// root: the element that holds the control and its reason; returns true when something blinked
export function blinkLocked(root, signedOut) {
	if (typeof document === 'undefined') return false
	const scope = root && typeof root.querySelectorAll === 'function' ? root : document
	const list = Array.from(scope.querySelectorAll(REASONS))
	if (signedOut) Array.from(document.querySelectorAll(CHIP)).forEach(c => list.push(c))
	if (!list.length) return false
	const first = list[0]
	if (offScreen(first) && typeof first.scrollIntoView === 'function') first.scrollIntoView({ behavior: 'smooth', block: 'center' })
	list.forEach(el => {
		el.classList.remove('is-attention')
		void el.offsetWidth // restarts the animation when touched twice in a row
		el.classList.add('is-attention')
		setTimeout(() => el.classList.remove('is-attention'), 1800)
	})
	return true
}

// Reaching a row inside a folded level of the Processes section (a group, a line of fine rows: data-collapsed="true"): opens every folded level around the
// element and says if it opened any. The toggle of each folded ancestor is the first one inside it (the header of a group, the button of the fine rows).
export function unfoldAround(el) {
	const toggles = []
	for (let n = el && el.parentElement; n; n = n.parentElement) {
		const t = n.getAttribute && n.getAttribute('data-collapsed') === 'true' ? n.querySelector('[data-group-toggle]') : null
		if (t) toggles.push(t)
	}
	toggles.forEach(t => t.click())
	return toggles.length > 0
}
