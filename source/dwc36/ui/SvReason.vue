<template>
	<!-- Why the controls of a block do not move because of the ROLE: ONE sentence per block, at its foot, no button. Nobody signed in is said once by the
	     cover of the place and by the chip of the header, so a lock of state 'session' draws nothing here.
	     Props: lock ({ state: 'session' | 'role', text } of session.can / a resource; null, 'ok' or 'session' = nothing is drawn). -->
	<div v-if="lock && lock.state === 'role'" class="sv-reason" :data-cause="lock.state">
		<span class="mdi sv-ico mdi-lock-outline" aria-hidden="true" />
		<span>{{ lock.text }}</span>
	</div>
</template>

<script>
import { svTextMixin } from './sv-text.js'

export default {
	name: 'SvReason',
	mixins: [svTextMixin],
	props: { lock: { type: Object, default: null } }
}
</script>
