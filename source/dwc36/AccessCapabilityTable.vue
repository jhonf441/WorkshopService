<template>
	<!-- Every capability by category with its class, its risk and how the profile covers it. A capability no profile can grant carries the lock and the
	     sentence; one that holds a stop is always allowed and can never be denied. Read only: no boxes. The service decides what is grantable. -->
	<div class="access-caps">
		<div class="access-h">{{ $t('plugins.WorkshopService.access.builder_caps_title') }}</div>
		<details v-for="g in groups" :key="g.id" class="access-cat" open>
			<summary class="access-cat-title">{{ catTitle(g) }} ({{ g.items.length }})</summary>
			<ul class="access-cap-rows">
				<li v-for="c in g.items" :key="c.id" class="access-cap-row" :class="{ 'is-locked': c.locked }">
					<v-icon v-if="c.locked" small class="access-cap-lock" aria-hidden="true">mdi-lock-outline</v-icon>
					<span class="access-cap-title">{{ c.title }}</span>
					<code class="access-cap-id">cap:{{ c.id }}</code>
					<v-chip small outlined label>{{ $t('plugins.WorkshopService.access.builder_class_' + c.klass) }}</v-chip>
					<v-chip small outlined label :color="riskColor(c.risk)">{{ $t('plugins.WorkshopService.access.builder_risk', { n: c.risk }) }}</v-chip>
					<v-chip v-if="c.allowed !== 'none'" small outlined label color="success">{{ $t('plugins.WorkshopService.access.builder_covered_' + c.allowed) }}</v-chip>
					<v-chip v-if="c.denied" small outlined label color="error">{{ $t('plugins.WorkshopService.access.builder_covered_deny') }}</v-chip>
					<span v-if="c.allowed === 'none' && !c.denied" class="access-cap-none">{{ $t('plugins.WorkshopService.access.builder_covered_none') }}</span>
					<span v-if="c.locked" class="access-cap-note">{{ $t('plugins.WorkshopService.access.builder_locked_admin') }}</span>
					<span v-if="c.alwaysAllowed" class="access-cap-note">{{ $t('plugins.WorkshopService.access.builder_always_allowed') }} {{ $t('plugins.WorkshopService.access.builder_locked_stop') }}</span>
				</li>
			</ul>
		</details>
	</div>
</template>

<script>
'use strict'

import { capabilityGroups, RISK_COLORS } from './access-profile-view.js'

export default {
	props: {
		doc: { type: Object, default: null },
		capabilities: { type: Array, default: () => [] },
		categories: { type: Array, default: () => [] }
	},
	computed: {
		groups() {
			return capabilityGroups(this.capabilities, this.categories, this.doc)
		}
	},
	methods: {
		riskColor(n) {
			return RISK_COLORS[n] || ''
		},
		catTitle(g) {
			const key = 'plugins.WorkshopService.access.builder_category_' + g.id
			return this.$te(key) ? this.$t(key) : g.title
		}
	}
}
</script>

<style>
.access-h { margin: 0 0 8px; font-size: 14px; font-weight: 600; }
.access-cat { margin-bottom: 8px; border: 1px solid var(--wf-line); border-radius: 8px; }
.access-cat-title { min-height: 40px; display: flex; align-items: center; padding: 0 12px; font-weight: 600; cursor: pointer; }
.access-cap-rows { list-style: none; margin: 0; padding: 0 12px 4px; }
.access-cap-row { display: flex; align-items: center; flex-wrap: wrap; gap: 4px 8px; min-height: 44px; border-top: 1px solid var(--wf-line); font-size: 13px; }
.access-cap-row.is-locked { opacity: 0.75; }
.access-cap-id { font-size: 12px; opacity: 0.7; }
.access-cap-note, .access-cap-none { font-size: 12px; opacity: 0.7; }
</style>
