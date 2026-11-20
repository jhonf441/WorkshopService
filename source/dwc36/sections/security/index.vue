<template>
	<!-- Security: the review, the report and the recorded activity of who did what. They are the screens that were already rebuilt with their own tests
	     (dwc36/Security*.vue, AuditCard.vue), hosted here with the tab the shell names. A button that points to an object of Access asks for it through
	     core/store/access-focus.js and moves the address. Props: active (this section is in view), tab. -->
	<div class="sv-security">
		<security-section :operations="operations" :tab="tab" @tab="onTab" @chain="v => { page.chainBroken = !!v }" @go-access="goAccess" />
	</div>
</template>

<script>
import { apiOps } from '../../core/resources.js'
import { askAccess } from '../../core/store/access-focus.js'
import { pageState } from '../../core/page-state.js'
import { want } from '../../core/store/session.js'
import SecuritySection from '../../SecuritySection.vue'

export default {
	name: 'SecurityHost',
	components: { SecuritySection },
	inject: { nav: { from: 'svNav', default: () => ({ go() {}, href: () => '#' }) } },
	props: { active: { type: Boolean, default: false }, tab: { type: String, default: 'review' } },
	data() {
		return { page: pageState }
	},
	computed: {
		operations() {
			return (apiOps.data && apiOps.data.ops) || []
		}
	},
	watch: {
		active: { immediate: true, handler(on) { if (on) { want(['api.describe']); apiOps.show() } else apiOps.hide() } }
	},
	methods: {
		onTab(t) {
			this.nav.go({ s: 'security', t })
		},
		// an object of Access (a profile, a person, a key): the request is kept and the Access tab opens
		goAccess(request) {
			const r = typeof request === 'string' ? { tab: request } : request || {}
			askAccess(r)
			this.nav.go({ s: 'access', t: ['profiles', 'people', 'templates', 'can', 'keys'].indexOf(r.tab) >= 0 ? r.tab : 'people' })
		}
	}
}
</script>
