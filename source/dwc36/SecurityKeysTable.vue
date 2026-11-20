<template>
	<!-- The keys of the report: state, reach, last use and days without use, creation and expiry (shown as the key has it, never edited here). A key that was
	     never used carries a chip. The button asks the page to open that key.
	       <security-keys-table :rows="keyRows(...)" :now="answer.generated" :sort="{ field, dir }" @sort="s => ..." @open="key => ..." /> -->
	<div class="security-keys-table">
		<div class="access-filters">
			<sv-select :value="sort.field" :items="fields" class="security-sort" :label="rt('report_sort')" :aria-label="rt('report_sort')" @input="$emit('sort', { field: $event, dir: sort.dir })" />
			<v-btn small outlined class="access-touch" :aria-label="rt('report_sort_' + sort.dir)" @click="$emit('sort', { field: sort.field, dir: sort.dir === 'asc' ? 'desc' : 'asc' })"><v-icon left small>{{ sort.dir === 'asc' ? 'mdi-sort-ascending' : 'mdi-sort-descending' }}</v-icon>{{ rt('report_sort_' + sort.dir) }}</v-btn>
		</div>
		<div v-if="!rows.length" class="wf-help access-own-empty">{{ rt('report_keys_empty') }}</div>
		<div v-else class="access-table-wrap">
			<table class="access-table security-table">
				<thead>
					<tr>
						<th>{{ rt('report_key_col_name') }}</th>
						<th>{{ rt('report_key_col_state') }}</th>
						<th>{{ rt('report_key_col_reach') }}</th>
						<th>{{ rt('report_col_last_use') }}</th>
						<th>{{ rt('report_key_col_idle') }}</th>
						<th>{{ rt('report_key_col_created') }}</th>
						<th>{{ rt('report_key_col_end') }}</th>
						<th></th>
					</tr>
				</thead>
				<tbody>
					<tr v-for="r in rows" :key="r.id || r.name" class="access-row security-key" :class="{ 'is-unused': r.unused }">
						<td class="access-cell-name"><strong>{{ r.name }}</strong></td>
						<td><v-chip small outlined label :color="r.enabled ? 'success' : ''">{{ rt(r.enabled ? 'report_key_active' : 'report_key_suspended') }}</v-chip></td>
						<td>{{ rt('report_key_reach', { n: r.breadth }, r.breadth) }}</td>
						<td>
							<v-chip v-if="r.unused" small outlined label color="warning" class="security-unused">{{ rt('report_key_unused') }}</v-chip>
							<span v-else>{{ ago(r.lastUse) }}</span>
						</td>
						<td>{{ r.idleDays === null ? '-' : rt('report_idle_days', { n: r.idleDays }, r.idleDays) }}</td>
						<td>{{ r.created === null ? '-' : date(r.created) }}</td>
						<td>{{ r.expires === null ? '-' : date(r.expires) }}</td>
						<td class="access-cell-act"><v-btn small outlined class="access-touch" @click="$emit('open', { id: r.id, name: r.name })">{{ rt('review_open_key') }}</v-btn></td>
					</tr>
				</tbody>
			</table>
		</div>
	</div>
</template>

<script>
'use strict'

import SvSelect from './ui/SvSelect.vue'
import { KEY_SORTS, agoText, translatorMixin } from './access-report-view.js'
import { dateText } from './access-review-view.js'

export default {
	components: { SvSelect },
	mixins: [translatorMixin],
	props: {
		rows: { type: Array, default: () => [] },
		now: { type: Number, default: 0 },
		sort: { type: Object, default: () => ({ field: 'name', dir: 'asc' }) }
	},
	computed: {
		fields() {
			return KEY_SORTS.map((f) => ({ value: f, text: this.rt('report_key_sort_' + f) }))
		}
	},
	methods: {
		ago(epoch) {
			return agoText(this.rt, this.now, epoch)
		},
		date(epoch) {
			return dateText(epoch)
		}
	}
}
</script>
