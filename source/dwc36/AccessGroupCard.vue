<template>
	<!-- The card of one group, read only. A custom role appears as a group with one profile and says it is edited in Users. Operation: access.groups.get.
	       <access-group-card :name="'Workshop'" @back="..." /> -->
	<div class="access-group-card">
		<div class="access-view-head">
			<v-btn small outlined class="access-touch" @click="$emit('back')"><v-icon left small>mdi-arrow-left</v-icon>{{ $t('plugins.WorkshopService.access.common_back') }}</v-btn>
			<strong class="access-view-name">{{ name }}</strong>
			<v-chip v-if="got" small outlined label>{{ $t('plugins.WorkshopService.access.groups_kind_' + (isRole ? 'role' : 'group')) }}</v-chip>
		</div>
		<access-state :state="state" :detail="detail" @retry="load()">
			<template v-if="got">
				<div v-if="isRole" class="wf-note mb-2" role="note"><v-icon class="wf-note-icon" aria-hidden="true">mdi-lock-outline</v-icon><span>{{ $t('plugins.WorkshopService.access.groups_role_readonly') }}</span></div>
				<div v-if="got.description" class="mb-2">{{ got.description }}</div>
				<div v-if="isRole" class="wf-help mb-2">{{ $t('plugins.WorkshopService.access.groups_role_base', { base: baseLabel }) }} {{ $t('plugins.WorkshopService.access.groups_role_counts', { grants: $tc('plugins.WorkshopService.access.entries_n', grants, { n: grants }), denies: denies }) }}</div>
				<div class="access-person-line"><span class="access-rule-label">{{ $t('plugins.WorkshopService.access.groups_col_profiles') }}</span>
					<v-chip v-for="p in got.profiles" :key="'p:' + p" small outlined label><profile-name :id="p" /></v-chip>
					<span v-if="!got.profiles.length">{{ $t('plugins.WorkshopService.access.groups_profiles_none') }}</span>
				</div>
				<div v-if="!isRole" class="access-person-line"><span class="access-rule-label">{{ $t('plugins.WorkshopService.access.groups_col_ceiling') }}</span>
					<v-chip v-if="got.ceiling" small outlined label><profile-name :id="got.ceiling" /></v-chip>
					<span v-else>{{ $t('plugins.WorkshopService.access.people_ceiling_none') }}</span>
				</div>
				<div class="access-person-line"><span class="access-rule-label">{{ $t('plugins.WorkshopService.access.groups_members') }}</span><access-term-help term="group" />
					<v-chip v-for="m in got.members" :key="'m:' + m" small outlined label>{{ m }}</v-chip>
					<span v-if="!got.members.length">{{ $t('plugins.WorkshopService.access.groups_members_none') }}</span>
				</div>
				<access-group-edit v-if="!isRole" :group="got" :users="users" :groups="groups" :damaged="damaged" @changed="changed()" @removed="$emit('changed'); $emit('back')" />
			</template>
		</access-state>
	</div>
</template>

<script>
'use strict'

import AccessState from './AccessState.vue'
import AccessTermHelp from './AccessTermHelp.vue'
import ProfileName from './ProfileName.vue'
import AccessGroupEdit from './AccessGroupEdit.vue'
import { accessApi } from './access-api.js'
import { isBaseRole } from './access-people-view.js'
import { stateOfError } from './access-profile-view.js'

export default {
	components: { AccessTermHelp, ProfileName, AccessState, AccessGroupEdit },
	props: {
		name: { type: String, required: true },
		users: { type: Array, default: () => [] }, // users.list: the people that can join the group
		groups: { type: Object, default: null }, // access.groups.list
		damaged: { type: Boolean, default: false }
	},
	data() {
		return { got: null, state: 'loading', detail: '' }
	},
	computed: {
		isRole() {
			return !!this.got && this.got.source === 'role'
		},
		grants() {
			return this.got && this.got.role ? (this.got.role.grant || []).length : 0
		},
		denies() {
			return this.got && this.got.role ? (this.got.role.deny || []).length : 0
		},
		baseLabel() {
			const b = this.got && this.got.role ? this.got.role.base : ''
			return isBaseRole(b) ? this.$t('plugins.WorkshopService.users.role_' + b) : b
		}
	},
	watch: {
		name() {
			this.load()
		}
	},
	created() {
		this.load()
	},
	methods: {
		changed() {
			this.load(true)
			this.$emit('changed')
		},
		async load(quiet) {
			if (!quiet) this.state = 'loading'
			this.detail = ''
			try {
				const a = await accessApi.groupsGet(this.name)
				this.got = Object.assign({ profiles: [], members: [] }, a.group)
				this.state = ''
			} catch (e) {
				this.got = null
				this.state = stateOfError(e)
				this.detail = (e && e.message) || ''
			}
		}
	}
}
</script>
