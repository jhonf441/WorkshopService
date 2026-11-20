<template>
	<!-- The dialog of a change of a profile (save a version, go back to one, remove, compare): AccessChangeDialog with the before and after of the profile
	     document, what changes in practice, the warnings of the dry run and the risk 4 box. The only way a profile changes. The service is told "confirmed"
	     by the parent (confirm: true) after the "Understood" box and the verb of this dialog, so there is one window, not two.
	       <access-profile-change v-model="open" :title="..." :confirm-label="..." :diff="diff" :attached="{ users, groups }" :warnings="[...]" :risk4="false" :drop="null" :busy :error @confirm="..." /> -->
	<access-change-dialog :value="value" :title="title" :confirm-label="confirmLabel" :risk4="risk4" :view-only="viewOnly" :busy="busy" :error="error" @input="v => $emit('input', v)" @confirm="$emit('confirm')">
		<template #before><access-profile-diff :diff="diff" side="before" :is-new="isNew" /></template>
		<template #after><access-profile-diff :diff="diff" side="after" /></template>
		<template #summary>
			<div v-if="!removing" class="access-change-line">{{ practice }}</div>
			<div v-if="gains && !removing" class="access-change-line">{{ $tc('plugins.WorkshopService.access.diff_gains', gains, { n: gains }) }}</div>
			<div v-if="loses && !removing" class="access-change-line">{{ $tc('plugins.WorkshopService.access.diff_loses', loses, { n: loses }) }}</div>
			<div v-if="removing" class="access-change-line">{{ $t('plugins.WorkshopService.access.diff_remove_all') }}</div>
			<div v-if="diff.highestRisk" class="access-change-line">{{ $t('plugins.WorkshopService.access.diff_highest_risk', { n: diff.highestRisk }) }}</div>
			<div v-if="drop" class="access-change-line">{{ $t('plugins.WorkshopService.access.diff_drop_oldest', { n: drop }) }}</div>
			<div v-for="w in warnings" :key="w.code" class="access-change-line access-warning" role="note">{{ w.text }}</div>
		</template>
	</access-change-dialog>
</template>

<script>
'use strict'

import AccessChangeDialog from './AccessChangeDialog.vue'
import AccessProfileDiff from './AccessProfileDiff.vue'
import { changeSize } from './access-profile-edit.js'

export default {
	components: { AccessChangeDialog, AccessProfileDiff },
	props: {
		value: { type: Boolean, default: false },
		title: { type: String, default: '' },
		confirmLabel: { type: String, default: '' },
		diff: { type: Object, required: true },
		attached: { type: Object, default: () => ({ users: [], groups: [] }) },
		warnings: { type: Array, default: () => [] },
		risk4: { type: Boolean, default: false },
		drop: { type: Number, default: null },
		isNew: { type: Boolean, default: false },
		removing: { type: Boolean, default: false },
		viewOnly: { type: Boolean, default: false },
		busy: { type: Boolean, default: false },
		error: { type: String, default: '' }
	},
	computed: {
		gains() {
			return changeSize(this.diff).gains
		},
		loses() {
			return changeSize(this.diff).loses
		},
		practice() {
			const people = (this.attached.users || []).length
			const groups = (this.attached.groups || []).length
			if (!people && !groups) return this.$t('plugins.WorkshopService.access.diff_nobody')
			return this.$t('plugins.WorkshopService.access.diff_in_practice', { people: this.$tc('plugins.WorkshopService.access.people_n', people, { n: people }), groups: this.$tc('plugins.WorkshopService.access.groups_n', groups, { n: groups }) })
		}
	}
}
</script>
