<template>
	<!-- The help of a row, four lines (design guide 8): what it is, what it is for, what happens when it is missing, how to use it.
	     Opens on touch and stays open; nothing lives only in a tooltip. Props: what, why, missing, how (sentences). The four labels and
	     the title come from the translator the page provides (keys help_*). -->
	<details class="sv-help" @keydown.esc.stop="close">
		<summary><span class="mdi mdi-help-circle-outline sv-ico sv-ico-s" aria-hidden="true" />{{ kt('help_title') }}</summary>
		<dl>
			<dt>{{ kt('help_what') }}</dt><dd>{{ what }}</dd>
			<dt>{{ kt('help_why') }}</dt><dd>{{ why }}</dd>
			<dt>{{ kt('help_missing') }}</dt><dd>{{ missing }}</dd>
			<dt>{{ kt('help_how') }}</dt><dd>{{ how }}</dd>
		</dl>
	</details>
</template>

<script>
import { svTextMixin } from './sv-text.js'

export default {
	name: 'SvHelp',
	mixins: [svTextMixin],
	props: {
		what: { type: String, default: '' },
		why: { type: String, default: '' },
		missing: { type: String, default: '' },
		how: { type: String, default: '' }
	},
	methods: {
		// Escape closes it and the focus goes back to the one trigger it has (its summary): the same control opens and closes
		close() {
			if (!this.$el || !this.$el.open) return
			this.$el.open = false
			const s = this.$el.querySelector('summary')
			if (s && s.focus) s.focus()
		}
	}
}
</script>
