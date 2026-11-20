<template>
	<!-- A sheet: a box over the page for a short task (section picker, My session) and the base of the confirmation dialog.
	     Props: open, title, wide (a reader: nearly the whole screen), level (3 | 4 for a dialog: the colour of its top line), role ('dialog' | 'alertdialog'), describedby.
	     Slots: default (the body), foot (the buttons). Event: close (Escape, a touch outside, its close button: a sheet has one, a
	     dialog is closed by its own buttons). While it is open the page behind does not scroll.
	     Focus: on opening it goes to the element with data-sv-autofocus (else the first one of the body); Tab stays inside; on closing it goes
	     back to where it was. It appears without animation. -->
	<div v-if="open" class="sv-veil on" @mousedown.self="$emit('close')" @keydown.esc.stop.prevent="$emit('close')" @keydown.tab="trap">
		<div ref="box" class="sv-sheet" :class="{ 'sv-dialog': !!level, 'sv-sheet-wide': wide }" :data-level="level || null" :role="role" aria-modal="true" :aria-labelledby="titleId" :aria-describedby="describedby || null">
			<div class="sv-sheet-head">
				<h2 :id="titleId">{{ title }}</h2>
				<button v-if="!level" type="button" class="sv-btn sv-text sv-sheet-close" :aria-label="kt('close')" @click="$emit('close')"><span class="mdi mdi-close sv-ico" aria-hidden="true" /></button>
			</div>
			<div class="sv-sheet-body"><slot /></div>
			<div v-if="$scopedSlots.foot || $slots.foot" class="sv-sheet-foot"><slot name="foot" /></div>
		</div>
	</div>
</template>

<script>
import { focusables, svTextMixin } from './sv-text.js'

const LOCK = 'overflow-y-hidden'      // the class Vuetify itself puts on <html> under its dialogs

let serial = 0

export default {
	name: 'SvSheet',
	mixins: [svTextMixin],
	props: {
		open: { type: Boolean, default: false },
		title: { type: String, default: '' },
		level: { type: Number, default: 0 },
		role: { type: String, default: 'dialog' },
		describedby: { type: String, default: '' },
		wide: { type: Boolean, default: false }      // a reader: nearly the whole screen
	},
	data() {
		serial += 1
		return { titleId: 'sv-sheet-title-' + serial, opener: null, locked: false }
	},
	watch: {
		open(now) {
			if (now) this.onOpen()
			else this.onClose()
		}
	},
	mounted() {
		if (this.open) this.onOpen()
	},
	beforeDestroy() {
		this.onClose()
	},
	methods: {
		onOpen() {
			this.opener = typeof document !== 'undefined' ? document.activeElement : null
			const root = typeof document !== 'undefined' ? document.documentElement : null
			if (root && root.classList && !root.classList.contains(LOCK)) { root.classList.add(LOCK); this.locked = true }
			this.$nextTick(() => {
				const box = this.$refs.box
				if (!box) return
				const all = focusables(box)
				const first = box.querySelector('[data-sv-autofocus]') || all.find(x => !x.classList || !x.classList.contains('sv-sheet-close')) || all[0]
				if (first && typeof first.focus === 'function') first.focus()
			})
		},
		onClose() {
			if (this.locked && typeof document !== 'undefined') document.documentElement.classList.remove(LOCK)
			this.locked = false
			const el = this.opener
			this.opener = null
			if (el && typeof el.focus === 'function') el.focus()
		},
		// Tab and Shift+Tab go round inside the box
		trap(e) {
			const items = focusables(this.$refs.box)
			if (!items.length) return
			const first = items[0]
			const last = items[items.length - 1]
			if (e.shiftKey && document.activeElement === first) {
				e.preventDefault()
				last.focus()
			} else if (!e.shiftKey && document.activeElement === last) {
				e.preventDefault()
				first.focus()
			}
		}
	}
}
</script>
