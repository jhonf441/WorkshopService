<template>
	<!-- A switch whose WORD is what is read ("Armed" / "Not armed"), not its position.
	     Props: checked, word (the word of the state it is in now), label (accessible name: what it switches), state (of its action:
	     'armed' paints it amber), disabled.
	     Events: toggle (a touch, Enter or Space), hold(true | false) (keyboard focus came to / left it while armed), escape. -->
	<button type="button" class="sv-switch" role="switch" :aria-checked="checked ? 'true' : 'false'" :aria-label="label" :data-state="state || null" :disabled="disabled"
		@click="$emit('toggle')" @focus="onFocus" @blur="$emit('hold', false)" @keydown.esc="$emit('escape')">
		<i aria-hidden="true" />
		<span>{{ word }}</span>
	</button>
</template>

<script>
export default {
	name: 'SvSwitch',
	props: {
		checked: { type: Boolean, default: false },
		word: { type: String, default: '' },
		label: { type: String, default: '' },
		state: { type: String, default: '' },
		disabled: { type: Boolean, default: false }
	},
	methods: {
		// only a focus that came from the keyboard holds an armed control (a touch or a click keeps its 5 seconds)
		onFocus(e) {
			let keyboard = false
			try { keyboard = e.target.matches(':focus-visible') } catch (err) { keyboard = false }
			if (keyboard) this.$emit('hold', true)
		}
	}
}
</script>
