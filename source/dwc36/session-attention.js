'use strict'

// A touch on something that needs a session (and nobody is signed in): no dialog, no card. The sign-in chip of the page bar and the session
// notes blink (family.css .is-attention); if the chip is out of view the page first scrolls up to it. Returns true when something blinked.
// The JS plugins have the same function (src/_shared/09-session-notice.js workshopSessionAttention).
const TARGETS = {
	session: '.wf-session-chip:not(.is-role), .wf-notice--session, .wf-reason--session, .wf-cover--session',
	role: '.wf-session-chip.is-role, .wf-notice--role, .wf-reason--role, .wf-cover--role'
}
// a read the page makes by itself when it opens: a role that cannot read it is told by the notes of the page, never by a card
const READ_OP = /(^|[._])(get|list|read|status|state|info|history|report|summary|snapshot|stats?|usage|check|probe|detect)(\.|_|$)/
export function isReadOp(op) {
	return READ_OP.test(String(op || ''))
}

function offScreen(el) {
	const r = el.getBoundingClientRect()
	return r.bottom < 0 || r.top > (window.innerHeight || document.documentElement.clientHeight)
}

// Where the person touched last: the notes that blink are the ones nearest to it, not every note of the page. The touched element is kept on
// window (the JS plugins keep it there too), and the listeners are added once per page whatever the number of plugin copies.
if (typeof window !== 'undefined' && typeof document !== 'undefined' && typeof document.addEventListener === 'function' && !window.__workshopTouchHook) {
	window.__workshopTouchHook = true
	const remember = ev => {
		window.__workshopLastTouch = ev && ev.target ? ev.target : null
	}
	document.addEventListener('pointerdown', remember, true)
	document.addEventListener('keydown', ev => {
		if (ev.key === 'Enter' || ev.key === ' ') remember({ target: document.activeElement })
	}, true)
}

function centerY(el) {
	const r = el.getBoundingClientRect()
	return (r.top + r.bottom) / 2
}

// from all the notes of the page to the one nearest to the touched element (the smallest ancestor of the touch that holds a note, then the
// closest of those by height); the sign-in chip always blinks. Exported for the tests.
export function nearestNote(notes, touch) {
	if (!notes.length) return []
	if (notes.length === 1) return notes
	if (touch && typeof touch.closest === 'function' && document.contains(touch)) {
		for (let up = touch.parentElement; up; up = up.parentElement) {
			const inside = notes.filter(n => up.contains(n))
			if (inside.length) {
				const y = centerY(touch)
				inside.sort((a, b) => Math.abs(centerY(a) - y) - Math.abs(centerY(b) - y))
				return [inside[0]]
			}
		}
	}
	return [notes[0]]
}

export function attentionSession(kind = 'session') {
	if (typeof document === 'undefined' || typeof document.querySelectorAll !== 'function') return false
	const all = Array.from(document.querySelectorAll(TARGETS[kind] || TARGETS.session))
	if (!all.length) return false
	const chips = all.filter(el => el.classList.contains('wf-session-chip'))
	const list = chips.concat(nearestNote(all.filter(el => !el.classList.contains('wf-session-chip')), typeof window !== 'undefined' ? window.__workshopLastTouch : null))
	const chip = chips[0]
	if (chip && offScreen(chip) && typeof chip.scrollIntoView === 'function') chip.scrollIntoView({ behavior: 'smooth', block: 'center' })
	list.forEach(el => {
		el.classList.remove('is-attention')
		void el.offsetWidth // restarts the animation when touched twice in a row
		el.classList.add('is-attention')
		setTimeout(() => el.classList.remove('is-attention'), 1800)
	})
	return true
}
