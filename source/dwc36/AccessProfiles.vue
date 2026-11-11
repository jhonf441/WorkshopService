<template>
	<!-- Access > Profiles, read only (step 1 of DISENO-PANTALLAS): the list, one profile (builder, JSON, versions), the states of section 5 and the fixed note about
	     G-code. Operations: access.profiles.list / get and access.profile.versions through access-api.js; the capabilities come from roles.list. -->
	<div class="access-profiles">
		<v-card class="mb-3">
			<v-card-title class="text-subtitle-1">
				{{ $t('plugins.WorkshopService.access.profiles_title') }}
				<v-spacer />
				<v-btn small outlined class="access-touch" :loading="loading" @click="load()"><v-icon left small>mdi-refresh</v-icon>{{ $t('plugins.WorkshopService.access.common_refresh') }}</v-btn>
			</v-card-title>
			<v-card-text>
				<div class="wf-note mb-2" role="note"><v-icon class="wf-note-icon" aria-hidden="true">mdi-information-outline</v-icon><span>{{ $t('plugins.WorkshopService.access.profiles_gcode_note') }}</span></div>
				<access-state :state="state" :detail="detail" @retry="load()">
					<template v-if="list">
						<access-profile-view v-if="selected" :key="selected.name" :name="selected.name" :base="selected.base" :capabilities="capabilities" :categories="categories" :max-rules="limits.rules" :max-versions="limits.versions" @back="selected = null" />
						<access-profile-list v-else :list="list" @open="selected = $event" />
					</template>
				</access-state>
			</v-card-text>
		</v-card>
	</div>
</template>

<script>
'use strict'

import AccessState from './AccessState.vue'
import AccessProfileList from './AccessProfileList.vue'
import AccessProfileView from './AccessProfileView.vue'
import { roleMixin } from './role-mixin.js'
import { accessApi } from './access-api.js'
import { stateOfError } from './access-profile-view.js'

const SLOW_MS = 15000

export default {
	components: { AccessState, AccessProfileList, AccessProfileView },
	mixins: [roleMixin],
	data() {
		return { list: null, capabilities: [], categories: [], loading: false, failed: '', failure: null, slow: false, selected: null }
	},
	computed: {
		limits() {
			return Object.assign({ rules: 50, versions: 5 }, (this.list && this.list.limits) || {})
		},
		empty() {
			return !!this.list && !(this.list.profiles || []).length && !(this.list.base || []).length
		},
		// one state at a time, the first that applies (section 5): the cover and the failures before the notes
		state() {
			if (this.failed) return this.failed
			if (this.loading && !this.list) return this.slow ? 'slow' : 'loading'
			if (this.list && this.list.damaged) return 'damaged'
			if (this.empty) return 'empty'
			if (this.list && !this.canDo('access.profiles.set')) return 'read_only'
			return ''
		},
		detail() {
			return this.failure ? this.failure.message || '' : ''
		}
	},
	created() {
		this.load()
	},
	beforeDestroy() {
		clearTimeout(this.timer)
	},
	methods: {
		async load() {
			this.loading = true
			this.slow = false
			this.failed = ''
			this.failure = null
			clearTimeout(this.timer)
			this.timer = setTimeout(() => { this.slow = true }, SLOW_MS)
			try {
				this.list = await accessApi.profilesList()
				// the capabilities (category, class, risk, lock) are the service's: a failure here leaves the rules readable without the table
				const caps = await accessApi.capabilities().catch(() => null)
				this.capabilities = (caps && caps.capabilities) || []
				this.categories = (caps && caps.categories) || []
			} catch (e) {
				this.list = null
				this.failure = e
				this.failed = stateOfError(e)
			} finally {
				this.loading = false
				clearTimeout(this.timer)
			}
		}
	}
}
</script>
