<template>
	<!-- "Give to a person": the existing attach flow, started from a template. The service attaches a SAVED profile by name, and a template is only an example: the person
	     picks who and which saved profile (the copy of the template when it exists). "See the change" runs the dry run access.attach.validate (access-ask-mixin.js) and, when
	     the service would accept it, opens AccessEditDialog, whose confirm is the only thing that writes (access.attach). Nothing is saved before that.
	       <access-template-give :template="t" :profiles="['Copia_de_Solo_ver']" :copy-name="'Copia_de_Solo_ver'" @close="..." @copy="..." @done="..." /> -->
	<v-card class="access-template-give mb-3" outlined>
		<v-card-title class="text-subtitle-1">{{ $t('plugins.WorkshopService.access.templates_give_title', { name: $t('plugins.WorkshopService.access.templates_' + template.id + '_name') }) }}</v-card-title>
		<v-card-text>
			<div class="wf-help mb-2">{{ $t('plugins.WorkshopService.access.templates_give_help') }}</div>
			<div v-if="!profiles.length" class="wf-note mb-2" role="note"><v-icon class="wf-note-icon" aria-hidden="true">mdi-information-outline</v-icon><span>{{ $t('plugins.WorkshopService.access.templates_give_none') }}</span></div>
			<div v-if="self" class="wf-note mb-2" role="note"><v-icon class="wf-note-icon" aria-hidden="true">mdi-lock-outline</v-icon><span>{{ $t('plugins.WorkshopService.access.people_self_locked') }}</span></div>
			<v-alert v-if="refused" type="warning" outlined dense class="mb-2" role="alert">{{ $t('plugins.WorkshopService.access.pedit_precheck_refused') }} {{ refused }}</v-alert>
			<v-alert v-if="failed" type="error" outlined dense class="mb-2" role="alert">{{ failed }}</v-alert>
			<div v-if="saved" class="wf-help mb-2" role="status">{{ $t('plugins.WorkshopService.access.pedit_saved') }}</div>
			<div class="access-edit-pick">
				<sv-select v-model="user" :items="people" clearable class="access-pick-field" :disabled="locked" :label="$t('plugins.WorkshopService.access.templates_give_person')" />
				<sv-select v-model="profile" :items="profiles" class="access-pick-field" :disabled="locked || !profiles.length" :label="$t('plugins.WorkshopService.access.templates_give_profile')" />
			</div>
			<div v-if="loaded && !people.length" class="wf-help mt-1">{{ $t('plugins.WorkshopService.access.who_none') }}</div>
		</v-card-text>
		<v-card-actions class="access-template-actions sv-card-actions">
			<v-btn small outlined class="access-touch" @click="$emit('close')">{{ $t('plugins.WorkshopService.access.common_cancel') }}</v-btn>
			<v-btn v-if="!profiles.length" small outlined class="access-touch" :disabled="locked" @click="$emit('copy', template)"><v-icon left small>mdi-content-copy</v-icon>{{ $t('plugins.WorkshopService.access.templates_copy') }}</v-btn>
			<v-btn small color="primary" class="access-touch" :loading="checking" :disabled="locked || self || !user || !profile" @click="preview()">{{ $t('plugins.WorkshopService.access.templates_give_preview') }}</v-btn>
		</v-card-actions>
		<access-edit-dialog :change="change" :before="brief" view="person" :groups="groups" @cancel="change = null" @done="done()" @stale="gone()" />
	</v-card>
</template>

<script>
'use strict'

import SvSelect from './ui/SvSelect.vue'
import AccessEditDialog from './AccessEditDialog.vue'
import { askMixin } from './access-ask-mixin.js'
import { roleMixin } from './role-mixin.js'
import { accessApi } from './access-api.js'
import { briefOfPerson, isSelf, refusalOf } from './access-edit-view.js'
import { giveChange } from './access-template-view.js'
import { currentIdentity } from './workshop-api.js'

export default {
	name: 'AccessTemplateGive',
	components: { SvSelect, AccessEditDialog },
	mixins: [roleMixin, askMixin],
	props: {
		template: { type: Object, required: true },
		profiles: { type: Array, default: () => [] }, // the names of the own saved profiles
		copyName: { type: String, default: '' }, // the name the copy of this template gets: chosen first when it exists
		locked: { type: Boolean, default: false } // the session may not attach, or the access file is damaged
	},
	data() {
		return { people: [], groups: null, loaded: false, user: null, profile: this.profiles.indexOf(this.copyName) >= 0 ? this.copyName : (this.profiles[0] || null), change: null, brief: null, failed: '', saved: false }
	},
	computed: {
		self() {
			void this.identityTick
			return !!this.user && isSelf(this.user, currentIdentity())
		}
	},
	async created() {
		try {
			const r = await accessApi.people()
			this.people = ((r && r.users) || []).map(u => String(u.name))
		} catch (e) {
			this.people = []
		}
		this.loaded = true
	},
	methods: {
		// the dry run first (askMixin.passes), then the dialog: the person is read again so the dialog shows the state the service has now
		async preview() {
			if (this.locked || this.self || !this.user || !this.profile || this.checking) return
			this.failed = ''
			this.saved = false
			const c = giveChange(this.user, this.profile)
			try {
				if (!(await this.passes(c))) return
				this.brief = briefOfPerson(await accessApi.personGet(this.user))
				this.groups = await accessApi.groupsList().catch(() => null)
				this.change = c
			} catch (e) {
				this.failed = refusalOf(e).text || this.$t('plugins.WorkshopService.access.pedit_failed')
			}
		},
		done() {
			this.change = null
			this.saved = true
			this.$emit('done')
		},
		gone() {
			this.change = null
			this.failed = this.$t('plugins.WorkshopService.access.state_stale')
		}
	}
}
</script>
