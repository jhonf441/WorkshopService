<template>
	<!-- Access > Profiles: the profiles (base, of the plugins and own) and, under them, the own roles (a base role plus capabilities given or taken away: the
	     matrix). Both are kept as they were; the own roles are also shown with the profiles of each person in "Who can do what". -->
	<div class="access-profiles-tab">
		<access-profiles :focus="focus" @damaged="v => $emit('damaged', v)" />
		<roles-card />
	</div>
</template>

<script>
'use strict'

import AccessProfiles from './AccessProfiles.vue'
import RolesCard from './RolesCard.vue'

export default {
	name: 'AccessProfilesTab',
	components: { AccessProfiles, RolesCard },
	props: { focus: { type: Object, default: null } }
}
</script>
