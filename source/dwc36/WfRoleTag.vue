<template>
	<!-- The role a section, a card or a block asks for, as ONE small chip for the whole family: "Requires the Technician role". It only exists when the access control is ON
	     (the service has users; with it off everybody can do everything and a role label would look like a restriction that is not there) and it is dimmed when the person
	     already has the role. Display only: what is locked says why through <lock-reason>. The look is design/family.css (.wf-role-tag, section FASE3).
	       <wf-role-tag role="technician" /> -->
	<span v-if="on" class="wf-role-tag" :class="{ 'is-have': have }" :title="text">{{ text }}</span>
</template>

<script>
'use strict'

import { ts } from './shared-t.js'
import { roleMixin } from './role-mixin.js'
import { accessOnFor } from './access-on.js'
import { roleLabel } from './notice-kind.js'
import { currentIdentity } from './workshop-auth.js'

export default {
	mixins: [roleMixin],
	props: {
		role: { type: String, default: 'technician' } // 'operator' | 'technician' | 'admin'
	},
	computed: {
		on() {
			void this.identityTick
			return accessOnFor(currentIdentity())
		},
		have() {
			return this.atLeast(this.role)
		},
		text() {
			return ts('role_tag_needs', { role: roleLabel(this.role, ts) })
		}
	}
}
</script>
