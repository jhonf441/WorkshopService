'use strict'

// Wires the answers of auth.can (access-can.js) to the page: ONE store for the whole page (the controls of every section ask the same cache), refreshed
// when the person signs in, out or changes role, and when a call is refused with 403 (workshop-api.js tells it with the window event below).
//
//   mixins: [accessCanMixin]      (it includes roleMixin)
//   this.canDo(op, ctx)           the answer of the service for the operation when it is known (the table of the role until then, and always when
//                                 ctx carries arguments: they can escalate a call and the answers are asked without them)
//   this.wantCan(['a.b', { operation: 'c.d', target: 'workshop:x:y/1' }])      asks for them in one call
//   this.canAnswer(op, target)    the cached answer or null
//
// Stop operations are always allowed by the service and by this mixin: nothing here can lock one.

import { api, currentIdentity, onIdentity } from './workshop-api.js'
import { roleMixin } from './role-mixin.js'
import { makeCanStore } from './access-can.js'
import { STOP_OPS } from './access-reason.js'
import { accessApi } from './access-api.js'

export const FORBIDDEN_EVENT = 'workshop:forbidden' // dispatched on window by workshop-api.js for every 403

let store = null

function identityKey() {
	const id = currentIdentity()
	if (!id) return null
	return String(id.role || '') + '|' + (id.role ? 'in' : 'out') + '|' + String((id.user && id.user.name) || '')
}

export function canStore() {
	if (store) return store
	store = makeCanStore({ call: items => accessApi.can(items, { quiet: true, noLogin: true }) })
	const baseline = identityKey()
	if (baseline !== null) store.noteIdentity(baseline)
	onIdentity(() => {
		const key = identityKey()
		if (key !== null) store.noteIdentity(key)
	})
	if (typeof window !== 'undefined' && typeof window.addEventListener === 'function') window.addEventListener(FORBIDDEN_EVENT, () => store.noteForbidden())
	return store
}

export const accessCanMixin = {
	mixins: [roleMixin],
	data() {
		return { canTick: 0 }
	},
	created() {
		this.offCan = canStore().onChange(() => { this.canTick++ })
	},
	beforeDestroy() {
		if (this.offCan) this.offCan()
	},
	methods: {
		wantCan(items) {
			return canStore().want(items)
		},
		canAnswer(op, target) {
			void this.canTick
			return canStore().get(op, target)
		},
		canDo(op, ctx) {
			void this.identityTick
			void this.canTick
			if (STOP_OPS.indexOf(op) >= 0) return true
			if (ctx && ctx.args) return roleMixin.methods.canDo.call(this, op, ctx)
			const s = canStore()
			s.want([op])
			const a = s.get(op)
			return a ? a.allowed : roleMixin.methods.canDo.call(this, op, ctx)
		}
	}
}
