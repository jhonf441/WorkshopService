<template>
	<!-- One touch target (40 px) that is on or off: a box for a choice among several, a round mark when `radio` (one of a few). Emits click; the parent decides. -->
	<button type="button" class="access-toggle access-touch" :class="{ 'is-on': on }" :role="radio ? 'radio' : 'checkbox'" :aria-checked="on ? 'true' : 'false'" :disabled="disabled" @click="$emit('click')">
		<v-icon small aria-hidden="true">{{ icon }}</v-icon>
		<span class="access-toggle-text">{{ label }}</span>
	</button>
</template>

<script>
'use strict'

export default {
	props: {
		label: { type: String, default: '' },
		on: { type: Boolean, default: false },
		radio: { type: Boolean, default: false },
		disabled: { type: Boolean, default: false }
	},
	computed: {
		icon() {
			if (this.radio) return this.on ? 'mdi-radiobox-marked' : 'mdi-radiobox-blank'
			return this.on ? 'mdi-checkbox-marked' : 'mdi-checkbox-blank-outline'
		}
	}
}
</script>

<style>
.access-toggle { display: inline-flex; align-items: center; gap: 6px; padding: 0 10px; border: 1px solid var(--wf-line); border-radius: 8px; background: transparent; color: inherit; font-size: 13px; cursor: pointer; }
.access-toggle.is-on { font-weight: 600; background: rgba(128, 128, 128, 0.18); }
.access-toggle:disabled { opacity: 0.5; cursor: default; }
</style>
