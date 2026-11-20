<template>
	<!-- One profile, read only: header (name, kind, version, who has it), then Builder | JSON | Versions. A base profile says it is generated and cannot be edited.
	       <access-profile-view :name="..." :base="true" :capabilities="[...]" :categories="[...]" :max-rules="50" @back="..." /> -->
	<div class="access-profile-view">
		<div class="access-view-head">
			<v-btn small outlined class="access-touch" @click="$emit('back')"><v-icon left small>mdi-arrow-left</v-icon>{{ $t('plugins.WorkshopService.access.common_back') }}</v-btn>
			<strong class="access-view-name"><profile-name :id="name" /></strong>
			<v-chip small outlined label>{{ $t('plugins.WorkshopService.access.profiles_type_' + (base ? 'base' : 'own')) }}</v-chip>
			<v-chip v-if="!base && got" small outlined label color="success">{{ $t('plugins.WorkshopService.access.profiles_version_of', { n: got.version, total: got.versions }) }}</v-chip>
			<v-chip v-if="viewing" small outlined label color="info">{{ $t('plugins.WorkshopService.access.versions_viewing', { n: viewing }) }}</v-chip>
		</div>
		<access-state :state="state" :detail="detail" @retry="load()">
			<template v-if="got">
				<div v-if="base" class="wf-note mb-2" role="note"><v-icon class="wf-note-icon" aria-hidden="true">mdi-lock-outline</v-icon><span>{{ $t('plugins.WorkshopService.access.profiles_base_notice') }}</span></div>
				<v-btn v-if="base && editable" small outlined class="access-touch mb-2" @click="$emit('duplicate', got.document)"><v-icon left small>mdi-content-copy</v-icon>{{ $t('plugins.WorkshopService.access.profiles_duplicate') }}</v-btn>
				<div class="access-holders wf-help">
					<span class="access-rule-label">{{ $t('plugins.WorkshopService.access.profiles_col_holders') }}</span>
					<span v-if="!users.length && !groups.length">{{ $t('plugins.WorkshopService.access.profiles_holders_nobody') }}</span>
					<span v-if="users.length">{{ $t('plugins.WorkshopService.access.profiles_holders_users', { names: users.join(', ') }) }}</span>
					<span v-if="groups.length">{{ $t('plugins.WorkshopService.access.profiles_holders_groups', { names: groups.join(', ') }) }}</span>
				</div>
				<div class="access-modes" role="group">
					<button v-for="m in modes" :key="m" type="button" class="access-kind access-touch" :class="{ 'is-on': mode === m }" :aria-pressed="mode === m ? 'true' : 'false'" @click="mode = m">{{ $t('plugins.WorkshopService.access.builder_mode_' + m) }}{{ m === 'versions' && !base ? ' (' + got.versions + ')' : '' }}</button>
				</div>
				<access-capability-builder v-if="mode === 'builder'" :doc="shownDoc" :capabilities="capabilities" :categories="categories" :max="maxRules" />
				<access-json-view v-else-if="mode === 'json'" :doc="shownDoc" />
				<access-version-list v-else :name="name" :base="base" :versions="versions" :max="maxVersions" :viewing="viewing" @view="n => viewing = n === activeN ? 0 : n" />
			</template>
		</access-state>
	</div>
</template>

<script>
'use strict'

import AccessState from './AccessState.vue'
import ProfileName from './ProfileName.vue'
import AccessCapabilityBuilder from './AccessCapabilityBuilder.vue'
import AccessJsonView from './AccessJsonView.vue'
import AccessVersionList from './AccessVersionList.vue'
import { accessApi } from './access-api.js'
import { stateOfError } from './access-profile-view.js'

export default {
	components: { ProfileName, AccessState, AccessCapabilityBuilder, AccessJsonView, AccessVersionList },
	props: {
		name: { type: String, required: true },
		base: { type: Boolean, default: false },
		capabilities: { type: Array, default: () => [] },
		categories: { type: Array, default: () => [] },
		maxRules: { type: Number, default: 50 },
		maxVersions: { type: Number, default: 5 },
		editable: { type: Boolean, default: false } // the session may change profiles: a base profile can be duplicated as an own one
	},
	data() {
		return { got: null, versions: [], state: 'loading', detail: '', viewing: 0, mode: 'builder', modes: ['builder', 'json', 'versions'] }
	},
	computed: {
		users() {
			return (this.got && this.got.attached_to && this.got.attached_to.users) || []
		},
		groups() {
			return (this.got && this.got.attached_to && this.got.attached_to.groups) || []
		},
		activeN() {
			return this.got ? this.got.version : 0
		},
		shownDoc() {
			if (this.viewing) {
				const v = this.versions.find(x => x.n === this.viewing)
				if (v) return v.doc
			}
			return this.got ? this.got.document : null
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
		async load() {
			this.state = 'loading'
			this.detail = ''
			try {
				this.got = await accessApi.profilesGet(this.name)
				this.versions = this.base ? [] : ((await accessApi.profileVersions(this.name)) || {}).versions || []
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

<style>
.access-view-head { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; margin-bottom: 12px; }
.access-view-name { font-size: 16px; }
.access-holders { display: flex; flex-wrap: wrap; gap: 4px 12px; margin-bottom: 8px; }
.access-modes { display: inline-flex; margin: 4px 0 12px; border: 1px solid var(--wf-line); border-radius: 8px; overflow: hidden; }
</style>
