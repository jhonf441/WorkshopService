<template>
	<!-- N3, the reason next to a disabled control or group of buttons (ESTANDAR 2.2): a thin wrapper of <session-notice variant="reason"> (the one component).
	     It draws nothing when the person may. ONE reason per group of buttons, below the group; never only a title="". The sign-in call is the chip of the bar.
	       <lock-reason min="technician" />                 the role the page section needs
	       <lock-reason op="light.set" need="operator" />   one operation of the service table
	       <lock-reason kind="down" />                      a cause known by the page (text: the standard one, or :text)
	       <lock-reason min="technician" action="Saving the zones" />   the sentence names what needs the role -->
	<session-notice variant="reason" :min="min" :op="op" :need="need" :ctx="ctx" :kind="kind" :text="text" :action="action" />
</template>

<script>
'use strict'

import SessionNotice from './SessionNotice.vue'

export default {
	components: { SessionNotice },
	props: {
		min: { type: String, default: '' },
		op: { type: String, default: '' },
		need: { type: String, default: '' },
		ctx: { type: Object, default: null },
		kind: { type: String, default: '' },
		text: { type: String, default: '' },
		action: { type: String, default: '' }
	}
}
</script>
