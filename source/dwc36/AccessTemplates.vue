<template>
	<!-- Access > Templates: six ready-made examples (a PROPOSAL the owner adjusts; none is given to anybody by itself), the card of the Administrator (a role, not a profile)
	     and, read only, the profiles of the plugins. "Copy and adjust" opens the profile editor of the Profiles tab on a NEW draft ("Copy of <template>"): saving stays its flow
	     (dry run, one before / after dialog, access.profiles.set). "Give to a person" starts the attach flow (dry run access.attach.validate; the confirm is the only write).
	     The ONE reason for the buttons is drawn by the section. Emits `go` ({ tab }) for the Administrator card.
	     Operations: access.profiles.list, roles.list, users.list (reads); the writes (save a profile, attach it) and their dry runs belong to the existing editor and dialog. -->
	<div class="access-templates">
		<div v-if="draft" ref="draftBox" class="access-template-draft"><access-profile-editor :key="'t:' + draft.n" :name="''" :seed="draft.doc" :seed-text="draft.text" :caps="capsAnswer" :limits="limits" :damaged="damaged" @back="closeDraft()" @saved="reload()" /></div>
		<access-state v-else :state="state" :detail="detail" @retry="load()">
			<v-card class="mb-3">
				<v-card-title class="text-subtitle-1">
					{{ $t('plugins.WorkshopService.access.templates_title') }}
					<v-spacer />
					<v-btn small outlined class="access-touch" :loading="loading" @click="load()"><v-icon left small>mdi-refresh</v-icon>{{ $t('plugins.WorkshopService.access.common_refresh') }}</v-btn>
				</v-card-title>
				<v-card-text>
					<div class="wf-help mb-3">{{ $t('plugins.WorkshopService.access.templates_intro') }}</div>
					<span class="sv-vh" role="status" aria-live="polite" data-part="said">{{ said }}</span>
					<div class="access-template-grid">
						<template v-for="t in templates">
							<access-template-card :key="t.id" :template="t" :titles="titles" :locked-copy="lockedCopy" :locked-give="lockedGive" :far-note="farNote && lastId === t.id ? farNote : ''" @copy="copy" @give="give" />
							<div v-if="giving && giving.id === t.id" :key="'g:' + t.id" ref="giveBox" class="access-template-give-slot">
								<access-template-give :template="giving" :profiles="ownProfiles" :copy-name="copyNameOf(giving)" :locked="lockedGive" @close="giving = null" @copy="x => { giving = null; copy(x) }" @done="reload()" />
							</div>
						</template>
						<v-card class="access-template-admin sv-card-fill" outlined>
							<v-card-title class="text-subtitle-1"><v-icon small class="mr-2" aria-hidden="true">mdi-shield-account-outline</v-icon>{{ $t('plugins.WorkshopService.access.templates_admin_title') }}</v-card-title>
							<v-card-text>
								<div class="mb-1 font-weight-medium">{{ $t('plugins.WorkshopService.access.templates_admin_role') }}</div>
								<div class="wf-help">{{ $t('plugins.WorkshopService.access.templates_admin_text') }}</div>
							</v-card-text>
							<v-card-actions class="sv-card-actions">
								<v-btn small outlined class="access-touch" @click="$emit('go', { tab: 'people' })"><v-icon left small>mdi-account-group-outline</v-icon>{{ $t('plugins.WorkshopService.access.templates_admin_go') }}</v-btn>
							</v-card-actions>
						</v-card>
					</div>
				</v-card-text>
			</v-card>
			<v-card class="mb-3 access-template-plugins" outlined>
				<v-card-title class="text-subtitle-1">{{ $t('plugins.WorkshopService.access.templates_plugins_title') }}</v-card-title>
				<v-card-text>
					<div class="wf-help mb-2">{{ $t('plugins.WorkshopService.access.templates_plugins_help') }}</div>
					<div v-if="!plugins.length" class="wf-help">{{ $t('plugins.WorkshopService.access.templates_plugins_none') }}</div>
					<div v-for="p in plugins" :key="p.name" class="access-edit-row mb-1">
						<div><strong><profile-name :id="p.name" /></strong></div>
						<div class="wf-help">{{ $t('plugins.WorkshopService.access.templates_plugin_' + p.level) }}</div>
					</div>
				</v-card-text>
			</v-card>
		</access-state>
	</div>
</template>

<script>
'use strict'

import AccessState from './AccessState.vue'
import AccessProfileEditor from './AccessProfileEditor.vue'
import AccessTemplateCard from './AccessTemplateCard.vue'
import AccessTemplateGive from './AccessTemplateGive.vue'
import ProfileName from './ProfileName.vue'
import { roleMixin } from './role-mixin.js'
import { revealMixin } from './reveal-mixin.js'
import { accessApi } from './access-api.js'
import { stateOfError } from './access-profile-view.js'
import { TEMPLATES } from './access-templates.js'
import { copyName, ownNames, pluginRows, templateDoc, titlesOf } from './access-template-view.js'

export default {
	name: 'AccessTemplates',
	components: { AccessState, AccessProfileEditor, AccessTemplateCard, AccessTemplateGive, ProfileName },
	mixins: [roleMixin, revealMixin],
	data() {
		return { templates: TEMPLATES, list: null, capsAnswer: {}, loading: false, failed: '', failure: null, draft: null, drafts: 0, giving: null, lastId: '' }
	},
	computed: {
		titles() {
			return titlesOf(this.capsAnswer)
		},
		limits() {
			return Object.assign({ rules: 50, versions: 5 }, (this.list && this.list.limits) || {})
		},
		damaged() {
			return !!this.list && !!this.list.damaged
		},
		ownProfiles() {
			return ownNames(this.list)
		},
		plugins() {
			return pluginRows(this.list)
		},
		// the editor and the attach flow need the lists the service gave (the capabilities, the profiles); the table of the service decides who may
		hasCaps() {
			return ((this.capsAnswer && this.capsAnswer.capabilities) || []).length > 0
		},
		lockedCopy() {
			return !this.canDo('access.profiles.set') || this.damaged || !this.hasCaps
		},
		lockedGive() {
			return !this.canDo('access.attach') || this.damaged
		},
		state() {
			if (this.failed) return this.failed
			if (this.loading && !this.list) return 'loading'
			if (this.damaged) return 'damaged'
			return ''
		},
		detail() {
			return this.failure ? this.failure.message || '' : ''
		}
	},
	created() {
		this.load()
	},
	methods: {
		copyNameOf(t) {
			return copyName(this.$t('plugins.WorkshopService.access.templates_copy_name', { name: this.$t('plugins.WorkshopService.access.templates_' + t.id + '_name') }))
		},
		// a NEW draft in the editor: nothing is asked of the service until the editor validates it, and nothing is written until its own confirm
		copy(t) {
			if (this.lockedCopy) return
			const name = this.$t('plugins.WorkshopService.access.templates_' + t.id + '_name')
			this.drafts++
			this.draft = { n: this.drafts, doc: templateDoc(t, this.copyNameOf(t)), text: this.$t('plugins.WorkshopService.access.templates_copy_note', { name }) }
			this.lastId = t.id
			// the editor opens in the place of the cards: bring it into view, mark it, focus its first field and say it
			this.$nextTick(() => this.showResult(this.$refs.draftBox, { focus: true, said: this.$t('plugins.WorkshopService.access.templates_copy_opened', { name: this.copyNameOf(t) }) }))
		},
		// "Give to a person": the panel opens right under the card (not at the top of the page) and gets the same treatment
		give(t) {
			this.giving = t
			this.lastId = t.id
			const name = this.$t('plugins.WorkshopService.access.templates_' + t.id + '_name')
			this.$nextTick(() => {
				const b = this.$refs.giveBox
				this.showResult(Array.isArray(b) ? b[0] : b, { focus: true, said: this.$t('plugins.WorkshopService.access.templates_give_opened', { name }) })
			})
		},
		closeDraft() {
			this.draft = null
			this.load()
		},
		reload() {
			accessApi.profilesList().then(l => { this.list = l }, () => {})
		},
		async load() {
			this.loading = true
			this.failed = ''
			this.failure = null
			try {
				this.list = await accessApi.profilesList()
				this.capsAnswer = (await accessApi.capabilities().catch(() => null)) || {}
			} catch (e) {
				this.list = null
				this.failure = e
				this.failed = stateOfError(e)
			} finally {
				this.loading = false
			}
		}
	}
}
</script>

<style>
.access-template-give-slot { grid-column: 1 / -1; }
.access-template-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 12px; align-items: stretch; }
</style>
