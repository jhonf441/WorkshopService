<template>
	<!-- The table of keys (read only): name, state, reach, access profile (always "key format" while no operation gives a key a profile), last use with the
	     mark of a wide key that is not used (only when the review has the finding), created. Under 900 px the rows become cards (rules in AccessProfileList.vue).
	       <access-key-list :rows="keyRows(...)" :now="epoch seconds" :total="how many keys exist" @open="id => ..." /> -->
	<div class="access-key-list">
		<div v-if="!rows.length" class="wf-help access-own-empty">{{ $t('plugins.WorkshopService.access.' + (total ? 'keys_none_found' : 'keys_empty')) }}</div>
		<div v-else class="access-table-wrap">
			<table class="access-table">
				<thead>
					<tr>
						<th>{{ $t('plugins.WorkshopService.access.keys_col_name') }}</th>
						<th>{{ $t('plugins.WorkshopService.access.keys_col_state') }}</th>
						<th>{{ $t('plugins.WorkshopService.access.keys_col_reach') }}</th>
						<th>{{ $t('plugins.WorkshopService.access.keys_col_profile') }}</th>
						<th>{{ $t('plugins.WorkshopService.access.keys_col_last_use') }}</th>
						<th>{{ $t('plugins.WorkshopService.access.keys_col_created') }}</th>
						<th></th>
					</tr>
				</thead>
				<tbody>
					<tr v-for="r in rows" :key="r.id" class="access-row">
						<td class="access-cell-name"><strong>{{ r.name }}</strong></td>
						<td>
							<v-chip small outlined label :color="r.enabled ? 'success' : ''">{{ $t('plugins.WorkshopService.access.keys_state_' + (r.enabled ? 'active' : 'suspended')) }}</v-chip>
							<v-chip v-if="expiry(r).expired" small outlined label color="error">{{ $t('plugins.WorkshopService.access.keys_past_due') }}</v-chip>
						</td>
						<td>
							{{ $t('plugins.WorkshopService.access.keys_reach', { ops: $tc('plugins.WorkshopService.access.operations_n', r.allowed.length, { n: r.allowed.length }), caps: $tc('plugins.WorkshopService.access.capabilities_n', r.capCount, { n: r.capCount }) }) }}
							<v-chip v-if="r.wide" small outlined label>{{ $t('plugins.WorkshopService.access.keys_reach_wide') }}</v-chip>
						</td>
						<td class="access-key-format">{{ $t('plugins.WorkshopService.access.keys_format') }}</td>
						<td>
							<span v-if="last(r).never">{{ $t('plugins.WorkshopService.access.common_never') }}</span>
							<span v-else-if="last(r).today">{{ $t('plugins.WorkshopService.access.keys_idle_today') }}</span>
							<span v-else>{{ $tc('plugins.WorkshopService.access.keys_idle_days', last(r).days, { n: last(r).days }) }}</span>
							<v-chip v-if="r.unused" small outlined label color="warning" class="access-unused-mark">{{ $tc('plugins.WorkshopService.access.keys_unused_days', r.unused.days, { n: r.unused.days }) }}</v-chip>
						</td>
						<td>{{ date(r.created) }}</td>
						<td class="access-cell-act"><v-btn small outlined class="access-touch" @click="$emit('open', r.id)">{{ $t('plugins.WorkshopService.access.common_open') }}</v-btn></td>
					</tr>
				</tbody>
			</table>
		</div>
	</div>
</template>

<script>
'use strict'

import { dateOf, expiryOf, lastUseOf } from './access-keys-view.js'

export default {
	props: {
		rows: { type: Array, default: () => [] },
		total: { type: Number, default: 0 },
		now: { type: Number, default: 0 }
	},
	methods: {
		last(r) {
			return lastUseOf(r)
		},
		expiry(r) {
			return expiryOf(r, this.now)
		},
		date(epoch) {
			return dateOf(epoch)
		}
	}
}
</script>
