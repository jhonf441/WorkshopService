'use strict'

// Vue mixin: lets a page ask what the current role may see and keeps it up to date when the person logs in, out or the role
// changes (onIdentity of workshop-auth.js). Use it inside computed properties and templates:
//
//   mixins: [roleMixin]      ...      this.atLeast('technician')      this.canDo('light.set')
//
// The ticket `identityTick` is what makes the computed properties run again; the answer itself is workshopCan / roleAtLeast.

import { onIdentity, workshopCan, workshopRole, signedOut, currentIdentity } from './workshop-auth.js'
import { roleAtLeast } from './role-view.js'
import { lockReason, lockReasonOp } from './lock-reason.js'
import { sessionKey, sessionChangeKind, resetSessionData } from './session-reset.js'

// A page that defines onSessionChange(kind) is told when the identity changes (not on every whoami); kind is 'signed-in' | 'signed-out' |
// 'role-changed' | 'known' (the first time the identity is known). The component option `sessionData: ['users', ...]` names the data that
// depends on who is signed in: it is put back to its initial value on 'signed-out' and 'role-changed', BEFORE onSessionChange runs.
export const roleMixin = {
	data() {
		return { identityTick: 0 }
	},
	created() {
		let last = currentIdentity() ? sessionKey(workshopRole(), signedOut()) : null
		this.offIdentity = onIdentity(() => {
			this.identityTick++
			const key = sessionKey(workshopRole(), signedOut())
			const kind = sessionChangeKind(last, key, !!currentIdentity())
			if (currentIdentity()) last = key
			if (!kind) return
			if (kind === 'signed-out' || kind === 'role-changed') resetSessionData(this, this.$options.sessionData)
			if (typeof this.onSessionChange === 'function') this.onSessionChange(kind)
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
