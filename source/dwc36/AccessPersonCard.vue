<template>
	<!-- The card of one person, read only: base role, groups, own profiles, profiles that come through groups, ceiling and whether the profiles or the
	     table of roles decide for them; "See what this person can do" opens the tab Who can do what (event `see-can`). Operation: access.person.get.
	       <access-person-card :name="'Maria'" :role-groups="[]" :users-off="false" @back="..." /> -->
	<div class="access-person-card">
		<div class="access-view-head">
			<v-btn small outlined class="access-touch" @click="$emit('back')"><v-icon left small>mdi-arrow-left</v-icon>{{ $t('plugins.WorkshopService.access.common_back') }}</v-btn>
			<strong class="access-view-name">{{ name }}</strong>
			<v-chip v-if="got" small outlined label>{{ roleLabel(got.role) }}</v-chip>
			<v-chip v-if="got" small outlined label :color="stateState === 'governed' ? 'info' : ''">{{ $t('plugins.WorkshopService.access.people_state_' + stateState) }}</v-chip>
		</div>
		<access-state :state="state" :detail="detail" @retry="load()">
			<template v-if="got">
				<div class="wf-help mb-2">{{ $t('plugins.WorkshopService.access.people_base_role', { role: roleLabel(got.role) }) }}</div>
				<div v-if="roleGroups.length" class="wf-note mb-2" role="note"><v-icon class="wf-note-icon" aria-hidden="true">mdi-lock-outline</v-icon><span>{{ $t('plugins.WorkshopService.access.people_role_group', { names: roleGroups.join(', ') }) }}</span></div>
				<div v-if="got.role === 'admin'" class="wf-note mb-2" role="note"><v-icon class="wf-note-icon" aria-hidden="true">mdi-lock-outline</v-icon><span>{{ $t('plugins.WorkshopService.access.people_admin_locked') }}</span></div>
				<div class="wf-help mb-2">{{ $t('plugins.WorkshopService.access.people_help_' + (stateState === 'governed' ? 'governed' : 'base')) }}</div>
				<div class="access-person-line"><span class="access-rule-label">{{ $t('plugins.WorkshopService.access.people_groups') }}</span>
					<v-chip v-for="g in got.groups" :key="'g:' + g" small outlined label>{{ g }}</v-chip>
					<span v-if="!got.groups.length">{{ $t('plugins.WorkshopService.access.common_none') }}</span>
				</div>
				<div class="access-person-line"><span class="access-rule-label">{{ $t('plugins.WorkshopService.access.people_profiles') }}</span>
					<v-chip v-for="p in got.profiles" :key="'p:' + p" small outlined label><profile-name :id="p" /></v-chip>
					<span v-if="!got.profiles.length">{{ $t('plugins.WorkshopService.access.common_none') }}</span>
				</div>
				<div class="access-person-line"><span class="access-rule-label">{{ $t('plugins.WorkshopService.access.people_from_groups') }}</span>
					<span v-for="v in via" :key="'v:' + v.group" class="access-via">{{ $t('plugins.WorkshopService.access.people_via_group', { group: v.group, profiles: v.profiles.length ? v.profiles.map(profileText).join(', ') : $t('plugins.WorkshopService.access.groups_profiles_none') }) }}</span>
					<span v-if="!via.length">{{ $t('plugins.WorkshopService.access.common_none') }}</span>
				</div>
				<div class="access-person-line"><span class="access-rule-label">{{ $t('plugins.WorkshopService.access.people_ceiling') }}</span><access-term-help term="ceiling" />
					<v-chip v-if="got.ceiling" small outlined label><profile-name :id="got.ceiling" /></v-chip>
					<span v-else>{{ $t('plugins.WorkshopService.access.people_ceiling_none') }}</span>
				</div>
				<div v-if="got.ceilings.length > (got.ceiling ? 1 : 0)" class="wf-help">{{ $t('plugins.WorkshopService.access.people_ceilings', { names: got.ceilings.map(profileText).join(', ') }) }}</div>
				<div class="wf-help mb-2">{{ $t('plugins.WorkshopService.access.people_ceiling_help') }}</div>
				<access-person-edit :name="name" :person="got" :groups="groups" @changed="changed()" />
				<div class="mt-3"><v-btn small outlined class="access-touch" @click="$emit('see-can', name)"><v-icon left small>mdi-account-search-outline</v-icon>{{ $t('plugins.WorkshopService.access.people_see_can') }}</v-btn></div>
			</template>
		</access-state>
	</div>
</template>

<script>
'use strict'

import AccessState from './AccessState.vue'
import AccessTermHelp from './AccessTermHelp.vue'
import ProfileName from './ProfileName.vue'
import { displayNamesMixin } from './display-names-mixin.js'
import AccessPersonEdit from './AccessPersonEdit.vue'
import { accessApi } from './access-api.js'
import { accessStateOf, isBaseRole, viaGroups } from './access-people-view.js'
import { stateOfError } from './access-profile-view.js'

export default {
	mixins: [displayNamesMixin],
	components: { AccessTermHelp, ProfileName, AccessState, AccessPersonEdit },
	props: {
		name: { type: String, required: true },
		roleGroups: { type: Array, default: () => [] },
		usersOff: { type: Boolean, default: false },
		groups: { type: Object, default: null } // access.groups.list, for the groups that can be chosen
	},
	data() {
		return { got: null, state: 'loading', detail: '' }
	},
	computed: {
		stateState() {
			return accessStateOf(this.got)
		},
		via() {
			return viaGroups(this.got)
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
		roleLabel(r) {
			return isBaseRole(r) ? this.$t('plugins.WorkshopService.users.role_' + r) : r
		},
		// after a change the card is read again where it stands (quiet), and the screen is told so that its lists follow
		changed() {
			this.load(true)
			this.$emit('changed')
		},
		async load(quiet) {
			if (!quiet) this.state = 'loading'
			this.detail = ''
			try {
				const p = await accessApi.personGet(this.name)
				this.got = Object.assign({ groups: [], profiles: [], ceilings: [], via_groups: {} }, p)
				this.state = this.got.damaged ? 'damaged' : ''
			} catch (e) {
				this.got = null
				this.state = stateOfError(e)
				this.detail = (e && e.message) || ''
			}
		}
	}
}
</script>

<style>
.access-person-line { display: flex; align-items: center; flex-wrap: wrap; gap: 4px 8px; margin-bottom: 8px; font-size: 13px; }
.access-via { padding-right: 8px; }
</style>
