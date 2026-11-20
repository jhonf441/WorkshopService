<template>
	<!-- The table of people (read only): base role, groups, own profiles, ceiling and who decides their access. Under 900 px the rows become cards (rules in
	     AccessProfileList.vue). The empty sentence is its own: there are no people (or users are turned off).
	       <access-people-list :rows="peopleRows(...)" @open="name => ..." /> -->
	<div class="access-people-list">
		<div v-if="!rows.length" class="wf-help access-own-empty">{{ $t('plugins.WorkshopService.access.people_none') }}</div>
		<div v-else class="access-table-wrap">
			<table class="access-table">
				<thead>
					<tr>
						<th>{{ $t('plugins.WorkshopService.access.people_col_person') }}</th>
						<th>{{ $t('plugins.WorkshopService.access.people_col_role') }}</th>
						<th>{{ $t('plugins.WorkshopService.access.people_col_groups') }}</th>
						<th>{{ $t('plugins.WorkshopService.access.people_col_profiles') }}</th>
						<th>{{ $t('plugins.WorkshopService.access.people_col_ceiling') }}</th>
						<th>{{ $t('plugins.WorkshopService.access.people_col_state') }}</th>
						<th></th>
					</tr>
				</thead>
				<tbody>
					<tr v-for="r in rows" :key="r.name" class="access-row">
						<td class="access-cell-name"><strong>{{ r.name }}</strong></td>
						<td>{{ roleLabel(r) }}</td>
						<td>{{ r.groups.length ? r.groups.join(', ') : $t('plugins.WorkshopService.access.common_none') }}</td>
						<td>{{ r.profiles.length ? r.profiles.join(', ') : $t('plugins.WorkshopService.access.common_none') }}</td>
						<td>{{ r.ceiling || $t('plugins.WorkshopService.access.common_none') }}</td>
						<td><v-chip small outlined label :color="r.state === 'governed' ? 'info' : ''">{{ $t('plugins.WorkshopService.access.people_state_' + r.state) }}</v-chip></td>
						<td class="access-cell-act"><v-btn small outlined class="access-touch" @click="$emit('open', r.name)">{{ $t('plugins.WorkshopService.access.common_open') }}</v-btn></td>
					</tr>
				</tbody>
			</table>
		</div>
	</div>
</template>

<script>
'use strict'

export default {
	props: { rows: { type: Array, default: () => [] } },
	methods: {
		roleLabel(r) {
			return r.customRole ? r.role : this.$t('plugins.WorkshopService.users.role_' + r.role)
		}
	}
}
</script>
