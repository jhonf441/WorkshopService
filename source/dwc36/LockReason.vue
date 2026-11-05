<template>
	<!-- N3, the reason next to a disabled control or group of buttons (ESTANDAR 2.2): one line, no box, the color of the cause. It draws nothing when the
	     person may. ONE reason per group of buttons, below the group; never only a title="". The sign-in call is the chip of the bar, not here.
	       <lock-reason min="technician" />                 the role the page section needs
	       <lock-reason op="light.set" need="operator" />   one operation of the service table
	       <lock-reason kind="down" />                      a cause known by the page (text: the standard one, or :text) -->
	<div v-if="k" class="wf-reason" :class="'wf-reason--' + k" role="note">
		<v-icon :size="16" class="wf-reason-icon" aria-hidden="true">{{ icon }}</v-icon>
		<span class="wf-reason-text">{{ message }}</span>
	</div>
</template>

<script>
'use strict'

import { ts } from './shared-t.js'
import { roleMixin } from './role-mixin.js'
import { lockKind, lockKindOp, lockReason, lockReasonOp } from './lock-reason.js'
import { NOTICE_ICONS, noticeText } from './notice-kind.js'
import { workshopRole } from './workshop-auth.js'

export default {
	mixins: [roleMixin],
	props: {
		min: { type: String, default: '' },
		op: { type: String, default: '' },
		need: { type: String, default: '' },
		ctx: { type: Object, default: null },
		kind: { type: String, default: '' },
		text: { type: String, default: '' }
	},
	computed: {
		k() {
			void this.identityTick
			if (this.kind) return this.kind
			if (this.op) return lockKindOp(this.op, this.need, this.ctx || undefined)
			return this.min ? lockKind(this.min) : ''
		},
		icon() {
			return NOTICE_ICONS[this.k] || NOTICE_ICONS.error
		},
		message() {
			void this.identityTick
			if (this.text) return this.text
			if (this.kind) return noticeText(this.kind, { needed: this.need || this.min || 'technician', role: workshopRole() }, ts)
			return this.op ? lockReasonOp(this.op, this.need, this.ctx || undefined) : lockReason(this.min)
		}
	}
}
</script>
