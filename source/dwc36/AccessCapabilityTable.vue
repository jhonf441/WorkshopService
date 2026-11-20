<template>
	<!-- Every capability by category with its class, its risk and how the profile covers it. A capability no profile can grant carries the lock and the
	     sentence; one that holds a stop is always allowed and can never be denied. Read only: no boxes. The service decides what is grantable. -->
	<div class="access-caps">
		<div class="access-h">{{ $t('plugins.WorkshopService.access.builder_caps_title') }}</div>
		<!-- many capabilities: a search and a filter by risk; the groups are closed except the first (all open while searching) -->
		<div class="access-caps-tools">
			<sv-text-field v-model="q" icon="mdi-magnify" type="search" class="access-search" :placeholder="$t('plugins.WorkshopService.access.builder_caps_search')" :aria-label="$t('plugins.WorkshopService.access.builder_caps_search')" />
			<div class="access-kinds" role="group" :aria-label="$t('plugins.WorkshopService.access.builder_caps_risk_label')">
				<button type="button" class="access-kind access-touch" :class="{ 'is-on': risk === 0 }" :aria-pressed="risk === 0 ? 'true' : 'false'" @click="risk = 0">{{ $t('plugins.WorkshopService.access.builder_caps_risk_all') }}</button>
				<button v-for="n in risks" :key="n" type="button" class="access-kind access-touch" :class="{ 'is-on': risk === n }" :aria-pressed="risk === n ? 'true' : 'false'" @click="risk = n">{{ $t('plugins.WorkshopService.access.builder_risk', { n }) }}</button>
			</div>
		</div>
		<p v-if="!shown.length" class="wf-help" role="status">{{ $t('plugins.WorkshopService.access.builder_caps_none') }}</p>
		<details v-for="(g, i) in shown" :key="g.id + (filtering ? 'f' : '')" class="access-cat" :open="filtering || i === 0">
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

import SvTextField from './ui/SvTextField.vue'
import { capabilityGroups, RISK_COLORS } from './access-profile-view.js'

export default {
	components: { SvTextField },
	props: {
		doc: { type: Object, default: null },
		capabilities: { type: Array, default: () => [] },
		categories: { type: Array, default: () => [] }
	},
	data() {
		return { q: '', risk: 0 }
	},
	computed: {
		groups() {
			return capabilityGroups(this.capabilities, this.categories, this.doc)
		},
		risks() {
			const set = new Set()
			this.groups.forEach(g => g.items.forEach(c => set.add(c.risk)))
			return Array.from(set).filter(n => n > 0).sort()
		},
		filtering() {
			return !!(this.q && this.q.trim()) || this.risk > 0
		},
		// the groups with only the capabilities that match the search (title or id) and the risk; a group left empty is not drawn
		shown() {
			const q = String(this.q || '').trim().toLowerCase()
			if (!q && !this.risk) return this.groups
			return this.groups
				.map(g => Object.assign({}, g, { items: g.items.filter(c => (!this.risk || c.risk === this.risk) && (!q || String(c.title).toLowerCase().indexOf(q) >= 0 || String(c.id).toLowerCase().indexOf(q) >= 0)) }))
				.filter(g => g.items.length)
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
.access-caps-tools { display: flex; flex-wrap: wrap; align-items: center; gap: 8px 12px; margin-bottom: 12px; }
.access-caps-tools .access-search { max-width: 320px; }
.access-h { margin: 0 0 8px; font-size: 14px; font-weight: 600; }
.access-cat { margin-bottom: 8px; border: 1px solid var(--wf-line); border-radius: 8px; }
.access-cat-title { min-height: 40px; display: flex; align-items: center; padding: 0 12px; font-weight: 600; cursor: pointer; }
.access-cap-rows { list-style: none; margin: 0; padding: 0 12px 4px; }
.access-cap-row { display: flex; align-items: center; flex-wrap: wrap; gap: 4px 8px; min-height: 44px; border-top: 1px solid var(--wf-line); font-size: 13px; }
.access-cap-row.is-locked { opacity: 0.75; }
.access-cap-id { font-size: 12px; opacity: 0.7; }
.access-cap-note, .access-cap-none { font-size: 12px; opacity: 0.7; }
</style>
