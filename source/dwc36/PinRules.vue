<template>
	<!-- The requirements of a NEW or CHANGED PIN, with a check or a cross while the person types (the words say it; the colour only helps), and the reason that keeps
	     the button off. Same look as the requirements of the DWC password (PasswordMeter: the classes sv-pwm-*). Pure drawing: the form computes `pin` and `repeat`
	     (never kept here, never sent anywhere) and this asks password-policy.js. Props: pin, repeat, withMatch (a second entry exists). -->
	<div class="sv-pwm pin-rules" :class="{ 'sv-pwm-idle': !typed }">
		<ul class="sv-pwm-reqs">
			<li v-for="r in reqs" :key="r.id" :class="r.ok ? 'sv-pwm-ok' : 'sv-pwm-no'">
				<span class="mdi" :class="r.ok ? 'mdi-check-circle-outline' : 'mdi-close-circle-outline'" aria-hidden="true" />
				<span class="sv-pwm-sr">{{ $t('plugins.WorkshopService.servicePage.' + (r.ok ? 'pw_met' : 'pw_not_met')) }}: </span>{{ $t('plugins.WorkshopService.users.pin_req_' + r.id, { min: min, max: max }) }}
			</li>
		</ul>
		<div v-if="why" class="text-caption sv-pwm-no" role="note">{{ $t('plugins.WorkshopService.users.pin_rule_' + why, { min: min, max: max }) }}</div>
	</div>
</template>

<script>
'use strict'

import { PIN_MAX_LEN, PIN_MIN_LEN, checkPin, pinRequirements } from './password-policy.js'

export default {
	name: 'PinRules',
	props: {
		pin: { type: String, default: '' },
		repeat: { type: String, default: '' },
		withMatch: { type: Boolean, default: true }
	},
	computed: {
		min() { return PIN_MIN_LEN },
		max() { return PIN_MAX_LEN },
		typed() { return !!this.pin },
		reqs() { return pinRequirements(this.pin, this.repeat).filter(r => this.withMatch || r.id !== 'match') },
		// the first rule that breaks, said in a sentence under the list (also what disables the button)
		why() { return this.typed ? checkPin(this.pin, this.withMatch && this.repeat ? this.repeat : undefined) : '' }
	}
}
</script>
