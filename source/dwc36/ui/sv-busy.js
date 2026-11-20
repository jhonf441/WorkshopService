'use strict'

// Waiting without flicker: what is waiting for something shows no spinner for the first BUSY_DELAY ms (400) (an answer that comes at once never flashes
// one) and, once the spinner is on, it stays for at least BUSY_MIN ms. The CSS draws the delay (animation-delay of the spinner); this holds the end.
//
// A component using it defines a computed `busyNow` (boolean) and draws `busyHeld` (data): true from the moment the wait starts until the held end.
//   holdEnd(elapsed)   ms still to wait after the work ended (0 = release now)

export const BUSY_DELAY = 400
export const BUSY_MIN = 400

export function holdEnd(elapsed) {
	const e = Number(elapsed) || 0
	if (e < BUSY_DELAY) return 0                      // the spinner never showed: nothing to hold
	return Math.max(0, BUSY_DELAY + BUSY_MIN - e)
}

export const svBusyMixin = {
	data() {
		return { busyHeld: false, busyFrom: 0, busyTimer: null }
	},
	watch: {
		busyNow: {
			immediate: true,
			handler(on) {
				clearTimeout(this.busyTimer)
				if (on) {
					if (!this.busyHeld) this.busyFrom = Date.now()
					this.busyHeld = true
					return
				}
				if (!this.busyHeld) return
				const wait = holdEnd(Date.now() - this.busyFrom)
				if (!wait) this.busyHeld = false
				else this.busyTimer = setTimeout(() => { this.busyHeld = false }, wait)
			}
		}
	},
	beforeDestroy() {
		clearTimeout(this.busyTimer)
	}
}
