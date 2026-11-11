<template>
	<!-- One rule of a profile, read only: its name, allow or deny, the operations (a few, the rest on request), the targets and the conditions. -->
	<div class="access-rule" :class="'access-rule--' + rule.decision">
		<div class="access-rule-head">
			<span class="access-rule-n">{{ index }}</span>
			<strong class="access-rule-id">{{ rule.id }}</strong>
			<v-chip small outlined label :color="rule.decision === 'allow' ? 'success' : 'error'">{{ $t('plugins.WorkshopService.access.builder_decision_' + rule.decision) }}</v-chip>
		</div>
		<div class="access-rule-line">
			<span class="access-rule-label">{{ $t('plugins.WorkshopService.access.builder_loose_ops') }}</span>
			<span v-for="o in shownOps" :key="o" class="access-op">{{ o }}</span>
			<v-btn v-if="hasMore" small text class="access-touch" @click="open = !open">{{ open ? $t('plugins.WorkshopService.access.builder_ops_less') : $t('plugins.WorkshopService.access.builder_ops_more', { n: hidden }) }}</v-btn>
		</div>
		<div class="access-rule-line">
			<span class="access-rule-label">{{ $t('plugins.WorkshopService.access.builder_target_some') }}</span>
			<span v-if="!targets.length">{{ $t('plugins.WorkshopService.access.builder_target_all') }}</span>
			<span v-for="t in targets" :key="t" class="access-op">{{ t }}</span>
		</div>
		<div v-if="conditions.length" class="access-rule-line">
			<span class="access-rule-label">{{ $t('plugins.WorkshopService.access.builder_when') }}</span>
			<span v-for="c in conditions" :key="c.labelKey" class="access-op">{{ $t('plugins.WorkshopService.access.' + c.labelKey) }}: {{ valueOf(c) }}</span>
		</div>
	</div>
</template>

<script>
'use strict'

import { whenItems } from './access-profile-view.js'

const SHOWN = 12

export default {
	props: {
		rule: { type: Object, required: true },
		index: { type: Number, default: 1 }
	},
	data() {
		return { open: false }
	},
	computed: {
		ops() {
			return this.rule.operations || []
		},
		shownOps() {
			return this.open ? this.ops : this.ops.slice(0, SHOWN)
		},
		hidden() {
			return Math.max(0, this.ops.length - SHOWN)
		},
		hasMore() {
			return this.hidden > 0 || this.open
		},
		targets() {
			return this.rule.targets || []
		},
		conditions() {
			return whenItems(this.rule.when)
		}
	},
	methods: {
		valueOf(c) {
			if (c.valueKey) return this.$t('plugins.WorkshopService.access.' + c.valueKey)
			if (c.value !== undefined) return c.value
			return this.$t('plugins.WorkshopService.access.' + (c.yes ? 'common_yes' : 'common_no'))
		}
	}
}
</script>

<style>
.access-rule { margin-bottom: 8px; padding: 8px 12px; border: 1px solid var(--wf-line); border-radius: 8px; font-size: 13px; }
.access-rule-head { display: flex; align-items: center; gap: 8px; min-height: 40px; }
.access-rule-n { opacity: 0.6; }
.access-rule-line { display: flex; align-items: center; flex-wrap: wrap; gap: 4px 6px; margin-top: 4px; }
.access-rule-label { margin-right: 4px; font-size: 12px; opacity: 0.7; }
.access-op { padding: 1px 8px; border: 1px solid var(--wf-line); border-radius: 999px; font-family: monospace; font-size: 12px; }
</style>
