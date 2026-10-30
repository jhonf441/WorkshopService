'use strict'

// Composable: lets a page ask what the current role may see and keeps it up to date when the person logs in, out or the role
// changes (onIdentity of workshop-auth.js). Call it once in setup / <script setup>, use the functions in computed() and templates:
//
//   const { atLeast, canDo } = useRole()      ...      atLeast('technician')      canDo('light.set')
//
// The ticket is what makes the computed properties run again; the answer itself is workshopCan / roleAtLeast.
// (3.6: the roleMixin mixin of role-mixin.js, with this.atLeast / this.canDo.)

import { ref, onBeforeUnmount } from 'vue'
import { onIdentity, workshopCan } from './workshop-auth.js'
import { roleAtLeast } from './role-view.js'

export function useRole() {
	const identityTick = ref(0)
	const off = onIdentity(() => {
		identityTick.value++
	})
	onBeforeUnmount(() => {
		if (off) off()
	})
	return {
		// ticket for pages that read other identity data in a computed (currentIdentity, signedOut...)
		identityTick,
		atLeast(min) {
			void identityTick.value
			return roleAtLeast(min)
		},
		canDo(op, ctx) {
			void identityTick.value
			return workshopCan(op, ctx)
		}
	}
}
