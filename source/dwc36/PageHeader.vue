<template>
	<!-- Header of every page (2026-10-23), the bar of the design family (2026-10-28): its look is design/family.css, nothing here is styled.
	     [badge + title, the lead line under it] ... [health state] [key chips of the page: slot] [right slot] [session] [start-up: slot "startup"]
	     - badge: a solid square of the color of the plugin (prop `badge`, else vue/_shared/plugin-colors.js); its icon is always white;
	     - lead: ONE line saying what the page is for (a text, or the key of a text of the catalog); long help goes in a fold of the page;
	     - health: the worst state of what the page watches (prop `reasons`) plus the service problem; green "All fine",
	       orange "Attention", red "Fault"; the list of reasons opens on tap. While the page has no data yet (`loading`) none.
	     - session: "Sign in" when the service has people and this browser has no session (so a page does not say the service
	       "does not respond" when it only needs you to sign in); "Read only" for a visitor.
	     - no action buttons here: what a section needs goes in the section. -->
	<div class="page-header wf-bar" :style="barStyle">
		<span class="wf-badge" aria-hidden="true"><v-icon class="wf-badge-icon">{{ icon }}</v-icon></span>
		<div class="wf-bar-txt">
			<div class="page-title wf-title" role="heading" aria-level="1">{{ title }}</div>
			<div v-if="leadText" class="wf-lead">{{ leadText }}</div>
		</div>
		<div class="wf-bar-right">
				<v-menu v-if="!loading && !signedOutNow" offset-y :close-on-content-click="false" :disabled="level === 'ok'">
					<template v-slot:activator="{ on, attrs }">
						<v-chip small outlined :color="ui.color" class="page-health" v-bind="attrs" v-on="on">
							{{ ts(ui.key) }}<template v-if="all.length">: {{ all.length }}</template>
						</v-chip>
					</template>
					<v-list dense class="page-health-list">
						<v-list-item v-for="(r, i) in all" :key="i">
							<v-list-item-icon class="mr-3"><v-icon small :color="r.level === 'error' ? 'error' : 'warning'">{{ r.level === 'error' ? 'mdi-alert-circle-outline' : 'mdi-alert-outline' }}</v-icon></v-list-item-icon>
							<v-list-item-content><v-list-item-title class="page-health-text">{{ r.text }}</v-list-item-title></v-list-item-content>
						</v-list-item>
					</v-list>
				</v-menu>
				<slot />
				<slot name="right" />
				<v-chip v-if="signedOutNow" small outlined color="info" :title="ts('header_sign_in_help')" @click="signIn">
					<v-icon x-small left>mdi-account-lock-outline</v-icon>{{ ts('header_sign_in') }}
				</v-chip>
				<v-chip v-else-if="viewerNow" small outlined :title="ts('header_read_only_help')">
					<v-icon x-small left>mdi-eye-outline</v-icon>{{ ts('header_read_only') }}
				</v-chip>
				<slot name="startup" />
		</div>
	</div>
</template>

<script>
'use strict'

import { healthLevel, LEVEL_UI } from './page-health.js'
import { serviceProblemKind, SERVICE_PROBLEM_KEYS } from './service-problem.js'
import { roleMixin } from './role-mixin.js'
import { signedOut, workshopRole } from './workshop-auth.js'
import { askLogin, currentIdentity, whoami } from './workshop-api.js'
import { ts } from './shared-t.js'
import i18n from '../../i18n'
import { PLUGIN_ID } from './plugin-id.js'
import { pluginBadge } from './plugin-colors.js'

export default {
	mixins: [roleMixin],
	created() {
		// who is using this browser: without it a missing session looks like a failure (the pages that never ask do not know yet)
		if (!currentIdentity()) whoami().catch(() => {})
	},
	props: {
		icon: { type: String, required: true },
		title: { type: String, required: true },
		// the one line under the title: a text or the key of a text in the catalog of the plugin
		lead: { type: String, default: '' },
		// color of the badge; default = the one of the plugin (plugin-colors.js)
		badge: { type: String, default: '' },
		// [{ level: 'warn' | 'error', text }] the page watches; null / [] = fine
		reasons: { type: Array, default: () => [] },
		// the page has no data yet: no health chip (a green "all fine" before knowing would be a lie)
		loading: { type: Boolean, default: false }
	},
	computed: {
		// signed out: the page's errors come from the missing session, not from a failure
		signedOutNow() {
			void this.identityTick
			const id = currentIdentity()
			// no token, or a token the service no longer accepts (expired / another machine)
			return signedOut() || !!(id && id.configured && id.login_required)
		},
		viewerNow() {
			void this.identityTick
			return workshopRole() === 'viewer'
		},
		serviceReason() {
			const kind = serviceProblemKind(this.$store)
			return kind ? { level: 'error', text: ts(SERVICE_PROBLEM_KEYS[kind].title) } : null
		},
		all() {
			const own = this.signedOutNow ? [] : this.reasons || []
			return (this.serviceReason ? [this.serviceReason] : []).concat(own.filter(Boolean))
		},
		level() {
			return healthLevel(this.all)
		},
		ui() {
			return LEVEL_UI[this.level]
		},
		barStyle() {
			return { '--wf-badge': this.badge || pluginBadge(PLUGIN_ID) }
		},
		leadText() {
			const l = this.lead || ''
			try {
				return l && /^[\w-]+(\.[\w-]+)+$/.test(l) && i18n.te(l) ? i18n.t(l) : l
			} catch (e) {
				return l
			}
		}
	},
	methods: {
		ts,
		signIn() {
			return askLogin()
		}
	}
}
</script>

<style scoped>
.page-health {
	cursor: pointer;
}
.page-health-list {
	max-width: 420px;
}
.page-health-text {
	white-space: normal;
}
</style>
