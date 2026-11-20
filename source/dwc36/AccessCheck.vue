<template>
	<!-- "What this person can do" (DISENO-PANTALLAS 2.3): try one operation with an optional target and context. It only calls access.check, which changes nothing.
	     With users turned off there is nobody to try: the fields are off and the fixed sentence says why.
	       <access-check :user="'Maria'" :role="'operator'" :disabled="usersOff" :damaged="false" /> -->
	<div class="access-check">
		<div class="access-rule-label">{{ $t('plugins.WorkshopService.access.check_title') }}</div>
		<div v-if="disabled" class="wf-note is-warn mt-2" role="note"><v-icon class="wf-note-icon" aria-hidden="true">mdi-alert-outline</v-icon><span>{{ $t('plugins.WorkshopService.access.check_disabled_users') }}</span></div>
		<div class="access-check-form">
			<sv-text-field v-model="form.operation" :disabled="disabled" :label="$t('plugins.WorkshopService.access.check_operation')" @enter="run()" />
			<sv-text-field v-model="form.target" :disabled="disabled" :label="$t('plugins.WorkshopService.access.check_target')" placeholder="workshop:lights:scene/night" @enter="run()" />
			<sv-select v-model="form.mode" :items="modeItems" :disabled="disabled" :label="$t('plugins.WorkshopService.access.check_mode')" />
			<sv-select v-model="form.job" :items="stateItems" :disabled="disabled" :label="$t('plugins.WorkshopService.access.check_job')" />
			<sv-select v-model="form.machineOn" :items="stateItems" :disabled="disabled" :label="$t('plugins.WorkshopService.access.check_machine_on')" />
			<sv-select v-model="form.via" :items="viaItems" :disabled="disabled" :label="$t('plugins.WorkshopService.access.check_via')" />
			<v-btn small color="primary" class="access-touch" :loading="busy" :disabled="disabled || !form.operation.trim()" @click="run()">{{ $t('plugins.WorkshopService.access.check_try') }}</v-btn>
		</div>
		<div v-if="!form.operation.trim() && !outcome" class="wf-help">{{ $t('plugins.WorkshopService.access.check_need_operation') }}</div>
		<access-state :state="state" :detail="detail" @retry="run()">
			<access-check-result v-if="outcome" :outcome="outcome" :role="role" />
		</access-state>
	</div>
</template>

<script>
'use strict'

import SvTextField from './ui/SvTextField.vue'
import SvSelect from './ui/SvSelect.vue'
import AccessState from './AccessState.vue'
import AccessCheckResult from './AccessCheckResult.vue'
import { accessApi } from './access-api.js'
import { MODE_CHOICES, TRISTATE, VIA_CHOICES, checkOutcome, checkRequest } from './access-people-view.js'
import { stateOfError } from './access-profile-view.js'

const AREA = 'plugins.WorkshopService.access.'

export default {
	components: { SvTextField, SvSelect, AccessState, AccessCheckResult },
	props: {
		user: { type: String, required: true },
		role: { type: String, default: '' },
		disabled: { type: Boolean, default: false },
		damaged: { type: Boolean, default: false }
	},
	data() {
		return { form: { operation: '', target: '', mode: '', job: '', machineOn: '', via: 'session' }, outcome: null, state: '', detail: '', busy: false }
	},
	computed: {
		modeItems() {
			return MODE_CHOICES.map(m => ({ value: m, text: m === '' ? this.$t(AREA + 'check_unset') : m === 'now' ? this.$t(AREA + 'check_mode_now') : m }))
		},
		stateItems() {
			return TRISTATE.map(v => ({ value: v, text: v === '' ? this.$t(AREA + 'check_unset') : this.$t(AREA + (v === 'yes' ? 'common_yes' : 'common_no')) }))
		},
		viaItems() {
			return VIA_CHOICES.map(v => ({ value: v, text: this.$t(AREA + 'check_via_' + v) }))
		}
	},
	watch: {
		user() {
			this.outcome = null
			this.state = ''
		}
	},
	methods: {
		async run() {
			if (this.disabled || !this.form.operation.trim() || this.busy) return
			this.busy = true
			this.state = ''
			this.detail = ''
			try {
				const answer = await accessApi.check(checkRequest(this.form, this.user))
				this.outcome = checkOutcome(answer, { damaged: this.damaged })
			} catch (e) {
				this.outcome = null
				this.state = stateOfError(e)
				this.detail = (e && e.message) || ''
			} finally {
				this.busy = false
			}
		}
	}
}
</script>

<style>
.access-check { margin-top: 16px; padding-top: 12px; border-top: 1px solid var(--wf-line); }
.access-check-form { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 12px 12px; align-items: center; margin-top: 10px; }
</style>
