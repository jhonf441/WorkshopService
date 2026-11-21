'use strict'

// For the components whose button shows its result somewhere else (see revealResult in reveal.js). The component draws, once:
//     <span class="sv-vh" role="status" aria-live="polite" data-part="said">{{ said }}</span>      what happened, for the screen reader
//     <span v-if="farNote" class="sv-chip-sm" role="status" data-part="far-note">{{ farNote }}</span>   next to the button, only when the result could not be brought into view
// and calls  this.showResult(el, { said: 'text already translated', focus: true | selector })  after the result is drawn (inside $nextTick).
import { revealResult } from './reveal.js'

export const FAR_NOTE_MS = 4000

export const revealMixin = {
	data() {
		return { said: '', farNote: '' }
	},
	beforeDestroy() {
		clearTimeout(this.farTimer)
	},
	methods: {
		showResult(el, opts) {
			const o = opts || {}
			const r = revealResult(el, o)
			if (o.said) this.said = o.said
			if (r.far && o.said) {
				this.farNote = o.said
				clearTimeout(this.farTimer)
				this.farTimer = setTimeout(() => { this.farNote = '' }, FAR_NOTE_MS)
			}
			return r
		}
	}
}
