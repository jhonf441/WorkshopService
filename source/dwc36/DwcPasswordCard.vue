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
			<div class="text-body-2 mb-1">{{ $t('plugins.WorkshopService.servicePage.with_a_password_dwc_asks_for') }}</div>
			<div class="text-caption mb-2">{{ $t('plugins.WorkshopService.servicePage.password_admin_only') }}</div>
			<lock-reason v-if="!signedOut" op="password.set" need="admin" class="mb-2 svc-lock-reason" />
			<v-row dense>
				<v-col cols="12" sm="5">
					<sv-text-field v-model="state.newEntry" type="password" :disabled="!allowed" :label="$t('plugins.WorkshopService.servicePage.new_password')" autocomplete="new-password" />
				</v-col>
				<v-col cols="12" sm="5">
					<sv-text-field v-model="state.repeat" type="password" :disabled="!allowed" :label="$t('plugins.WorkshopService.servicePage.repeat_the_password')" autocomplete="new-password" />
				</v-col>
				<v-col cols="12" sm="2" class="d-flex align-center">
					<arm-button small block color="primary" :loading="state.sending" :disabled="!valid || !canDo('password.set')" :armed-text="$t('plugins.WorkshopService.servicePage.confirm_q')" @confirm="$emit('put')">
						<v-icon v-if="!canDo('password.set')" small left aria-hidden="true">mdi-lock-outline</v-icon>{{ state.has ? $t('plugins.WorkshopService.servicePage.change') : $t('plugins.WorkshopService.servicePage.set_2') }}
					</arm-button>
				</v-col>
			</v-row>
			<div v-if="state.newEntry && !valid" class="text-caption warning--text mt-1">{{ problem }}</div>
			<div class="text-caption warning--text mt-3">{{ $t('plugins.WorkshopService.servicePage.if_you_forget_it_dwc_won') }}</div>
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
import { roleMixin } from './role-mixin.js'
import { blinkLocked } from './lock-attention.js'
import { passwordChip } from './dwc-password.js'
import LockReason from './LockReason.vue'
import { ArmButton, ErrorNotice } from './arm-kit.js'

// Props: state ({ has: true | false | null, newEntry, repeat, sending, msg, error }), problem (why the typed one is not valid, '' = valid), valid, signedOut.
export default {
	name: 'DwcPasswordCard',
	components: { SvTextField, LockReason, ArmButton, ErrorNotice },
	mixins: [roleMixin],
	props: {
		state: { type: Object, required: true },
		problem: { type: String, default: '' },
		valid: { type: Boolean, default: false },
		signedOut: { type: Boolean, default: false }
	},
	computed: {
		allowed() { return this.canDo('password.set') },
		chip() { return passwordChip(this.state.has, key => this.$t('plugins.WorkshopService.' + key)) }
	},
	methods: {
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
