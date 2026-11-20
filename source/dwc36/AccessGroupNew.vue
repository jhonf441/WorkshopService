<template>
	<!-- Create a group (administrators only): a name and a description; profiles, ceiling and people are added in its card. The name rule is shown before it is sent
	     and the service has the last word. Goes through AccessEditDialog (operation access.groups.set, through the dialog).
	       <access-group-new :groups="answer of access.groups.list" :locked="false" @created="reload()" /> -->
	<div class="access-group-new mb-3">
		<v-btn small color="primary" class="access-touch" :disabled="locked" @click="open = !open"><v-icon left small>mdi-plus</v-icon>{{ $t('plugins.WorkshopService.access.groups_new') }}</v-btn>
		<div v-if="open" class="access-group-new-form">
			<sv-text-field v-model="name" maxlength="32" :label="$t('plugins.WorkshopService.access.groups_name')" :error="problemText" />
			<div class="wf-help">{{ $t('plugins.WorkshopService.access.groups_name_rule') }}</div>
			<sv-text-field v-model="description" maxlength="200" :label="$t('plugins.WorkshopService.access.groups_description')" />
			<v-btn small color="primary" class="access-touch" :disabled="locked || !!problem || !name" @click="ask()">{{ $t('plugins.WorkshopService.access.change_do_group_create') }}</v-btn>
		</div>
		<access-state v-if="stale" state="stale" />
		<v-alert v-if="refused" type="warning" outlined dense class="mb-2" role="alert">{{ $t('plugins.WorkshopService.access.pedit_precheck_refused') }} {{ refused }}</v-alert>
		<access-edit-dialog :change="change" :before="null" view="group" :groups="groups" @cancel="change = null" @done="done()" @stale="gone()" />
	</div>
</template>

<script>
'use strict'

import SvTextField from './ui/SvTextField.vue'
import AccessState from './AccessState.vue'
import AccessEditDialog from './AccessEditDialog.vue'
import { askMixin } from './access-ask-mixin.js'
import { BASE_ROLES } from './access-people-view.js'
import { groupNameProblem } from './access-edit-view.js'

const ROLE_NONE = 'none' // role_store.NONE_ROLE: not a name for a group either

export default {
	components: { SvTextField, AccessState, AccessEditDialog },
	mixins: [askMixin],
	props: {
		groups: { type: Object, default: null }, // access.groups.list
		locked: { type: Boolean, default: false }
	},
	data() {
		return { open: false, name: '', description: '', change: null, stale: false }
	},
	watch: {
		name() {
			this.refused = ''
		}
	},
	computed: {
		clean() {
			return String(this.name || '').split(/\s+/).filter(Boolean).join(' ')
		},
		// the custom roles are shown as groups: their names are taken too
		reserved() {
			const roles = ((this.groups && this.groups.groups) || []).filter(g => g.source === 'role').map(g => g.name)
			return BASE_ROLES.concat([ROLE_NONE], roles)
		},
		problem() {
			return this.name ? groupNameProblem(this.name, this.groups, this.reserved) : ''
		},
		problemText() {
			return this.problem ? [this.$t('plugins.WorkshopService.access.' + this.problem)] : []
		}
	},
	methods: {
		async ask() {
			if (this.locked || this.problem || this.checking) return
			this.stale = false
			const change = { kind: 'group_save', object: this.clean, name: this.clean, description: this.description }
			if (await this.passes(change)) this.change = change
		},
		done() {
			this.change = null
			this.open = false
			this.name = ''
			this.description = ''
			this.$emit('created')
		},
		// a group with that name appeared while the dialog was open: nothing was saved
		gone() {
			this.change = null
			this.stale = true
			this.$emit('created')
		}
	}
}
</script>

<style>
.access-group-new-form { display: flex; flex-direction: column; gap: 8px; max-width: 420px; margin-top: 8px; }
</style>
