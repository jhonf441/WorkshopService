<template>
	<!-- One state of "Who can do what": an icon AND a word (never only a color). state: a line state or an area state of who-can-view.js.
	       <access-can-state state="cannot" /> -->
	<v-chip small outlined label class="can-state" :class="'is-' + state" :color="look.color" :title="compact ? $t('plugins.WorkshopService.access.who_state_' + state) : null">
		<v-icon left x-small aria-hidden="true">{{ look.icon }}</v-icon>{{ $t('plugins.WorkshopService.access.' + (compact ? 'who_short_' : 'who_state_') + state) }}<span v-if="compact" class="sv-vh">{{ $t('plugins.WorkshopService.access.who_state_' + state) }}</span>
	</v-chip>
</template>

<script>
'use strict'

const LOOK = Object.freeze({
	can: { icon: 'mdi-check-circle-outline', color: 'success' },
	view: { icon: 'mdi-eye-outline', color: 'info' },
	partial: { icon: 'mdi-adjust', color: 'warning' },
	cannot: { icon: 'mdi-cancel', color: 'error' },
	admin_only: { icon: 'mdi-lock-outline', color: '' },
	stop: { icon: 'mdi-stop-circle-outline', color: 'success' },
	unknown: { icon: 'mdi-help-circle-outline', color: '' }
})

export default {
	name: 'AccessCanState',
	props: { state: { type: String, default: 'unknown' }, compact: { type: Boolean, default: false } },
	computed: {
		look() { return LOOK[this.state] || LOOK.unknown }
	}
}
</script>

<style>
.can-state { height: auto !important; min-height: 28px; white-space: nowrap; flex: none; }
</style>
