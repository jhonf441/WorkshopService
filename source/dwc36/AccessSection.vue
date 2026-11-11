<template>
	<!-- Section "Access" of the service page (administrator only). Tabs: Profiles (step 1, read only), People and groups and Keys (they come in later steps and
	     say so through the state component). The notice of users turned off is fixed on top. -->
	<div class="access-section">
		<access-users-notice v-if="usersOff" class="mb-3" @go-users="$emit('go-users')" />
		<v-tabs v-model="tab" height="40" show-arrows class="mb-3">
			<v-tab v-for="t in tabs" :key="t">{{ $t('plugins.WorkshopService.access.tab_' + t) }}</v-tab>
		</v-tabs>
		<access-profiles v-if="tab === 0" />
		<access-state v-else state="later" />
		<access-change-dialog v-model="dialog" />
	</div>
</template>

<script>
'use strict'

import AccessState from './AccessState.vue'
import AccessChangeDialog from './AccessChangeDialog.vue'
import AccessProfiles from './AccessProfiles.vue'
import AccessUsersNotice from './AccessUsersNotice.vue'
import { roleMixin } from './role-mixin.js'
import { currentIdentity } from './workshop-api.js'

export default {
	components: { AccessState, AccessChangeDialog, AccessProfiles, AccessUsersNotice },
	mixins: [roleMixin],
	data() {
		return { tab: 0, tabs: ['profiles', 'people', 'keys'], dialog: false }
	},
	computed: {
		// users turned off (or none created): everybody is an administrator today
		usersOff() {
			void this.identityTick
			const i = currentIdentity()
			return !!i && (i.configured === false || !!i.users_disabled)
		}
	}
}
</script>

<style>
.access-section .v-tab { min-height: 40px; }
.access-touch { min-height: 40px; }
</style>
