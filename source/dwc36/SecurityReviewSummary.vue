<template>
	<!-- The line on top of the review: how many findings of each severity, how many are high, when it was made and the thresholds the service used.
	       <security-review-summary :answer="answer of access.review" /> -->
	<div class="security-review-summary mb-3">
		<div class="security-chips">
			<v-chip v-for="c in counts" :key="c.severity" small outlined label :color="c.color" class="security-sev" :class="'is-' + c.severity">{{ $t('plugins.WorkshopService.access.review_sev_' + c.severity) }} {{ c.count }}</v-chip>
			<span class="security-high" :class="{ 'is-on': high > 0 }">{{ $t('plugins.WorkshopService.access.review_high_count', { n: high }) }}</span>
			<span class="wf-help">{{ $t('plugins.WorkshopService.access.review_checked', { time: checked }) }}</span>
		</div>
		<div v-if="limits" class="wf-help mt-1">{{ $t('plugins.WorkshopService.access.review_limits', { keys: limits.keyDays, admin: limits.adminDays, breadth: limits.breadth }) }}</div>
	</div>
</template>

<script>
'use strict'

import { clockText, highCount, reviewLimits, severityCounts } from './access-review-view.js'

export default {
	props: { answer: { type: Object, default: () => ({}) } },
	computed: {
		counts() {
			return severityCounts(this.answer)
		},
		high() {
			return highCount(this.answer)
		},
		limits() {
			return reviewLimits(this.answer)
		},
		checked() {
			return clockText(this.answer && this.answer.generated)
		}
	}
}
</script>

<style>
.security-chips { display: flex; align-items: center; flex-wrap: wrap; gap: 6px 12px; }
.security-high { font-size: 13px; font-weight: 500; }
.security-high.is-on { font-weight: 700; }
</style>
