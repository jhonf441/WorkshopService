<template>
	<!-- Access: who enters and what they may do (People, Profiles, Templates, Who can do what, Keys) and the settings (the DWC password). The five first
	     tabs are the screens that were already rebuilt with their own tests (dwc36/Access*.vue); they are hosted here with the tab the shell names and
	     the request of Security to show an object ("go"). Props: active (this section is in view), tab. -->
	<div class="sv-access">
		<access-how />
		<p class="sv-quiet sv-purpose" data-part="purpose">{{ t('access_help.purpose_' + tab) }} <button type="button" class="sv-btn sv-text" data-act="how" @click="showTerm('')">{{ t('access_help.how_link') }}</button></p>
		<access-section v-if="tab !== 'settings'" :operations="operations" :tab="tab" :go="go" @tab="onTab" />
		<password-tab v-if="seenPassword" v-show="tab === 'settings'" :active="active && tab === 'settings'" />
	</div>
</template>

<script>
import { apiOps } from '../../core/resources.js'
import { accessGo } from '../../core/store/access-focus.js'
import { setOps } from '../../access-ops-source.js'
import { want } from '../../core/store/session.js'
import { t } from '../../core/dwc.js'
import { showTerm } from '../../core/store/access-how.js'
import AccessSection from '../../AccessSection.vue'
import AccessHow from './AccessHow.vue'
import PasswordTab from './PasswordTab.vue'

export default {
	name: 'AccessHost',
	components: { AccessSection, AccessHow, PasswordTab },
	inject: { nav: { from: 'svNav', default: () => ({ go() {}, href: () => '#' }) } },
	props: { active: { type: Boolean, default: false }, tab: { type: String, default: 'people' } },
	data() {
		return { go: accessGo, seenPassword: false }
	},
	computed: {
		operations() {
			return (apiOps.data && apiOps.data.ops) || []
		}
	},
	watch: {
		active: { immediate: true, handler(on) { if (on) { want(['api.describe']); apiOps.show() } else apiOps.hide() } },
		tab: { immediate: true, handler(t) { if (t === 'settings') this.seenPassword = true } },
		// the editor of rules of Profiles offers the operations of the service with their meaning
		operations: { immediate: true, handler(list) { setOps(list) } }
	},
	methods: {
		t,
		showTerm,
		onTab(tab) {
			this.nav.go({ s: 'access', t: tab })
		}
	}
}
</script>
