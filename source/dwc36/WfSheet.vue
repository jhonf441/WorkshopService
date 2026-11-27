<template>
	<!-- THE sheet of the family (FASE2, promoted from the service SvSheet): a box over the page for a short task and the base of the confirmation (WfConfirm).
	     No shadow (a border), 44 px controls. Props: open, title, wide (a reader), level (3 | 4 for a dialog: the color of its top line), role ('dialog' |
	     'alertdialog'), describedby. Slots: default (body), foot (buttons). Event: close (Escape, a touch outside, its close button: a sheet has one, a dialog
	     is closed by its own buttons). While it is open the page behind does not scroll. Focus: on opening it goes to [data-wf-autofocus] (else the first
	     element of the body); Tab stays inside; on closing it goes back to where it was. -->
	<div v-if="open" class="wf-veil" :style="clear" data-wf-veil-clear="1" @mousedown.self="$emit('close')" @keydown.esc.stop.prevent="$emit('close')" @keydown.tab="trap">
		<div ref="box" class="wf-sheet" :class="{ 'wf-dialog': !!level, 'wf-sheet-wide': wide }" :data-level="level || null" :role="role" aria-modal="true" :aria-labelledby="titleId" :aria-describedby="describedby || null">
			<div class="wf-sheet-head">
				<h2 :id="titleId" class="wf-sheet-title">{{ title }}</h2>
				<button v-if="!level" type="button" class="wf-btn wf-sheet-close" :aria-label="ts('wf_close')" @click="$emit('close')"><span class="mdi mdi-close" aria-hidden="true" /></button>
			</div>
			<div class="wf-sheet-body"><slot /></div>
			<div v-if="$scopedSlots.foot || $slots.foot" class="wf-sheet-foot"><slot name="foot" /></div>
		</div>
	</div>
</template>

<script>
import { ts } from './shared-t.js'

const LOCK = 'overflow-y-hidden'      // the class Vuetify itself puts on <html> under its dialogs
const FOCUSABLE = 'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'

let serial = 0

// the focusable elements inside a box, in order
function focusables(root) {
	if (!root || !root.querySelectorAll) return []
	return Array.prototype.filter.call(root.querySelectorAll(FOCUSABLE), el => !el.hidden)
}

// The veil never covers an emergency stop (owner's safety rule, 2026-11-23; twin of workshopVeilClear, src/_shared/45-layers.js): it starts under
// DWC's top bar (its Emergency stop) and ends left of the control bar (its STOP; the bar publishes its width to the notices center, getInset).
function veilClear() {
	let top = 0
	if (typeof document !== 'undefined' && typeof document.querySelector === 'function') {
		const bar = document.querySelector('header.v-app-bar') || document.querySelector('.v-app-bar')
		const r = bar && typeof bar.getBoundingClientRect === 'function' ? bar.getBoundingClientRect() : null
		if (r && r.height > 0 && r.bottom > 0) top = Math.ceil(r.bottom)
	}
	const c = typeof window !== 'undefined' ? window.__workshopNotices : null
	const right = c && typeof c.getInset === 'function' ? Number(c.getInset('right')) || 0 : 0
	return { top: top + 'px', right: right + 'px' }
}

export default {
	name: 'WfSheet',
	props: {
		open: { type: Boolean, default: false },
		title: { type: String, default: '' },
		level: { type: Number, default: 0 },
		role: { type: String, default: 'dialog' },
		describedby: { type: String, default: '' },
		wide: { type: Boolean, default: false }
	},
	data() {
		serial += 1
		return { titleId: 'wf-sheet-title-' + serial, opener: null, locked: false, clear: null }
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
		ts,
		onOpen() {
			this.clear = veilClear()
			this.opener = typeof document !== 'undefined' ? document.activeElement : null
			const root = typeof document !== 'undefined' ? document.documentElement : null
			if (root && root.classList && !root.classList.contains(LOCK)) { root.classList.add(LOCK); this.locked = true }
			this.$nextTick(() => {
				const box = this.$refs.box
				if (!box) return
				const all = focusables(box)
				const first = box.querySelector('[data-wf-autofocus]') || all.find(x => !x.classList || !x.classList.contains('wf-sheet-close')) || all[0]
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
			const box = this.$refs.box
			// the focus fell out of the box (a touch on the veil, the opener lost): Tab brings it back in at the end it asked for
			if (box && !box.contains(document.activeElement)) {
				e.preventDefault()
				;(e.shiftKey ? last : first).focus()
			} else if (e.shiftKey && document.activeElement === first) {
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
