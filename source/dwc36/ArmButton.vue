<template>
	<!-- The double tap of the service page (owner decision P-2): ONE component for every dangerous control. The first tap arms it (amber, the text says "tap
	     again", announced to a screen reader), the second tap sends `confirm`; it disarms by itself after `ms`, on Escape and when it becomes disabled. Each
	     button has its OWN timer: arming one never touches another. A stop control is never wrapped in this component (STOP is never delayed).
	       <arm-button small outlined color="error" :armed-text="$t('...')" @confirm="close">Close the job</arm-button>          a Vuetify button
	       <arm-button :plain="true" role="radio" :checked="on" :arm="needsIt" @confirm="pick">...</arm-button>                      a plain button (cards, chips, switches)
	     `arm` false: the first tap already confirms (the safe direction of a switch, or a control another dialog already confirms).
	     `keep`: the armed button keeps its content and adds the note (a card), instead of replacing the content by it. Targets are 40 px high at least. -->
	<button
		v-if="plain" type="button" class="arm-btn" :class="{ 'arm-armed': armed }" :disabled="disabled" :role="role || null" :aria-checked="role ? String(!!checked) : null"
		:data-armed="armed ? '1' : null" aria-live="polite" @click="tap" @keydown.esc="disarm" @blur="disarm"
	>
		<slot v-if="!armed || keep" />
		<span v-if="armed" class="arm-note">{{ note }}</span>
	</button>
	<v-btn
		v-else v-bind="$attrs" class="arm-vbtn" :class="{ 'arm-armed': armed }" :color="armed ? 'amber darken-3' : $attrs.color" :dark="armed" :disabled="disabled" :loading="loading"
		:data-armed="armed ? '1' : null" aria-live="polite" @click="tap" @keydown.native.esc="disarm" @blur="disarm"
	>
		<slot v-if="!armed || keep" />
		<span v-if="armed" class="arm-note">{{ note }}</span>
	</v-btn>
</template>

<script>
'use strict'

import { ARM_MS } from './arm-levels.js'

export default {
	name: 'ArmButton',
	inheritAttrs: false,
	props: {
		plain: { type: Boolean, default: false },
		arm: { type: Boolean, default: true },
		keep: { type: Boolean, default: false },
		ms: { type: Number, default: ARM_MS },
		armedText: { type: String, default: '' },
		disabled: { type: Boolean, default: false },
		loading: { type: Boolean, default: false },
		role: { type: String, default: '' },
		checked: { type: Boolean, default: false }
	},
	data() {
		return { armed: false }
	},
	computed: {
		note() {
			return this.armedText || this.$t('plugins.WorkshopService.servicePage.arm_tap_again')
		}
	},
	watch: {
		disabled(v) { if (v) this.disarm() },
		arm(v) { if (!v) this.disarm() }
	},
	beforeDestroy() {
		clearTimeout(this._timer)
	},
	methods: {
		// a tap, or Enter / Space on the focused button (the browser turns them into a click)
		tap() {
			if (this.disabled || this.loading) return
			if (!this.arm) {
				this.disarm()
				this.$emit('confirm')
				return
			}
			if (!this.armed) {
				this.armed = true
				clearTimeout(this._timer)
				this._timer = setTimeout(() => { this.armed = false }, this.ms)
				this.$emit('arm')
				return
			}
			this.disarm()
			this.$emit('confirm')
		},
		disarm() {
			clearTimeout(this._timer)
			this.armed = false
		}
	}
}
</script>

<style>
.arm-btn { font: inherit; text-align: left; min-height: 40px; min-width: 40px; padding: 4px 12px; border: 1px solid var(--wf-line-strong, currentColor); border-radius: 8px; background: transparent; color: inherit; cursor: pointer; }
.arm-btn:hover:not([disabled]) { background: var(--wf-soft, rgba(128, 128, 128, 0.12)); }
.arm-btn:focus-visible, .arm-vbtn:focus-visible { outline: 2px solid var(--wf-info, #1976d2); outline-offset: 2px; }
.arm-btn[aria-checked="true"] { border-color: var(--v-primary-base, #1976d2); font-weight: 600; }
.arm-btn[disabled] { opacity: 0.5; cursor: not-allowed; }
.arm-vbtn { min-height: 40px; }
.arm-btn.arm-armed { background: #ff8f00; border-color: #ff8f00; color: #1b1b1b; }
.arm-note { display: block; font-weight: 600; }
.arm-vbtn .arm-note { display: inline; }
</style>
