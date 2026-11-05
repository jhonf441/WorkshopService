'use strict'

// Vue mixin: lets a page ask what the current role may see and keeps it up to date when the person logs in, out or the role
// changes (onIdentity of workshop-auth.js). Use it inside computed properties and templates:
//
//   mixins: [roleMixin]      ...      this.atLeast('technician')      this.canDo('light.set')
//
// The ticket `identityTick` is what makes the computed properties run again; the answer itself is workshopCan / roleAtLeast.

import { onIdentity, workshopCan, workshopRole, signedOut } from './workshop-auth.js'
import { roleAtLeast } from './role-view.js'
import { lockReason, lockReasonOp } from './lock-reason.js'

export const roleMixin = {
	data() {
		return { identityTick: 0 }
	},
	created() {
		// a page that defines onSessionChange() is told when the person signs in or out or the role changes (not on every
		// whoami): it reads its data again, so it does not stay empty with the error of the time it was signed out
		let last = null
		this.offIdentity = onIdentity(() => {
			this.identityTick++
			const key = workshopRole() + '|' + (signedOut() ? 'out' : 'in')
			if (last !== null && last !== key && typeof this.onSessionChange === 'function') this.onSessionChange()
			last = key
		})
	},
	beforeDestroy() {
		if (this.offIdentity) this.offIdentity()
	},
	methods: {
		atLeast(min) {
			void this.identityTick
			return roleAtLeast(min)
		},
		canDo(op, ctx) {
			void this.identityTick
			return workshopCan(op, ctx)
		},
		// the sentence that says why a control is locked ('' when it is not): for the title / a note next to it
		lockText(min) {
			void this.identityTick
			return lockReason(min)
		},
		lockTextOp(op, need, ctx) {
			void this.identityTick
			return lockReasonOp(op, need, ctx)
		}
	}
}
