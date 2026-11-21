<template>
	<!-- The DWC password (M551 in sys/config.g, handlers/password.py): what it is for, its state (icon + word), two fields and the double tap buttons.
	     The page owns the state and the calls: this card draws and emits `put` / `remove`. Operations: password.set, password.clear (administrator).
	     A signed-out person gets the ONE sign-in block of the tab (the page draws it): the card is locked and says nothing more; a signed-in person without
	     the role reads ONE reason under the title, not one sentence under each field. -->
	<v-card class="mb-3 dpc">
		<v-card-title>
			<v-icon small class="mr-2 svx-ico">mdi-lock-outline</v-icon>{{ $t('plugins.WorkshopService.servicePage.dwc_password') }}
			<v-spacer />
			<v-chip small outlined :color="chip.color" class="dpc-state"><v-icon left x-small aria-hidden="true">{{ chip.icon }}</v-icon>{{ chip.text }}</v-chip>
		</v-card-title>
		<v-card-text @click="touchLock">
			<div class="text-body-2 mb-1 sv-prose">{{ $t('plugins.WorkshopService.servicePage.with_a_password_dwc_asks_for') }}</div>
			<div class="text-caption mb-2 sv-prose">{{ $t('plugins.WorkshopService.servicePage.password_admin_only') }}</div>
			<lock-reason v-if="!signedOut" op="password.set" need="admin" class="mb-2 svc-lock-reason" />
			<sv-form-row>
				<sv-text-field v-model="state.newEntry" :type="state.show ? 'text' : 'password'" :disabled="!allowed" :label="$t('plugins.WorkshopService.servicePage.new_password')" :error="fieldError('password')" autocomplete="new-password" spellcheck="false" autocapitalize="off">
					<template #append><button type="button" class="sv-field-btn" :disabled="!allowed" :aria-pressed="state.show ? 'true' : 'false'" :aria-label="state.show ? $t('plugins.WorkshopService.servicePage.pw_hide') : $t('plugins.WorkshopService.servicePage.pw_show')" @click="$set(state, 'show', !state.show)"><span class="mdi" :class="state.show ? 'mdi-eye-off' : 'mdi-eye'" aria-hidden="true" /></button></template>
				</sv-text-field>
				<sv-text-field v-model="state.repeat" :type="state.show ? 'text' : 'password'" :disabled="!allowed" :label="$t('plugins.WorkshopService.servicePage.repeat_the_password')" :error="fieldError('repeat')" autocomplete="new-password" spellcheck="false" autocapitalize="off" />
				<template #act>
					<arm-button color="primary" :loading="state.sending" :disabled="!valid || !canDo('password.set')" :armed-text="$t('plugins.WorkshopService.servicePage.confirm_q')" @confirm="$emit('put')">
						<v-icon v-if="!canDo('password.set')" small left aria-hidden="true">mdi-lock-outline</v-icon>{{ state.has ? $t('plugins.WorkshopService.servicePage.change') : $t('plugins.WorkshopService.servicePage.set_2') }}
					</arm-button>
				</template>
			</sv-form-row>
			<password-meter v-if="allowed" :level="level" :typed="!!state.newEntry" :reqs="reqs" :min="min" :max="max" />
			<div v-if="allowed && !valid" class="text-caption mt-2 sv-prose sv-pw-why" role="status" data-part="pw-why">{{ $t('plugins.WorkshopService.servicePage.pw_blocked') }} {{ problem }}</div>
			<div class="text-caption warning--text mt-2 sv-prose">{{ $t('plugins.WorkshopService.servicePage.if_you_forget_it_dwc_won') }}</div>
			<div class="d-flex align-center mt-3">
				<arm-button v-if="state.has" small outlined :disabled="state.sending || !canDo('password.clear')" :armed-text="$t('plugins.WorkshopService.servicePage.confirm_q')" @confirm="$emit('remove')">
					<v-icon v-if="!canDo('password.clear')" small left aria-hidden="true">mdi-lock-outline</v-icon>{{ $t('plugins.WorkshopService.servicePage.remove_the_password') }}
				</arm-button>
				<span v-if="state.msg" class="text-caption ml-3">{{ state.msg }}</span>
			</div>
			<error-notice :error="state.error" class="mt-2" />
		</v-card-text>
	</v-card>
</template>

<script>
'use strict'

import SvTextField from './ui/SvTextField.vue'
import SvFormRow from './ui/SvFormRow.vue'
import PasswordMeter from './PasswordMeter.vue'
import { roleMixin } from './role-mixin.js'
import { blinkLocked } from './lock-attention.js'
import { passwordChip } from './dwc-password.js'
import LockReason from './LockReason.vue'
import { ArmButton, ErrorNotice } from './arm-kit.js'

// Props: state ({ has: true | false | null, newEntry, repeat, show, sending, msg, error, fieldError: { field, text } }), problem (why the typed one cannot be set yet, the
// first unmet rule, and it is what the button's reason says), valid, level (0 very weak to 3 strong), reqs ([{ id, ok }]), min / max (the limits), signedOut.
// The password is only in state.newEntry / state.repeat: never copied or kept anywhere else.
export default {
	name: 'DwcPasswordCard',
	components: { SvTextField, SvFormRow, PasswordMeter, LockReason, ArmButton, ErrorNotice },
	mixins: [roleMixin],
	props: {
		state: { type: Object, required: true },
		problem: { type: String, default: '' },
		valid: { type: Boolean, default: false },
		level: { type: Number, default: 0 },
		reqs: { type: Array, default: () => [] },
		min: { type: Number, default: 10 },
		max: { type: Number, default: 60 },
		signedOut: { type: Boolean, default: false }
	},
	computed: {
		allowed() { return this.canDo('password.set') },
		chip() { return passwordChip(this.state.has, key => this.$t('plugins.WorkshopService.' + key)) }
	},
	methods: {
		// what the server refused (422 invalid_args) goes under the field it names
		fieldError(field) {
			const e = this.state.fieldError
			return e && e.field === field ? e.text : ''
		},
		// a touch on the card while this role cannot change it (a disabled control emits no click): its one reason blinks
		touchLock(ev) {
			if (this.canDo('password.set') && this.canDo('password.clear')) return
			const el = ev && ev.currentTarget ? ev.currentTarget : null
			if (el) blinkLocked(el, this.signedOut)
		}
	}
}
</script>

<style>
/* STRUCTURE only (the look is family.css): 40 px targets for the two buttons of the card */
.dpc .v-btn { min-height: 40px; }
.dpc .dpc-state { pointer-events: none; }
</style>
