<template>
	<!-- The verdict: ONE answer to "how is what this screen looks after", first thing on the screen.
	     Props: level ('ok' | 'warn' | 'error'), title (the sentence), facts ([short strings]: version, since when, age of the data),
	            old (the last fact is a datum that got old: drawn as a notice).
	     Slot: default (one main button: the next thing to do). In the medium width it becomes one compact row (style sheet). -->
	<div class="sv-verdict" :data-level="level" role="status">
		<span class="mdi sv-ico sv-ico-l" :class="icon" aria-hidden="true" />
		<div class="sv-verdict-main">
			<strong>{{ title }}</strong>
			<div v-if="facts.length" class="sv-verdict-facts">
				<span v-for="(f, i) in facts" :key="i" :class="{ 'sv-age': old && i === last }" :data-old="old && i === last ? '' : null">{{ f }}</span>
			</div>
		</div>
		<slot />
	</div>
</template>

<script>
const ICONS = { ok: 'mdi-check-circle-outline', warn: 'mdi-alert-outline', error: 'mdi-close-circle-outline' }

export default {
	name: 'SvVerdict',
	props: {
		level: { type: String, default: 'ok' },
		title: { type: String, default: '' },
		facts: { type: Array, default: () => [] },
		old: { type: Boolean, default: false }
	},
	computed: {
		icon() {
			return ICONS[this.level] || ICONS.warn
		},
		last() {
			return this.facts.length - 1
		}
	}
}
</script>
