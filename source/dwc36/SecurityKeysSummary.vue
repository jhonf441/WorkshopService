<template>
	<!-- The keys in the report: COUNTS by state and the EXCEPTIONS (a key that is expired or has never been used), with the button to open each one and the link to
	     the one list of keys (Access > Keys). The table of every key is not repeated here: it has one place. The words of the state and the columns are the ones of
	     Access > Keys (keys_state_*). A key is opened in its card there.
	       <security-keys-summary :overview="keysOverview(answer)" @open="{ id, name }" @open-all /> -->
	<div class="security-keys">
		<div class="wf-help mb-2">{{ rt('report_keys_counts', { total: overview.total, active: overview.active, off: overview.off, expired: overview.expired, unused: overview.unused }) }}</div>
		<div v-if="!overview.total" class="wf-help access-own-empty">{{ rt('keys_empty') }}</div>
		<div v-else-if="!overview.exceptions.length" class="wf-help access-own-empty">{{ rt('report_keys_none_exceptions') }}</div>
		<div v-else class="access-table-wrap">
			<table class="access-table security-table">
				<thead>
					<tr>
						<th>{{ rt('keys_col_name') }}</th>
						<th>{{ rt('keys_col_state') }}</th>
						<th>{{ rt('report_keys_col_why') }}</th>
						<th></th>
					</tr>
				</thead>
				<tbody>
					<tr v-for="r in overview.exceptions" :key="r.id || r.name" class="access-row security-key" :class="{ 'is-unused': r.unused }">
						<td class="access-cell-name"><strong>{{ r.name }}</strong></td>
						<td><v-chip small outlined label :color="r.status === 'active' ? 'success' : r.status === 'ended' ? 'error' : ''">{{ rt('keys_state_' + r.status) }}</v-chip></td>
						<td>
							<v-chip v-if="r.status === 'ended'" small outlined label color="error" class="mr-1">{{ rt('report_keys_why_ended') }}</v-chip>
							<v-chip v-if="r.unused" small outlined label color="warning">{{ rt('report_keys_why_unused') }}</v-chip>
						</td>
						<td class="access-cell-act"><v-btn small outlined class="access-touch" @click="$emit('open', { id: r.id, name: r.name })">{{ rt('review_open_key') }}</v-btn></td>
					</tr>
				</tbody>
			</table>
		</div>
		<v-btn small outlined class="access-touch mt-2" @click="$emit('open-all')"><v-icon left small>mdi-key-chain</v-icon>{{ rt('report_keys_all') }}</v-btn>
	</div>
</template>

<script>
'use strict'

import { translatorMixin } from './access-report-view.js'

export default {
	mixins: [translatorMixin],
	props: {
		overview: { type: Object, default: () => ({ total: 0, active: 0, off: 0, expired: 0, unused: 0, exceptions: [] }) }
	}
}
</script>
