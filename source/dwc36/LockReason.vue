<template>
	<!-- N3, the reason next to a disabled control or group of buttons (ESTANDAR 2.2): a thin wrapper of <session-notice variant="reason"> (the one component).
	     It draws nothing when the person may. ONE reason per group of buttons, below the group; never only a title="". The sign-in call is the chip of the bar.
	       <lock-reason min="technician" />                 the role the page section needs
	       <lock-reason op="light.set" need="operator" />   one operation of the service table
	       <lock-reason kind="down" />                      a cause known by the page (text: the standard one, or :text)
	       <lock-reason min="technician" action="Saving the zones" />   the sentence names what needs the role
	       <lock-reason op="lights.scene" target="workshop:lights:scene/two" />   the answer of the service (auth.can) names the profile, the rule or the ceiling
	       <lock-reason :ops="['machine.config.apply', 'machine.config.plan']" />   ONE sentence for a group of buttons: the first operation that is denied
	       <lock-reason min="technician" note subject="Bed mesh" />   the note at the top of a module: the notice of the cause of `min` (with :ops the sentence of the group, as without `note`)
	       <lock-reason :lock="lock" />                      the answer of a service page store ({ state: 'role', text }): drawn for a role cause only; the session cause is said once by the
	                                                        cover of the place and by the chip of the bar (this is what the service's own SvReason did; it is now this piece)
	     A stop operation never carries a sentence. The sentence is drawn only when the control is disabled by permissions (access-reason.js, section 3.3). -->
	<!-- `note`: the section-top note of a module (what RoleNote of Machine did): with `ops` the sentence follows the service's answer for the group, else it is the plain notice of the
	     cause of `min` ("Requires the Technician role. Your role: Operator." / "Requires signing in."), drawn only while the person lacks the role -->
	<session-notice v-if="drawn" :variant="noteKind ? 'section' : 'reason'" :min="min" :op="op" :need="need" :ctx="ctx" :kind="noteKind || lockKind" :needed="noteKind ? min : ''" :text="shownText" :action="action" :target="target" :ops="ops" :live="live" :subject="subject" />
</template>

<script>
'use strict'

import SessionNotice from './SessionNotice.vue'
import { roleMixin } from './role-mixin.js'
import { lockKind } from './lock-reason.js'

export default {
	components: { SessionNotice },
	mixins: [roleMixin],
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
		live: { type: Object, default: null },
		subject: { type: String, default: '' },
		note: { type: Boolean, default: false }, // module-top note: min alone draws the plain notice of its cause (see above)
		lock: { type: Object, default: null } // { state, text } of the service page store; wins over kind / text
	},
	computed: {
		noteKind() {
			void this.identityTick
			return this.note && this.min && !this.ops.length && !this.lock ? lockKind(this.min) : ''
		},
		// a store answer draws only a role cause (a session cause is the cover's and the chip's)
		drawn() {
			if (this.noteKind) return true
			return !this.lock || this.lock.state === 'role'
		},
		lockKind() {
			return this.lock ? 'role' : this.kind
		},
		shownText() {
			return this.lock ? this.lock.text || '' : this.text
		}
	}
}
</script>
