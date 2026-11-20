<template>
	<!-- Change the access of one person: groups, own profiles and ceiling (administrators only). Nobody changes their OWN access: in the own card every control is
	     off and the sentence says why (the service refuses too: self_change). Every change opens AccessEditDialog; the card reloads after the service accepts.
	     Operations (through the dialog): access.attach, access.detach, access.ceiling.set.
	       <access-person-edit :name="'Maria'" :person="answer of access.person.get" :groups="answer of access.groups.list" @changed="reload()" /> -->
	<div class="access-person-edit">
		<div class="access-rule-label access-edit-head">{{ $t('plugins.WorkshopService.access.pedit_title') }}</div>
		<div v-if="self" class="wf-note mb-2" role="note"><v-icon class="wf-note-icon" aria-hidden="true">mdi-lock-outline</v-icon><span>{{ $t('plugins.WorkshopService.access.people_self_locked') }}</span></div>
		<access-state v-if="stale" state="stale" />
		<v-alert v-if="refused" type="warning" outlined dense class="mb-2" role="alert">{{ $t('plugins.WorkshopService.access.pedit_precheck_refused') }} {{ refused }}</v-alert>
		<div v-if="saved" class="wf-help mb-2" role="status">{{ $t('plugins.WorkshopService.access.pedit_saved') }}</div>
		<div class="access-edit-block">
			<div class="access-rule-label">{{ $t('plugins.WorkshopService.access.people_groups') }}</div>
			<div v-for="g in person.groups" :key="'g:' + g" class="access-edit-row">
				<span>{{ g }}</span>
				<v-btn small outlined class="access-touch" :disabled="locked" @click="ask({ kind: 'leave', object: name, subject: { user: name }, group: g, item: g })">{{ $t('plugins.WorkshopService.access.change_do_leave') }}</v-btn>
			</div>
			<div v-if="!person.groups.length" class="wf-help">{{ $t('plugins.WorkshopService.access.common_none') }}</div>
			<div class="access-edit-pick">
				<sv-select v-model="groupPick" :items="groupItems" clearable class="access-pick-field" :disabled="locked || !groupItems.length" :label="$t('plugins.WorkshopService.access.people_add_group')" />
				<v-btn small color="primary" class="access-touch" :disabled="locked || !groupPick" @click="join()">{{ $t('plugins.WorkshopService.access.change_do_join') }}</v-btn>
			</div>
			<div v-if="!groupItems.length" class="wf-help">{{ $t('plugins.WorkshopService.access.pedit_no_groups') }}</div>
		</div>
		<access-profile-picks :subject="{ user: name }" :object="name" :attached="person.profiles" :ceiling="person.ceiling || null" :locked="locked" @ask="ask($event)" />
		<access-edit-dialog :change="change" :before="brief" view="person" :groups="groups" @cancel="change = null" @done="done()" @stale="gone()" />
	</div>
</template>

<script>
'use strict'

import SvSelect from './ui/SvSelect.vue'
import AccessState from './AccessState.vue'
import AccessProfilePicks from './AccessProfilePicks.vue'
import AccessEditDialog from './AccessEditDialog.vue'
import { askMixin } from './access-ask-mixin.js'
import { roleMixin } from './role-mixin.js'
import { currentIdentity } from './workshop-api.js'
import { briefOfPerson, groupChoices, isSelf } from './access-edit-view.js'

export default {
	components: { SvSelect, AccessState, AccessProfilePicks, AccessEditDialog },
	mixins: [roleMixin, askMixin],
	props: {
		name: { type: String, required: true },
		person: { type: Object, required: true }, // access.person.get
		groups: { type: Object, default: null } // access.groups.list
	},
	data() {
		return { change: null, groupPick: null, stale: false, saved: false }
	},
	computed: {
		self() {
			void this.identityTick
			return isSelf(this.name, currentIdentity())
		},
		// no change of their own access, none while the access file is damaged, none for a session that may not (the service decides; this only asks it less)
		locked() {
			return this.self || !!this.person.damaged || !this.canDo('access.attach')
		},
		brief() {
			return briefOfPerson(this.person)
		},
		groupItems() {
			return groupChoices(this.groups, this.person.groups)
		}
	},
	methods: {
		async ask(change) {
			if (this.locked || this.checking) return
			this.stale = false
			this.saved = false
			if (await this.passes(change)) this.change = change
		},
		join() {
			this.ask({ kind: 'join', object: this.name, subject: { user: this.name }, group: this.groupPick, item: this.groupPick })
			this.groupPick = null
		},
		done() {
			this.change = null
			this.saved = true
			this.$emit('changed')
		},
		// somebody else changed it while the dialog was open: nothing was applied; the card reloads and says so
		gone() {
			this.change = null
			this.stale = true
			this.$emit('changed')
		}
	}
}
</script>
