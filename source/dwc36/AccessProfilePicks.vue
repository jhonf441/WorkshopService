<template>
	<!-- The profiles and the ceiling of a person or of a group, with what is offered to attach and to use as a ceiling. It changes nothing by itself: a tap asks the
	     card to open the dialog (event `ask` with the change). base.administrator is never offered; a plugin profile may be attached but is never a ceiling; a ceiling
	     must have an allow rule (the service refuses it otherwise: its document is read to offer only those). Operations read: access.profiles.list / get.
	       <access-profile-picks :subject="{ user: 'Maria' }" object="Maria" :attached="[...]" :ceiling="null" :locked="false" @ask="change = $event" /> -->
	<div class="access-picks">
		<div class="access-edit-block">
			<div class="access-rule-label">{{ $t('plugins.WorkshopService.access.people_profiles') }}</div>
			<div v-for="p in attached" :key="'a:' + p" class="access-edit-row">
				<profile-name :id="p" />
				<v-btn small outlined class="access-touch" :disabled="locked" @click="ask('detach', p)">{{ $t('plugins.WorkshopService.access.change_do_detach') }}</v-btn>
			</div>
			<div v-if="!attached.length" class="wf-help">{{ $t('plugins.WorkshopService.access.common_none') }}</div>
			<div class="access-edit-pick">
				<sv-select v-model="pick" :items="attachItems" clearable class="access-pick-field" :disabled="locked || !attachItems.length" :label="$t('plugins.WorkshopService.access.people_add_profile')" />
				<v-btn small color="primary" class="access-touch" :disabled="locked || !pick" @click="ask('attach', pick)">{{ $t('plugins.WorkshopService.access.change_do_attach') }}</v-btn>
			</div>
			<div v-if="loaded && !attachItems.length" class="wf-help">{{ $t('plugins.WorkshopService.access.pedit_no_profiles') }}</div>
			<div v-if="failed" class="wf-help">{{ $t('plugins.WorkshopService.access.pedit_profiles_failed') }}</div>
		</div>
		<div class="access-edit-block">
			<div class="access-rule-label">{{ $t('plugins.WorkshopService.access.people_ceiling') }}</div>
			<div v-if="ceiling" class="access-edit-row">
				<profile-name :id="ceiling" />
				<v-btn small outlined class="access-touch" :disabled="locked" @click="ask('ceiling', '')">{{ $t('plugins.WorkshopService.access.change_do_ceiling_clear') }}</v-btn>
			</div>
			<div v-else class="wf-help">{{ $t('plugins.WorkshopService.access.people_ceiling_none') }}</div>
			<div class="access-edit-pick">
				<sv-select v-model="ceilingPick" :items="ceilingItems" clearable class="access-pick-field" :disabled="locked" :label="$t('plugins.WorkshopService.access.pedit_ceiling_pick')" @focusin.native="loadDocs()" />
				<v-btn small color="primary" class="access-touch" :disabled="locked || !ceilingPick" @click="ask('ceiling', ceilingPick)">{{ $t('plugins.WorkshopService.access.change_do_ceiling') }}</v-btn>
			</div>
			<div class="wf-help">{{ $t('plugins.WorkshopService.access.people_ceiling_needs_allow') }} {{ $t('plugins.WorkshopService.access.pedit_ceiling_no_plugin') }}</div>
			<div v-if="docsLoaded && !ceilingItems.length" class="wf-help">{{ $t('plugins.WorkshopService.access.pedit_no_ceilings') }}</div>
		</div>
	</div>
</template>

<script>
'use strict'

import SvSelect from './ui/SvSelect.vue'
import { accessApi } from './access-api.js'
import ProfileName from './ProfileName.vue'
import { displayNamesMixin } from './display-names-mixin.js'
import { attachCandidates, ceilingCandidates, ceilingPool } from './access-edit-view.js'

export default {
	components: { SvSelect, ProfileName },
	mixins: [displayNamesMixin],
	props: {
		subject: { type: Object, required: true }, // { user } or { group }
		object: { type: String, required: true }, // the name the card shows
		attached: { type: Array, default: () => [] },
		ceiling: { type: String, default: null },
		locked: { type: Boolean, default: false }
	},
	data() {
		return { answer: null, loaded: false, failed: false, docs: {}, docsLoaded: false, docsLoading: false, pick: null, ceilingPick: null }
	},
	computed: {
		attachItems() {
			return attachCandidates(this.answer, this.attached).map(c => ({ text: this.profileText(c.name) + ' (' + this.kindText(c.kind) + ')', value: c.name }))
		},
		ceilingItems() {
			return ceilingCandidates(ceilingPool(this.answer, this.ceiling), this.docs).map(c => ({ text: this.profileText(c.name) + ' (' + this.kindText(c.kind) + ')', value: c.name }))
		}
	},
	created() {
		this.loadList()
	},
	methods: {
		kindText(kind) {
			if (kind === 'base') return this.$t('plugins.WorkshopService.access.profiles_type_base')
			if (kind === 'plugin') return this.$t('plugins.WorkshopService.access.pedit_kind_plugin')
			return this.$t('plugins.WorkshopService.access.profiles_type_own')
		},
		async loadList() {
			try {
				this.answer = await accessApi.profilesList()
			} catch (e) {
				this.failed = true
			} finally {
				this.loaded = true
			}
		},
		// the documents of the profiles that could be a ceiling, read once when the selector is used
		async loadDocs() {
			if (this.docsLoaded || this.docsLoading || !this.answer) return
			this.docsLoading = true
			const pool = ceilingPool(this.answer, this.ceiling)
			const got = await Promise.all(pool.map(c => accessApi.profilesGet(c.name).catch(() => null)))
			const docs = {}
			pool.forEach((c, i) => { if (got[i]) docs[c.name] = got[i].document })
			this.docs = docs
			this.docsLoaded = true
			this.docsLoading = false
		},
		ask(kind, profile) {
			this.$emit('ask', { kind, object: this.object, subject: this.subject, profile })
			this.pick = null
			this.ceilingPick = null
		}
	}
}
</script>

<style>
.access-edit-block { margin-bottom: 12px; }
.access-edit-row { display: flex; align-items: center; justify-content: space-between; gap: 8px; min-height: 44px; }
.access-edit-pick { display: flex; align-items: center; gap: 8px; margin-top: 6px; }
.access-pick-field { max-width: 360px; }
</style>
