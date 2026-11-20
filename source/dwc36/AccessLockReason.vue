<template>
	<!-- The reason of a locked group of buttons (LockReason, the shared component, untouched) plus, ONLY for an administrator whose profiles are what block the
	     operation, the link "View profiles" (block_see_profiles) that asks the page to open Access > Profiles. Used on the service page only: the plugin pages
	     have no such screen. It decides nothing about access: the cause is the one the service answered (access-reason.js), the same LockReason draws.
	       <access-lock-reason :ops="['access.attach']" @see-profiles="show('profiles')" />   (the same props as lock-reason) -->
	<div class="access-lock-reason">
		<lock-reason v-bind="$props" />
		<button v-if="link" type="button" class="wf-btn access-touch access-see-profiles" @click="$emit('see-profiles')">{{ $t('plugins.WorkshopService.access.block_see_profiles') }}</button>
	</div>
</template>

<script>
'use strict'

import LockReason from './LockReason.vue'
import { accessCanMixin, canStore } from './reason-mixin.js'
import { groupFromAnswers } from './access-reason.js'

// the causes that come from the profiles of the person: only then is the list of profiles where to look
const PROFILE_CAUSES = ['profile', 'ceiling', 'no_rule']

export default {
	components: { LockReason },
	mixins: [accessCanMixin],
	props: {
		min: { type: String, default: '' },
		op: { type: String, default: '' },
		need: { type: String, default: '' },
		ctx: { type: Object, default: null },
		kind: { type: String, default: '' },
		text: { type: String, default: '' },
		action: { type: String, default: '' },
		target: { type: String, default: '' },
		ops: { type: Array, default: () => [] },
		live: { type: Object, default: null }
	},
	computed: {
		// the operations the reason is about: `ops`, or the one `op` (as LockReason asks the service)
		items() {
			if (this.kind) return []
			if (this.ops.length) return this.ops.map(o => (typeof o === 'string' ? { operation: o } : o))
			return this.op ? [this.target ? { operation: this.op, target: this.target } : { operation: this.op }] : []
		},
		link() {
			void this.identityTick
			void this.canTick
			if (!this.atLeast('admin') || !this.items.length) return false
			const targets = {}
			this.items.forEach(i => { targets[i.operation] = i.target })
			const store = canStore()
			if (!store || typeof store.get !== 'function') return false
			const v = groupFromAnswers(this.items.map(i => i.operation), op => store.get(op, targets[op]), { roleName: '' })
			return !!v.show && PROFILE_CAUSES.indexOf(v.cause) >= 0
		}
	}
}
</script>
