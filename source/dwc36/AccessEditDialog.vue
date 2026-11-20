<template>
	<!-- The confirmation flow of every change of a person or of a group (DISENO-PANTALLAS 2.5 and 7.7): it fills AccessChangeDialog with before / after / outcome,
	     asks the service again for the object (somebody else may have changed it: then it does not apply anything, it says so and the card reloads), and calls the
	     operation with confirm: true because THIS dialog is the confirmation (the service does not ask a second time). A refusal keeps the dialog open.
	       <access-edit-dialog :change="change" :before="brief" view="person" :groups="groups" @cancel="change = null" @done="..." @stale="..." />
	     change: { kind, object, subject, profile?, group?, item?, name?, description? } (access-edit-view.js); null: closed. -->
	<access-change-dialog :value="!!change" :title="title" :confirm-label="verb" :busy="busy" :error="error" @input="onInput" @confirm="confirm()">
		<template #before><access-attachment-diff side="before" :kind="view" :before="before" :after="after" :missing="isCreate" /></template>
		<template #after><access-attachment-diff side="after" :kind="view" :before="before" :after="after" :missing="isRemove" /></template>
		<template #summary>
			<div v-if="text.outcome" class="mb-1">{{ $tc('plugins.WorkshopService.access.' + text.outcome, text.params.n, text.params) }}</div>
			<div v-if="text.note" class="wf-help">{{ $t('plugins.WorkshopService.access.' + text.note, text.params) }}</div>
		</template>
	</access-change-dialog>
</template>

<script>
'use strict'

import AccessChangeDialog from './AccessChangeDialog.vue'
import AccessAttachmentDiff from './AccessAttachmentDiff.vue'
import { accessApi } from './access-api.js'
import { applyChange, briefOfGroup, briefOfPerson, describeChange, governedAfter, refusalOf, sameBrief } from './access-edit-view.js'

const OPTS = { confirm: true } // this dialog is the confirmation of the service (key access.change / access.remove)

export default {
	components: { AccessChangeDialog, AccessAttachmentDiff },
	props: {
		change: { type: Object, default: null },
		before: { type: Object, default: null }, // the Brief the screen shows now (access-edit-view.js)
		view: { type: String, default: 'person' }, // what the card shows: 'person' | 'group'
		groups: { type: Object, default: null } // the answer of access.groups.list (to tell who is governed by profiles)
	},
	data() {
		return { busy: false, error: '' }
	},
	computed: {
		isCreate() {
			return !!this.change && this.change.kind === 'group_save'
		},
		isRemove() {
			return !!this.change && this.change.kind === 'group_remove'
		},
		after() {
			return this.change ? applyChange(this.before, this.change) : null
		},
		text() {
			const c = this.change
			const people = this.view === 'person'
			const info = { members: this.before && !people ? this.before.groups.length : 0, governedBefore: people && !!this.before && governedAfter(this.before, this.groups), governedAfter: people && !!this.after && governedAfter(this.after, this.groups) }
			return describeChange(c, info)
		},
		title() {
			return this.change ? this.$t('plugins.WorkshopService.access.' + this.text.title, this.text.params) : ''
		},
		verb() {
			return this.change ? this.$t('plugins.WorkshopService.access.' + this.text.verb) : ''
		}
	},
	watch: {
		change() {
			this.error = ''
			this.busy = false
		}
	},
	methods: {
		onInput(open) {
			if (!open && !this.busy) this.$emit('cancel')
		},
		// what the service keeps of the object now: a Brief, or null when there is no such object (a group that is not there)
		async fresh() {
			const c = this.change
			try {
				if (this.view === 'person') return briefOfPerson(await accessApi.personGet(c.object))
				return briefOfGroup(((await accessApi.groupsGet(c.object)) || {}).group)
			} catch (e) {
				if (e && e.code === 'unknown_group') return null
				throw e
			}
		},
		async run() {
			const c = this.change
			if (c.kind === 'attach') return accessApi.attach(c.subject, { profile: c.profile }, OPTS)
			if (c.kind === 'detach') return accessApi.detach(c.subject, { profile: c.profile }, OPTS)
			if (c.kind === 'join') return accessApi.attach(c.subject, { memberOf: c.group }, OPTS)
			if (c.kind === 'leave') return accessApi.detach(c.subject, { memberOf: c.group }, OPTS)
			if (c.kind === 'ceiling') return accessApi.ceilingSet(c.subject, c.profile, OPTS)
			if (c.kind === 'group_save') return accessApi.groupsSet({ name: c.name, description: c.description || '', profiles: [] }, OPTS)
			return accessApi.groupsRemove(c.name, OPTS)
		},
		async confirm() {
			if (!this.change || this.busy) return
			this.busy = true
			this.error = ''
			try {
				const now = await this.fresh()
				// a new group must still not exist (saving over one would replace its profiles); anything else must be as the dialog showed it
				const same = this.isCreate ? now === null : now !== null && sameBrief(now, this.before)
				if (!same) {
					this.$emit('stale')
					return
				}
				this.$emit('done', await this.run())
			} catch (e) {
				this.error = refusalOf(e).text || this.$t('plugins.WorkshopService.access.pedit_failed')
			} finally {
				this.busy = false
			}
		}
	}
}
</script>
