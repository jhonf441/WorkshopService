<template>
	<!-- A group of choices as chips where changing the choice is a dangerous act: every chip is an ArmButton (double tap, a timer of its own), so the chosen
	     one is never re-sent and a second chip never leaves another one armed. role="radiogroup" with one radio per chip (keyboard: Tab and Enter / Space).
	       <arm-chips :value="seconds" :items="[{ value: 8, text: '8 s' }, ...]" :disabled="!can" @confirm="set" />       items: { value, text } or plain values
	       <arm-chips :value="mode" :items="['auto', 'on', 'off']" i18n-prefix="plugins.WorkshopService.servicePage.mode_" ... />     text = $t(prefix + value) -->
	<div class="arm-chips" role="radiogroup" :aria-label="label || null">
		<arm-button
			v-for="it in list" :key="String(it.value)" :plain="true" role="radio" class="arm-chip" :checked="it.value === value" :arm="it.value !== value" :disabled="disabled"
			@confirm="pick(it.value)"
		>{{ it.text }}</arm-button>
	</div>
</template>

<script>
'use strict'

import ArmButton from './ArmButton.vue'

export default {
	name: 'ArmChips',
	components: { ArmButton },
	props: {
		value: { type: [String, Number, Boolean], default: null },
		items: { type: Array, default: () => [] },
		i18nPrefix: { type: String, default: '' },
		label: { type: String, default: '' },
		disabled: { type: Boolean, default: false }
	},
	methods: {
		// the chosen chip is already the state: nothing to send
		pick(v) {
			if (v !== this.value) this.$emit('confirm', v)
		}
	},
	computed: {
		list() {
			return this.items.map(it => {
				const o = it !== null && typeof it === 'object' ? it : { value: it }
				return { value: o.value, text: o.text !== undefined ? o.text : (this.i18nPrefix ? this.$t(this.i18nPrefix + o.value) : String(o.value)) }
			})
		}
	}
}
</script>

<style>
.arm-chips { display: inline-flex; flex-wrap: wrap; gap: 6px; }
.arm-chip { border-radius: 16px; padding: 4px 14px; font-size: 13px; }
</style>
