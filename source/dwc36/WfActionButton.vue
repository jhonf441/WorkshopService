<template>
	<!-- THE button of a write: it keeps ONE size whatever it says. The texts it may show (label, armLabel) are stacked and the longest sets the width; a wait is a
	     spinner drawn over the text (after a delay, never another text). 44 px high always (design/family.css, FASE2).
	       action      the object of createAction (workshop-action.js) or null          label / armLabel   its text, and its text while armed
	       permission  { state: 'ok' | 'resolving' | 'session' | 'role', text }         danger / main      the look (red outline / filled accent)
	       disabled    the page locks it for its own reasons
	     Two variants for dense lists and tables (they look small and are touched over 44 px: an invisible ::after, design/family.css FASE5-PIEZAS):
	       variant 'icon'  a 28 px glyph button with NO visible text: `icon` is its mdi class (required), `label` is its aria-label and tooltip (required, say the verb and the object:
	                       "Delete Lucia"), `armLabel` + `armIcon` (default mdi-check) are what a double touch shows and announces. Buttons that follow each other are spaced 16 px
	                       (the areas tile and never touch a neighbour); stack them with that gap, not closer.
	       variant 'text'  the text of the button as a link-looking word in a row ("Delete" in a table): same behaviour, same armed text, 24 px to the eye.
	     Event: run (the control was touched: the page calls action.run with its arguments). Escape or leaving the focus disarms. -->
	<button type="button" class="wf-btn wf-act" :class="{ 'wf-danger': danger, 'wf-main': main && !armed, 'wf-armed': armed, 'wf-act--icon': iconOnly, 'wf-act--text': variant === 'text' }" :data-state="state" :disabled="off"
		:aria-label="iconOnly ? shown : null" :aria-disabled="locked ? 'true' : null" :title="tip" :aria-busy="busyHeld ? 'true' : null"
		@click="touch" @focus="onFocus" @blur="onBlur" @keydown.esc="cancel">
		<span v-if="locked && !iconOnly" class="mdi mdi-lock-outline wf-act-ico" aria-hidden="true" />
		<span class="wf-act-stack" :data-alt="iconOnly ? null : alt"><span v-if="iconOnly" class="mdi wf-act-ico" :class="glyph" aria-hidden="true" /><template v-else>{{ shown }}</template></span>
	</button>
</template>

<script>
import { wfBusyMixin } from './wf-busy.js'

export default {
	name: 'WfActionButton',
	mixins: [wfBusyMixin],
	props: {
		action: { type: Object, default: null },
		label: { type: String, required: true },
		armLabel: { type: String, default: '' },
		permission: { type: Object, default: null },
		danger: { type: Boolean, default: false },
		main: { type: Boolean, default: false },
		disabled: { type: Boolean, default: false },
		variant: { type: String, default: '', validator: v => v === '' || v === 'icon' || v === 'text' },
		icon: { type: String, default: '' },
		armIcon: { type: String, default: 'mdi-check' }
	},
	created() {
		if (this.variant === 'icon' && !this.icon && typeof console !== 'undefined') console.warn('[WfActionButton] variant "icon" needs `icon` (an mdi class)')
		if (!String(this.label).trim() && typeof console !== 'undefined') console.warn('[WfActionButton] `label` is the accessible name: it cannot be empty')
	},
	computed: {
		iconOnly() {
			return this.variant === 'icon'
		},
		// the glyph of an icon-only button: the lock when it is locked (the person sees why), the armed one while armed
		glyph() {
			if (this.locked) return 'mdi-lock-outline'
			return this.armed ? this.armIcon : this.icon
		},
		// the tooltip: the reason when it is locked, else the name of an icon-only button (it has no text)
		tip() {
			if (this.locked && this.permission.text) return this.permission.text
			return this.iconOnly ? this.shown : null
		},
		state() {
			return (this.action && this.action.state) || 'idle'
		},
		armed() {
			return this.state === 'armed'
		},
		working() {
			return this.state === 'sending' || this.state === 'verifying'
		},
		locked() {
			return !!this.permission && (this.permission.state === 'session' || this.permission.state === 'role')
		},
		off() {
			return this.disabled || this.locked || this.working || this.state === 'confirming' || (!!this.permission && this.permission.state === 'resolving')
		},
		busyNow() {
			return this.working
		},
		shown() {
			return this.armed && this.armLabel ? this.armLabel : this.label
		},
		// the other text the button may show: it only lends its width (CSS ::after), so the button never changes size
		alt() {
			return this.armed && this.armLabel ? this.label : this.armLabel
		}
	},
	methods: {
		touch() {
			if (!this.off) this.$emit('run')
		},
		cancel() {
			if (this.armed && this.action) this.action.cancel()
		},
		// keyboard focus on the armed control: its time does not run; when the focus leaves it is disarmed at once
		onFocus(e) {
			let keyboard = false
			try { keyboard = e.target.matches(':focus-visible') } catch (err) { keyboard = false }
			if (keyboard && this.action && typeof this.action.hold === 'function') this.action.hold(true)
		},
		onBlur() {
			if (this.action && typeof this.action.hold === 'function') this.action.hold(false)
			this.cancel()
		}
	}
}
</script>
