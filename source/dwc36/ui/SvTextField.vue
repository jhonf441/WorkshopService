<template>
	<!-- The one-line field of the kit (a box of 44 px, one focus ring) with its label ABOVE it, for the screens that still draw the old fields: v-model compatible. Everything else that
	     an input takes (type, min, max, maxlength, inputmode, autocomplete, disabled, readonly, placeholder, aria-label, id) goes to the input as it is.
	     Props: value, label, icon (an mdi class drawn inside the box: a search), error (a sentence under the field), invalid. Events: input (the text; v-model.number makes it a number), enter. -->
	<div>
		<label v-if="label" class="sv-label" :for="inputId">{{ label }}</label>
		<span class="sv-field"><span v-if="icon" class="mdi sv-ico sv-ico-s" :class="icon" aria-hidden="true" /><input v-bind="$attrs" :id="inputId" :value="value" :aria-invalid="invalid || error ? 'true' : null" @input="$emit('input', $event.target.value)" @keyup.enter="$emit('enter')"></span>
		<span v-if="error" class="sv-field-error" role="alert"><span class="mdi mdi-alert-outline sv-ico sv-ico-s" aria-hidden="true" />{{ error }}</span>
	</div>
</template>

<script>
let serial = 0

export default {
	name: 'SvTextField',
	inheritAttrs: false,
	model: { prop: 'value', event: 'input' },
	props: {
		value: { type: [String, Number], default: '' },
		label: { type: String, default: '' },
		icon: { type: String, default: '' },
		error: { type: String, default: '' },
		invalid: { type: Boolean, default: false }
	},
	data() {
		serial += 1
		return { uid: 'sv-tf-' + serial }
	},
	computed: {
		inputId() {
			return this.$attrs.id || this.uid
		}
	}
}
</script>
