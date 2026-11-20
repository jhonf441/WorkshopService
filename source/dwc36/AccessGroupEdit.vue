<template>
	<!-- Change one group (administrators only): its profiles and ceiling, its members, and remove it. A group with people cannot be removed (the button is off and
	     says how many); nobody puts themselves in or takes themselves out of a group (the service refuses: self_change). Every change opens AccessEditDialog.
	     Operations (through the dialog): access.attach, access.detach, access.ceiling.set, access.groups.remove.
	       <access-group-edit :group="group of access.groups.get" :users="[{ name }]" :groups="answer of access.groups.list" @changed="reload()" @removed="back()" /> -->
	<div class="access-group-edit">
		<div class="access-rule-label access-edit-head">{{ $t('plugins.WorkshopService.access.pedit_title') }}</div>
		<access-state v-if="stale" state="stale" />
		<v-alert v-if="refused" type="warning" outlined dense class="mb-2" role="alert">{{ $t('plugins.WorkshopService.access.pedit_precheck_refused') }} {{ refused }}</v-alert>
		<div v-if="saved" class="wf-help mb-2" role="status">{{ $t('plugins.WorkshopService.access.pedit_saved') }}</div>
		<access-profile-picks :subject="{ group: group.name }" :object="group.name" :attached="group.profiles" :ceiling="group.ceiling || null" :locked="locked" @ask="ask($event)" />
		<div class="access-edit-block">
			<div class="access-rule-label">{{ $t('plugins.WorkshopService.access.groups_members') }}</div>
			<div v-for="m in group.members" :key="'m:' + m" class="access-edit-row">
				<span>{{ m }}</span>
				<v-btn small outlined class="access-touch" :disabled="locked || isMe(m)" @click="ask({ kind: 'leave', object: group.name, subject: { user: m }, group: group.name, item: m })">{{ $t('plugins.WorkshopService.access.change_do_leave') }}</v-btn>
			</div>
			<div v-if="!group.members.length" class="wf-help">{{ $t('plugins.WorkshopService.access.groups_members_none') }}</div>
			<div v-if="meIn" class="wf-help">{{ $t('plugins.WorkshopService.access.people_self_locked') }}</div>
			<div class="access-edit-pick">
				<sv-select v-model="memberPick" :items="memberItems" clearable class="access-pick-field" :disabled="locked || !memberItems.length" :label="$t('plugins.WorkshopService.access.pedit_member_pick')" />
				<v-btn small color="primary" class="access-touch" :disabled="locked || !memberPick" @click="join()">{{ $t('plugins.WorkshopService.access.change_do_join') }}</v-btn>
			</div>
			<div v-if="!memberItems.length" class="wf-help">{{ $t('plugins.WorkshopService.access.pedit_no_members') }}</div>
		</div>
		<div class="access-edit-block access-care" data-part="care">
			<v-btn small outlined color="error" class="access-touch" :disabled="locked || group.members.length > 0" @click="ask({ kind: 'group_remove', object: group.name, name: group.name })">{{ $t('plugins.WorkshopService.access.change_do_group_remove') }}</v-btn>
			<span v-if="group.members.length" class="wf-help">{{ $tc('plugins.WorkshopService.access.groups_remove_has_people', group.members.length, { n: group.members.length }) }}</span>
		</div>
		<access-edit-dialog :change="change" :before="brief" view="group" :groups="groups" @cancel="change = null" @done="done()" @stale="gone()" />
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
import { briefOfGroup, isSelf, memberChoices } from './access-edit-view.js'

export default {
	components: { SvSelect, AccessState, AccessProfilePicks, AccessEditDialog },
	mixins: [roleMixin, askMixin],
	props: {
		group: { type: Object, required: true }, // access.groups.get -> group (never a custom role)
		users: { type: Array, default: () => [] }, // users.list: the people that can join
		groups: { type: Object, default: null }, // access.groups.list
		damaged: { type: Boolean, default: false }
	},
	data() {
		return { change: null, memberPick: null, stale: false, saved: false }
	},
	computed: {
		locked() {
			return this.damaged || !this.canDo('access.attach')
		},
		brief() {
			return briefOfGroup(this.group)
		},
		memberItems() {
			void this.identityTick
			return memberChoices(this.users, this.group.members, currentIdentity())
		},
		meIn() {
			return this.group.members.some(m => this.isMe(m))
		}
	},
	methods: {
		isMe(name) {
			void this.identityTick
			return isSelf(name, currentIdentity())
		},
		async ask(change) {
			if (this.locked || this.checking) return
			this.stale = false
			this.saved = false
			if (await this.passes(change)) this.change = change
		},
		join() {
			this.ask({ kind: 'join', object: this.group.name, subject: { user: this.memberPick }, group: this.group.name, item: this.memberPick })
			this.memberPick = null
		},
		done() {
			const removed = this.change && this.change.kind === 'group_remove'
			this.change = null
			this.saved = true
			this.$emit(removed ? 'removed' : 'changed')
		},
		gone() {
			this.change = null
			this.stale = true
			this.$emit('changed')
		}
	}
}
</script>
