<template>
	<!-- The builder of a profile in read mode (step 1): its rules, the fixed notes and the table of every capability. Nothing here edits. -->
	<div class="access-builder">
		<div class="access-h">{{ $t('plugins.WorkshopService.access.builder_rules_count', { n: rules.length, max }) }}</div>
		<div v-if="!rules.length" class="wf-help">{{ $t('plugins.WorkshopService.access.builder_no_rules') }}</div>
		<access-rule-view v-for="(r, i) in rules" :key="r.id" :rule="r" :index="i + 1" />
		<div class="wf-help access-summary">{{ $t('plugins.WorkshopService.access.builder_summary', { allow: summary.allow, deny: summary.deny }) }}</div>
		<div class="wf-help">{{ $t('plugins.WorkshopService.access.builder_order_note') }}</div>
		<div class="wf-help">{{ $t('plugins.WorkshopService.access.builder_when_unknown') }}</div>
		<access-capability-table v-if="capabilities.length" class="mt-3" :doc="doc" :capabilities="capabilities" :categories="categories" />
	</div>
</template>

<script>
'use strict'

import AccessRuleView from './AccessRuleView.vue'
import AccessCapabilityTable from './AccessCapabilityTable.vue'
import { ruleSummary } from './access-profile-view.js'

export default {
	components: { AccessRuleView, AccessCapabilityTable },
	props: {
		doc: { type: Object, default: null },
		capabilities: { type: Array, default: () => [] },
		categories: { type: Array, default: () => [] },
		max: { type: Number, default: 50 }
	},
	computed: {
		rules() {
			return (this.doc && this.doc.rules) || []
		},
		summary() {
			return ruleSummary(this.doc)
		}
	}
}
</script>
