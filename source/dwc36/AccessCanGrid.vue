<template>
	<!-- All the people by areas at a glance. Each cell is a button 40 px high with icon and word; touching it opens that person (event `open` { name, area }).
	     From 900 px down the table becomes one card per person with its two most restricted areas (the same rule as the other tables of Access).
	       <access-can-grid :rows="gridRows(views)" @open="..." /> -->
	<div class="can-grid">
		<div v-if="!rows.length" class="wf-help">{{ $t('plugins.WorkshopService.access.who_none') }}</div>
		<template v-else>
			<div class="can-table-wrap">
				<table class="can-table">
					<thead>
						<tr>
							<th scope="col">{{ $t('plugins.WorkshopService.access.who_col_person') }}</th>
							<th v-for="a in areas" :key="a.id" scope="col"><v-icon x-small aria-hidden="true">{{ a.icon }}</v-icon> {{ $t('plugins.WorkshopService.access.area_short_' + a.id) }}</th>
						</tr>
					</thead>
					<tbody>
						<tr v-for="r in rows" :key="r.name">
							<th scope="row" class="can-person"><strong>{{ r.name }}</strong><div class="wf-help">{{ roleLabel(r.role) }}</div></th>
							<td v-for="a in areas" :key="a.id">
								<button type="button" class="can-cell access-touch" :aria-label="$t('plugins.WorkshopService.access.who_open_area', { person: r.name, area: areaName(a.id) })" @click="$emit('open', { name: r.name, area: a.id })">
									<access-can-state :state="r.cells[a.id]" compact />
								</button>
							</td>
						</tr>
					</tbody>
				</table>
			</div>
			<div class="can-legend" data-part="legend">
				<span class="can-legend-title">{{ $t('plugins.WorkshopService.access.who_legend_title') }}</span>
				<span v-for="s in LEGEND" :key="s" class="can-legend-item"><access-can-state :state="s" compact /><span class="wf-help">{{ $t('plugins.WorkshopService.access.who_state_' + s) }}</span></span>
			</div>
			<div class="can-cards">
				<div v-for="r in rows" :key="'c:' + r.name" class="can-card">
					<div class="can-card-head"><strong>{{ r.name }}</strong><span class="wf-help">{{ roleLabel(r.role) }}</span></div>
					<div v-for="x in restricted(r)" :key="x.id" class="can-card-area">
						<span>{{ areaName(x.id) }}</span><access-can-state :state="x.state" />
					</div>
					<div v-if="!restricted(r).length" class="can-card-area"><access-can-state state="can" /></div>
					<v-btn small outlined class="access-touch mt-2" @click="$emit('open', { name: r.name, area: '' })">{{ $t('plugins.WorkshopService.access.common_open') }}</v-btn>
				</div>
			</div>
		</template>
	</div>
</template>

<script>
'use strict'

import AccessCanState from './AccessCanState.vue'
import { AREAS } from './access-areas.js'
import { isBaseRole } from './access-people-view.js'
import { restrictedAreas } from './who-can-view.js'

export default {
	name: 'AccessCanGrid',
	components: { AccessCanState },
	props: { rows: { type: Array, default: () => [] } },
	computed: {
		areas() { return AREAS },
		LEGEND() { return ['can', 'view', 'partial', 'cannot', 'admin_only', 'stop'] }
	},
	methods: {
		areaName(id) { return this.$t('plugins.WorkshopService.access.area_' + id) },
		roleLabel(r) { return isBaseRole(r) ? this.$t('plugins.WorkshopService.users.role_' + r) : r },
		restricted(r) { return restrictedAreas(r.cells, 2) }
	}
}
</script>

<style>
.can-table-wrap { overflow-x: auto; max-width: 100%; border: 1px solid var(--wf-line); border-radius: 8px; }
.can-table { border-collapse: collapse; width: 100%; font-size: 12px; }
.can-table th, .can-table td { padding: 10px 12px; border-bottom: 1px solid var(--wf-line); text-align: left; vertical-align: middle; }
.can-legend { display: flex; flex-wrap: wrap; align-items: center; gap: 8px 16px; margin-top: 12px; }
.can-legend-title { font-size: 12px; font-weight: 600; }
.can-legend-item { display: inline-flex; align-items: center; gap: 6px; }
.can-person { min-width: 130px; font-size: 13px; }
.can-cell { display: block; width: 100%; min-width: 40px; padding: 0; border: 0; background: transparent; color: inherit; cursor: pointer; text-align: left; }
.can-cards { display: none; }
.can-card { padding: 10px 4px; border-bottom: 1px solid var(--wf-line); }
.can-card-head { display: flex; gap: 8px; align-items: baseline; margin-bottom: 4px; }
.can-card-area { display: flex; align-items: center; justify-content: space-between; gap: 8px; padding: 2px 0; font-size: 13px; }
@media (max-width: 900px) {
	.can-table-wrap { display: none; }
	.can-cards { display: block; }
}
</style>
