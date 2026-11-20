<template>
	<!-- Section "Security" of the service page (administrator only). The tab shown is the one the page names (`tab`: review, report or activity): Review
	     and Report are read only and their buttons ask the page to show the Access tab AND the object (`go-access` { tab, name?, id? }); Recorded activity
	     is the audit trail. A button that moves to another tab of this section tells the page back (event `tab`). Emits `chain` (true when the chain of
	     the recorded activity was found broken), `damaged` (the access file is damaged, from what the screens already read). Users turned off are said by the band of the page. -->
	<div class="security-section">
		<!-- ONE reason for the buttons of the activity tab that change settings or export (nothing is drawn for a person who may) -->
		<access-lock-reason v-if="current === 'activity'" :ops="ACTIVITY_OPS" class="mb-3" @see-profiles="$emit('go-access', { tab: 'profiles' })" />
		<security-review v-if="current === 'review'" @open-profile="name => $emit('go-access', { tab: 'profiles', name })" @open-person="name => $emit('go-access', { tab: 'people', name })" @open-key="k => $emit('go-access', { tab: 'keys', id: k && k.id, name: k && k.name })" @damaged="v => $emit('damaged', v)" />
		<security-report v-else-if="current === 'report'" @open-person="name => $emit('go-access', { tab: 'people', name })" @open-can="name => $emit('go-access', { tab: 'can', name })" @open-activity="$emit('tab', 'activity')" @open-key="k => $emit('go-access', { tab: 'keys', id: k && k.id, name: k && k.name })" @damaged="v => $emit('damaged', v)" />
		<audit-card v-else :operations="operations" @chain="v => $emit('chain', v)" />
	</div>
</template>

<script>
'use strict'

import SecurityReview from './SecurityReview.vue'
import SecurityReport from './SecurityReport.vue'
import AuditCard from './AuditCard.vue'
import { accessCanMixin } from './reason-mixin.js'
import AccessLockReason from './AccessLockReason.vue'

const ACTIVITY_OPS = ['audit.settings', 'audit.export', 'audit.verify']
const TABS = ['review', 'report', 'activity']

export default {
	components: { AccessLockReason, SecurityReview, SecurityReport, AuditCard },
	mixins: [accessCanMixin],
	props: {
		operations: { type: Array, default: () => [] }, // the API description, for the operation pickers
		tab: { type: String, default: '' } // the tab the page shows ('' = the activity, the first the old page drew)
	},
	data() {
		return { ACTIVITY_OPS }
	},
	computed: {
		current() {
			return TABS.indexOf(this.tab) >= 0 ? this.tab : 'activity'
		},
	}
}
</script>

<style>
.access-touch { min-height: 40px; }
</style>
