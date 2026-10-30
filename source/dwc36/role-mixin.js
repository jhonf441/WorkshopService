'use strict'

// Vue mixin: lets a page ask what the current role may see and keeps it up to date when the person logs in, out or the role
// changes (onIdentity of workshop-auth.js). Use it inside computed properties and templates:
//
//   mixins: [roleMixin]      ...      this.atLeast('technician')      this.canDo('light.set')
//
// The ticket `identityTick` is what makes the computed properties run again; the answer itself is workshopCan / roleAtLeast.

import { onIdentity, workshopCan } from './workshop-auth.js'
import { roleAtLeast } from './role-view.js'

export const roleMixin = {
	data() {
		return { identityTick: 0 }
	},
	created() {
		this.offIdentity = onIdentity(() => {
			this.identityTick++
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
		}
	}
}
