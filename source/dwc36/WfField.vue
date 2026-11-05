<template>
	<!-- A field with its label OUTSIDE the control and the "?" next to the LABEL (ESTANDAR 4.1, AYUDAS.md 4). Never a help button inside append-outer /
	     append / prepend. The control goes in the default slot WITHOUT :label, with the same :id and an :aria-label.
	       <wf-field :id="'al-cooldown'" :label="t(S.cooldown.label)">
	         <template #help><info-tip :choice="S.cooldown" :title="t(S.cooldown.label)" /></template>
	         <v-text-field id="al-cooldown" v-model="draft.cooldown" dense outlined hide-details :aria-label="t(S.cooldown.label)" />
	       </wf-field> -->
	<div class="wf-field">
		<div class="wf-field-label">
			<label :for="id">{{ label }}</label>
			<slot name="help" />
		</div>
		<slot />
		<div v-if="message" class="wf-field-msg" :class="'is-' + level">{{ message }}</div>
	</div>
</template>

<script>
'use strict'

export default {
	props: {
		id: { type: String, default: '' },
		label: { type: String, required: true },
		// a line under the field: level 'hint' (needed to write the value) or 'error' (only after the person touched the field)
		message: { type: String, default: '' },
		level: { type: String, default: 'hint' }
	}
}
</script>
