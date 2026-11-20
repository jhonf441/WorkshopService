<template>
	<!-- The people of the report: role, groups and profiles, who decides their access, last sign-in, sessions, age of the PIN, lock with the time left and last use.
	     A person who is locked or who never signed in carries a chip. Sorting is a field and a direction (buttons of 40 px, no click on a header needed);
	     under 900 px the rows become cards (rules in AccessProfileList.vue).
	       <security-people-table :rows="peopleRows(...)" :now="answer.generated" :sort="{ field, dir }" @sort="s => ..." @open="name => ..." /> -->
	<div class="security-people-table">
		<div class="access-filters">
			<sv-select :value="sort.field" :items="fields" class="security-sort" :label="rt('report_sort')" :aria-label="rt('report_sort')" @input="$emit('sort', { field: $event, dir: sort.dir })" />
			<v-btn small outlined class="access-touch" :aria-label="rt('report_sort_' + sort.dir)" @click="$emit('sort', { field: sort.field, dir: sort.dir === 'asc' ? 'desc' : 'asc' })"><v-icon left small>{{ sort.dir === 'asc' ? 'mdi-sort-ascending' : 'mdi-sort-descending' }}</v-icon>{{ rt('report_sort_' + sort.dir) }}</v-btn>
		</div>
		<div v-if="!rows.length" class="wf-help access-own-empty">{{ rt('report_empty') }}</div>
		<div v-else class="access-table-wrap">
			<table class="access-table security-table">
				<thead>
					<tr>
						<th>{{ rt('report_col_person') }}</th>
						<th>{{ rt('report_col_role') }}</th>
						<th>{{ rt('report_col_access') }}</th>
						<th>{{ rt('report_col_last_login') }}</th>
						<th>{{ rt('report_col_sessions') }}</th>
						<th>{{ rt('report_col_pin_age') }}</th>
						<th>{{ rt('report_col_lock') }}</th>
						<th>{{ rt('report_col_last_use') }}</th>
						<th></th>
					</tr>
				</thead>
				<tbody>
					<tr v-for="r in rows" :key="r.name" class="access-row security-person" :class="{ 'is-locked': r.locked, 'is-never': r.neverSignedIn }">
						<td class="access-cell-name"><strong>{{ r.name }}</strong></td>
						<td>{{ r.customRole ? r.role : rt('users.role_' + r.role) }}</td>
						<td>
							<v-chip small outlined label :color="r.governed ? 'info' : ''">{{ rt(r.governed ? 'report_governed' : 'report_base_only') }}</v-chip>
							<div class="wf-help">{{ detail(r) }}</div>
						</td>
						<td>
							<v-chip v-if="r.neverSignedIn" small outlined label color="warning" class="security-never">{{ rt('report_never_signed') }}</v-chip>
							<span v-else>{{ ago(r.lastLogin) }}</span>
						</td>
						<td>{{ r.sessions }}</td>
						<td>{{ r.pinAgeDays === null ? '-' : rt('report_pin_days', { n: r.pinAgeDays }, r.pinAgeDays) }}</td>
						<td>
							<v-chip v-if="r.locked" small outlined label color="error" class="security-locked">{{ rt('report_locked', { time: duration(r.lockedFor) }) }}</v-chip>
							<span v-else>-</span>
						</td>
						<td>{{ r.lastUse === null ? '-' : ago(r.lastUse) }}</td>
						<td class="access-cell-act"><v-btn small outlined class="access-touch" @click="$emit('open', r.name)">{{ rt('common_open') }}</v-btn></td>
					</tr>
				</tbody>
			</table>
		</div>
	</div>
</template>

<script>
'use strict'

import SvSelect from './ui/SvSelect.vue'
import { PEOPLE_SORTS, agoText, durationText, translatorMixin } from './access-report-view.js'

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
			return PEOPLE_SORTS.map((f) => ({ value: f, text: this.rt('report_sort_' + f) }))
		}
	},
	methods: {
		ago(epoch) {
			return agoText(this.rt, this.now, epoch)
		},
		duration(s) {
			return durationText(this.rt, s)
		},
		// groups and profiles of the person in one line; "None" when they have neither
		detail(r) {
			const parts = r.groups.concat(r.profiles)
			return parts.length ? parts.join(', ') : this.rt('common_none')
		}
	}
}
</script>

<style>
.security-sort { max-width: 240px; }
.security-table .wf-help { margin: 2px 0 0; }
</style>
