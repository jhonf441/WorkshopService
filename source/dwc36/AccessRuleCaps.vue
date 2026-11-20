<template>
	<!-- "What it does" of one rule being edited: the capabilities by category with a box each. Nothing that a profile cannot grant has a box (lock and
	     sentence), and a deny rule is never offered a stop. The groups come from offered() of access-profile-edit.js, built on the lists of the service.
	       <access-rule-caps :groups="[...]" :operations="rule.operations" @toggle="entry => ..." /> -->
	<div class="access-rule-caps">
		<details v-for="g in groups" :key="g.id" class="access-cat" :open="opened(g)">
			<summary class="access-cat-title">{{ catTitle(g) }} ({{ g.items.length }})</summary>
			<ul class="access-cap-rows">
				<li v-for="c in g.items" :key="c.id" class="access-cap-row" :class="{ 'is-locked': !!c.lock }">
					<v-icon v-if="c.lock" small class="access-cap-lock" aria-hidden="true">mdi-lock-outline</v-icon>
					<access-toggle v-else :label="c.title" :on="has(c.id)" @click="$emit('toggle', 'cap:' + c.id)" />
					<span v-if="c.lock" class="access-cap-title">{{ c.title }}</span>
					<code class="access-cap-id">cap:{{ c.id }}</code>
					<v-chip small outlined label>{{ $t('plugins.WorkshopService.access.builder_class_' + c.klass) }}</v-chip>
					<v-chip small outlined label :color="riskColor(c.risk)">{{ $t('plugins.WorkshopService.access.builder_risk', { n: c.risk }) }}</v-chip>
					<span v-if="c.lock === 'admin'" class="access-cap-note">{{ $t('plugins.WorkshopService.access.builder_locked_admin') }}</span>
					<span v-else-if="c.lock === 'stop'" class="access-cap-note">{{ $t('plugins.WorkshopService.access.builder_locked_stop') }}</span>
					<span v-else-if="c.alwaysAllowed" class="access-cap-note">{{ $t('plugins.WorkshopService.access.builder_always_allowed') }}</span>
				</li>
			</ul>
		</details>
	</div>
</template>

<script>
'use strict'

import AccessToggle from './AccessToggle.vue'
import { RISK_COLORS } from './access-profile-view.js'

export default {
	components: { AccessToggle },
	props: {
		groups: { type: Array, default: () => [] },
		operations: { type: Array, default: () => [] }
	},
	methods: {
		has(id) {
			return this.operations.indexOf('cap:' + id) >= 0
		},
		opened(g) {
			return g.items.some(i => this.has(i.id))
		},
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
