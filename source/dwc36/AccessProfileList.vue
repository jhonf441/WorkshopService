<template>
	<!-- The table of profiles (read only): filter by name and by kind, base profiles first. Under 900 px the rows become cards (access.css rules below).
	       <access-profile-list :list="answer of access.profiles.list" @open="row => ..." /> -->
	<div class="access-profile-list">
		<div class="access-filters">
			<v-text-field v-model="text" dense outlined hide-details clearable prepend-inner-icon="mdi-magnify" class="access-search" :placeholder="$t('plugins.WorkshopService.access.common_search')" :aria-label="$t('plugins.WorkshopService.access.common_search')" />
			<div class="access-kinds" role="group">
				<button v-for="k in kinds" :key="k" type="button" class="access-kind access-touch" :class="{ 'is-on': kind === k }" :aria-pressed="kind === k ? 'true' : 'false'" @click="kind = k">{{ $t('plugins.WorkshopService.access.profiles_filter_' + k) }}</button>
			</div>
		</div>
		<div v-if="!ownCount && kind !== 'base'" class="wf-help access-own-empty">{{ $t('plugins.WorkshopService.access.profiles_empty') }}</div>
		<div class="access-table-wrap">
			<table class="access-table">
				<thead>
					<tr>
						<th>{{ $t('plugins.WorkshopService.access.profiles_col_name') }}</th>
						<th>{{ $t('plugins.WorkshopService.access.profiles_col_type') }}</th>
						<th>{{ $t('plugins.WorkshopService.access.profiles_col_rules') }}</th>
						<th>{{ $t('plugins.WorkshopService.access.profiles_col_version') }}</th>
						<th>{{ $t('plugins.WorkshopService.access.profiles_col_holders') }}</th>
						<th></th>
					</tr>
				</thead>
				<tbody>
					<tr v-for="r in rows" :key="(r.base ? 'b:' : 'o:') + r.name" class="access-row">
						<td class="access-cell-name"><strong>{{ r.name }}</strong></td>
						<td><v-chip small outlined label>{{ $t('plugins.WorkshopService.access.profiles_type_' + (r.base ? 'base' : 'own')) }}</v-chip></td>
						<td>{{ r.rules }}</td>
						<td>{{ r.base ? '-' : $t('plugins.WorkshopService.access.profiles_version_short', { n: r.version }) }}</td>
						<td>
							<span v-if="r.neverAttached">{{ $t('plugins.WorkshopService.access.profiles_never_attached') }}</span>
							<span v-else-if="!r.users.length && !r.groups.length">{{ $t('plugins.WorkshopService.access.profiles_holders_nobody') }}</span>
							<span v-else>{{ $t('plugins.WorkshopService.access.profiles_holders_count', { people: r.users.length, groups: r.groups.length }) }}</span>
						</td>
						<td class="access-cell-act"><v-btn small outlined class="access-touch" @click="$emit('open', { name: r.name, base: r.base })">{{ $t('plugins.WorkshopService.access.common_' + (r.base ? 'view' : 'open')) }}</v-btn></td>
					</tr>
				</tbody>
			</table>
		</div>
		<div class="wf-help mt-2">{{ $t('plugins.WorkshopService.access.profiles_limits', { profiles: limits.profiles, rules: limits.rules, versions: limits.versions }) }}</div>
	</div>
</template>

<script>
'use strict'

import { KINDS, profileRows } from './access-profile-view.js'

export default {
	props: { list: { type: Object, default: () => ({}) } },
	data() {
		return { kind: 'all', text: '', kinds: KINDS }
	},
	computed: {
		rows() {
			return profileRows(this.list, this.kind, this.text)
		},
		ownCount() {
			return ((this.list && this.list.profiles) || []).length
		},
		limits() {
			return Object.assign({ profiles: 0, rules: 0, versions: 0 }, (this.list && this.list.limits) || {})
		}
	}
}
</script>

<style>
.access-filters { display: flex; align-items: center; flex-wrap: wrap; gap: 8px 16px; margin-bottom: 8px; }
.access-search { max-width: 320px; }
.access-kinds { display: inline-flex; border: 1px solid var(--wf-line); border-radius: 8px; overflow: hidden; }
.access-kind { padding: 0 14px; background: transparent; color: inherit; font-size: 13px; cursor: pointer; border: 0; }
.access-kind.is-on { font-weight: 600; background: rgba(128, 128, 128, 0.18); }
.access-table-wrap { overflow-x: auto; max-width: 100%; border: 1px solid var(--wf-line); border-radius: 8px; }
.access-table { border-collapse: collapse; width: 100%; font-size: 13px; }
.access-table th, .access-table td { padding: 4px 10px; border-bottom: 1px solid var(--wf-line); text-align: left; vertical-align: middle; }
.access-row { height: 44px; }
@media (max-width: 900px) {
	.access-table thead { display: none; }
	.access-table, .access-table tbody, .access-table tr, .access-table td { display: block; width: 100%; }
	.access-row { height: auto; padding: 8px 4px; border-bottom: 1px solid var(--wf-line); }
	.access-table td { border-bottom: 0; padding: 2px 10px; }
}
</style>
