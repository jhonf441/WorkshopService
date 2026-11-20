<template>
	<!-- Section "Access" of the service page (administrator only): People, Profiles, Templates, Who can do what, Keys. The tab shown is the one the page
	     names (`tab`: the tabs of the shell and the links choose it); a tab a button of this section moves to is told back (event `tab`).
	     `go` { tab, name?, id?, n }: show that tab and, when it names one, the profile / person or group / key (Security asks); the tabs ask the same through their
	     own `go` / `see-can` events. Emits `damaged` (the access file is damaged, read from the lists the tabs already ask). Users turned off are said by the band of the page and by the card of People (with its action). -->
	<div class="access-section">
		<!-- ONE reason for the buttons of the tab that change something (nothing is drawn for a person who may) -->
		<access-lock-reason :ops="tabOps" class="mb-3" @see-profiles="select('profiles')" />
		<access-people-tab v-if="current === 'people'" :focus="focusFor('people')" @damaged="v => $emit('damaged', v)" @see-can="n => goInside({ tab: 'can', name: n })" />
		<access-profiles-tab v-else-if="current === 'profiles'" :focus="focusFor('profiles')" @damaged="v => $emit('damaged', v)" />
		<access-templates v-else-if="current === 'templates'" @go="goInside" />
		<access-can v-else-if="current === 'can'" :focus="focusFor('can')" @go="goInside" />
		<access-keys-tab v-else :focus="focusFor('keys')" :operations="operations" />
		<access-change-dialog v-model="dialog" />
	</div>
</template>

<script>
'use strict'

import AccessState from './AccessState.vue'
import AccessChangeDialog from './AccessChangeDialog.vue'
import AccessPeopleTab from './AccessPeopleTab.vue'
import AccessProfilesTab from './AccessProfilesTab.vue'
import AccessTemplates from './AccessTemplates.vue'
import AccessCan from './AccessCan.vue'
import AccessKeysTab from './AccessKeysTab.vue'
import { accessCanMixin } from './reason-mixin.js'
import AccessLockReason from './AccessLockReason.vue'
import { focusOf } from './access-go.js'

const TABS = ['people', 'profiles', 'templates', 'can', 'keys']
const TAB_OPS = {
	profiles: ['access.profiles.set', 'access.profiles.remove', 'access.profile.rollback'],
	templates: ['access.profiles.set', 'access.attach'],
	people: ['access.attach', 'access.detach', 'access.ceiling.set', 'access.groups.set', 'access.groups.remove']
}

export default {
	components: { AccessLockReason, AccessState, AccessChangeDialog, AccessPeopleTab, AccessProfilesTab, AccessTemplates, AccessCan, AccessKeysTab },
	mixins: [accessCanMixin],
	props: {
		go: { type: Object, default: () => ({ tab: '', n: 0 }) }, // { tab, name?, id?, n }: show that tab (and the object) when n changes (asked from Security)
		tab: { type: String, default: '' }, // the tab the page shows ('' = the first)
		operations: { type: Array, default: () => [] } // the API description, for the operation pickers of the key dialog
	},
	data() {
		return { tabs: TABS, own: TABS.indexOf(this.tab) >= 0 ? this.tab : TABS[0], dialog: false, wanted: null }
	},
	watch: {
		'go.n'() {
			this.applyGo()
		},
		tab(t) {
			if (TABS.indexOf(t) >= 0) this.own = t
		},
		// a tab opened by hand carries no request: the object asked for is shown once, on the tab it was asked for
		own() {
			if (this.wanted && this.wanted.tab !== this.own) this.wanted = null
		}
	},
	// the section is made the first time somebody asks for it: the request that made it is already in `go`
	created() {
		if (this.go && this.go.n) this.applyGo()
	},
	methods: {
		applyGo() {
			this.goInside(this.go)
		},
		// show a tab and, when the request names one, the object on it: from Security (go) and from the tabs themselves ({ tab, name })
		goInside(request) {
			const r = request || {}
			if (this.tabs.indexOf(r.tab) < 0) return
			this.wanted = Object.assign({}, r, { n: (r.n | 0) || ((this.wanted && this.wanted.n | 0) + 1) })
			this.select(r.tab)
		},
		select(t) {
			if (this.tabs.indexOf(t) < 0) return
			this.own = t
			this.$emit('tab', t)
		},
		focusFor(tab) {
			return focusOf(this.wanted, tab)
		}
	},
	computed: {
		// the operations that change something in the tab on screen (access-reason.js groupFromAnswers: one sentence per group of buttons)
		current() {
			return this.own
		},
		tabOps() {
			return TAB_OPS[this.own] || []
		},
	}
}
</script>

<style>
.access-touch { min-height: 40px; }
.access-people [data-flash] { outline: 3px solid var(--v-primary-base, currentColor); outline-offset: 2px; border-radius: 4px; }
</style>
