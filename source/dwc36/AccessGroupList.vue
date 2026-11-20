<template>
	<!-- The table of groups (read only): the groups of the access file and the custom roles, which are groups with one profile and cannot be edited here.
	       <access-group-list :rows="groupRows(answer of access.groups.list)" @open="name => ..." /> -->
	<div class="access-group-list">
		<div v-if="!rows.length" class="wf-help access-own-empty">{{ $t('plugins.WorkshopService.access.groups_empty') }}</div>
		<div v-else class="access-table-wrap">
			<table class="access-table">
				<thead>
					<tr>
						<th>{{ $t('plugins.WorkshopService.access.groups_col_name') }}</th>
						<th>{{ $t('plugins.WorkshopService.access.groups_col_kind') }}</th>
						<th>{{ $t('plugins.WorkshopService.access.groups_col_profiles') }}</th>
						<th>{{ $t('plugins.WorkshopService.access.groups_col_ceiling') }}</th>
						<th>{{ $t('plugins.WorkshopService.access.groups_col_members') }}</th>
						<th></th>
					</tr>
				</thead>
				<tbody>
					<tr v-for="r in rows" :key="(r.role ? 'r:' : 'g:') + r.name" class="access-row">
						<td class="access-cell-name"><strong>{{ r.name }}</strong></td>
						<td><v-chip small outlined label>{{ $t('plugins.WorkshopService.access.groups_kind_' + (r.role ? 'role' : 'group')) }}</v-chip></td>
						<td>{{ r.profiles.length ? r.profiles.join(', ') : $t('plugins.WorkshopService.access.groups_profiles_none') }}</td>
						<td>{{ r.ceiling || $t('plugins.WorkshopService.access.common_none') }}</td>
						<td>{{ r.members.length ? r.members.join(', ') : $t('plugins.WorkshopService.access.groups_members_none') }}</td>
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
	props: { rows: { type: Array, default: () => [] } }
}
</script>
