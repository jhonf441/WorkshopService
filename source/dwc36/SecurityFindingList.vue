<template>
	<!-- The findings of a review, one row each in the order the service gave them: severity chip, the sentence of the service and the button of the object it
	     names (profile, person or key). A finding of a code this screen does not know is shown with its sentence and no button: nothing is invented.
	       <security-finding-list :rows="findingRows(answer)" @open="target => ..." /> -->
	<ul class="security-findings" role="list">
		<li v-for="r in rows" :key="r.id" class="security-finding" :data-code="r.code">
			<v-chip small outlined label :color="r.color" class="security-sev" :class="'is-' + r.severity">{{ $t('plugins.WorkshopService.access.review_sev_' + r.severity) }}</v-chip>
			<span class="security-message">{{ r.message }}</span>
			<v-btn v-if="r.target" small outlined class="access-touch security-open" :aria-label="$t('plugins.WorkshopService.access.' + r.openLabel) + ': ' + r.subject" @click="$emit('open', r.target)">{{ $t('plugins.WorkshopService.access.' + r.openLabel) }}</v-btn>
		</li>
	</ul>
</template>

<script>
'use strict'

export default {
	props: { rows: { type: Array, default: () => [] } }
}
</script>

<style>
.security-findings { list-style: none; margin: 0; padding: 0; border: 1px solid var(--wf-line); border-radius: 8px; }
.security-finding { display: flex; align-items: center; gap: 8px 12px; min-height: 44px; padding: 4px 12px; border-bottom: 1px solid var(--wf-line); }
.security-finding:last-child { border-bottom: 0; }
.security-sev { flex: none; min-width: 72px; justify-content: center; }
.security-message { flex: 1 1 auto; min-width: 0; font-size: 13px; overflow-wrap: anywhere; }
.security-open { flex: none; }
@media (max-width: 900px) {
	.security-finding { flex-wrap: wrap; padding: 8px 12px; }
	.security-message { flex-basis: 100%; order: 3; }
}
</style>
