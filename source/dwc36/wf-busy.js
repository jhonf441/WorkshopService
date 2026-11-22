'use strict'

// Waiting without flicker (FASE2, promoted from the service kit sv-busy.js): what waits for something shows no spinner during the first WF_BUSY_DELAY ms
// (an answer that comes at once never flashes one) and, once the spinner is on, it stays at least WF_BUSY_MIN ms. The CSS draws the delay (animation-delay of
// the spinner); this holds the end.
//
// A component using it defines a computed `busyNow` (boolean) and draws `busyHeld` (data): true from the start of the wait until the held end.

export const WF_BUSY_DELAY = 400
export const WF_BUSY_MIN = 400

// ms still to wait after the work ended (0 = release now)
export function wfHoldEnd(elapsed) {
	const e = Number(elapsed) || 0
	if (e < WF_BUSY_DELAY) return 0                      // the spinner never showed: nothing to hold
	return Math.max(0, WF_BUSY_DELAY + WF_BUSY_MIN - e)
}

export const wfBusyMixin = {
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
				const wait = wfHoldEnd(Date.now() - this.busyFrom)
				if (!wait) this.busyHeld = false
				else this.busyTimer = setTimeout(() => { this.busyHeld = false }, wait)
			}
		}
	},
	beforeDestroy() {
		clearTimeout(this.busyTimer)
	}
}
