<template>
	<!-- THE table of keys (Access > Keys, one card for every screen): name, state (one word: Active / Expired / Off, text and not only colour), what it can do (ONE
	     phrase: its classes and how many operations it may call), last use (times), expires, created and the actions. Under 900 px the rows become cards.
	       <access-key-list :rows="keyRows(...)" :now="epoch seconds" :total="how many keys exist" :can-change="bool" @open="id" @edit="row" @toggle="{ row, on }" @remove="row" /> -->
	<div class="access-key-list">
		<div v-if="!rows.length" class="wf-help access-own-empty">{{ $t('plugins.WorkshopService.access.' + (total ? 'keys_none_found' : 'keys_empty')) }}</div>
		<div v-else class="access-table-wrap">
			<table class="access-table">
				<thead>
					<tr>
						<th>{{ $t('plugins.WorkshopService.access.keys_col_name') }}</th>
						<th>{{ $t('plugins.WorkshopService.access.keys_col_state') }}</th>
						<th>{{ $t('plugins.WorkshopService.access.keys_col_can') }}</th>
						<th>{{ $t('plugins.WorkshopService.access.keys_col_last_use') }}</th>
						<th>{{ $t('plugins.WorkshopService.access.keys_col_ends') }}</th>
						<th>{{ $t('plugins.WorkshopService.access.keys_col_created') }}</th>
						<th></th>
					</tr>
				</thead>
				<tbody>
					<tr v-for="r in rows" :key="r.id" class="access-row">
						<td class="access-cell-name"><strong>{{ r.name }}</strong></td>
						<td><v-chip small outlined label :color="chipColor(r.status)">{{ $t('plugins.WorkshopService.access.keys_state_' + r.status) }}</v-chip></td>
						<td>
							{{ canText(r) }}
							<v-chip v-if="r.wide" small outlined label>{{ $t('plugins.WorkshopService.access.keys_reach_wide') }}</v-chip>
							<v-chip v-if="r.raw.strict === false" small outlined label color="warning" :title="$t('plugins.WorkshopService.keys.cap_legacy_hint')">{{ $t('plugins.WorkshopService.keys.cap_legacy') }}</v-chip>
						</td>
						<td>
							<span v-if="last(r).never">{{ $t('plugins.WorkshopService.access.common_never') }}</span>
							<span v-else-if="last(r).today">{{ $t('plugins.WorkshopService.access.keys_idle_today') }}</span>
							<span v-else>{{ $tc('plugins.WorkshopService.access.keys_idle_days', last(r).days, { n: last(r).days }) }}</span>
							<span v-if="r.uses" class="access-key-uses"> ({{ r.uses }})</span>
							<v-chip v-if="r.unused" small outlined label color="warning" class="access-unused-mark">{{ $tc('plugins.WorkshopService.access.keys_unused_days', r.unused.days, { n: r.unused.days }) }}</v-chip>
						</td>
						<td>
							{{ expiry(r).none ? $t('plugins.WorkshopService.access.keys_no_end') : expiry(r).at }}
							<v-chip v-if="expiry(r).soon" small outlined label color="warning">{{ $t('plugins.WorkshopService.keys.expires_soon') }}</v-chip>
						</td>
						<td>{{ date(r.created) }}</td>
						<td class="access-cell-act">
							<v-btn small outlined class="access-touch" @click="$emit('open', r.id)">{{ $t('plugins.WorkshopService.access.common_open') }}</v-btn>
							<template v-if="canChange">
								<sv-toggle :value="r.status === 'active'" :label="$t('plugins.WorkshopService.access.keys_switch')" :disabled="r.status === 'ended'" @input="v => $emit('toggle', { row: r, on: v })" />
								<v-btn icon small class="access-touch" :title="$t('plugins.WorkshopService.keys.edit')" :aria-label="$t('plugins.WorkshopService.keys.edit')" @click="$emit('edit', r)"><v-icon small>mdi-pencil</v-icon></v-btn>
								<v-btn icon small color="error" class="access-touch" :title="$t('plugins.WorkshopService.keys.revoke')" :aria-label="$t('plugins.WorkshopService.keys.revoke')" @click="$emit('remove', r)"><v-icon small>mdi-delete</v-icon></v-btn>
							</template>
						</td>
					</tr>
				</tbody>
			</table>
		</div>
	</div>
</template>

<script>
'use strict'

import SvToggle from './ui/SvToggle.vue'
import { canOf, dateOf, expiryOf, lastUseOf } from './access-keys-view.js'
import { classKey } from './key-names.js'

export default {
	components: { SvToggle },
	props: {
		rows: { type: Array, default: () => [] },
		total: { type: Number, default: 0 },
		now: { type: Number, default: 0 },
		// the person may change keys: the switch, the pencil and the bin are drawn (the service refuses anyway; the lock reason says why they are not)
		canChange: { type: Boolean, default: false }
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
		},
		// the colour never carries the state alone: the chip says it in words
		chipColor(status) {
			return status === 'active' ? 'success' : status === 'ended' ? 'error' : ''
		},
		// THE phrase of what a key can do, the same in every screen: "Read, Move: 112 operations" (+ ", 2 capabilities" when it names some)
		canText(r) {
			const c = canOf(r)
			const classes = c.classes.map(k => this.$t('plugins.WorkshopService.' + classKey(k))).join(', ')
			const ops = this.$tc('plugins.WorkshopService.access.operations_n', c.ops, { n: c.ops })
			const caps = c.caps ? ', ' + this.$tc('plugins.WorkshopService.access.capabilities_n', c.caps, { n: c.caps }) : ''
			return (classes ? classes + ': ' : '') + ops + caps
		}
	}
}
</script>
