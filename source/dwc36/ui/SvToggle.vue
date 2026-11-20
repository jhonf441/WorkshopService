<template>
	<!-- An on / off with its name beside it, drawn with the switch of the kit (the word of the state is what is read): for the screens that still hold the value in their own data.
	     Props: value, label (what it switches), onWord, offWord, disabled. Event: input (the new value), as v-model. -->
	<span class="sv-toggle"><sv-switch :checked="!!value" :word="value ? (onWord || kt('toggle_on')) : (offWord || kt('toggle_off'))" :label="label" :disabled="disabled" @toggle="$emit('input', !value)" /><span v-if="label" class="sv-toggle-text">{{ label }}</span></span>
</template>

<script>
import SvSwitch from './SvSwitch.vue'
import { svTextMixin } from './sv-text.js'

export default {
	name: 'SvToggle',
	components: { SvSwitch },
	mixins: [svTextMixin],
	model: { prop: 'value', event: 'input' },
	props: {
		value: { type: Boolean, default: false },
		label: { type: String, default: '' },
		onWord: { type: String, default: '' },
		offWord: { type: String, default: '' },
		disabled: { type: Boolean, default: false }
	}
}
</script>
