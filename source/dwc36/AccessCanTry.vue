<template>
	<!-- "Try as this person" (read only): ONE action in words, with the conditions folded, and the answer of the service with its reason. It only calls access.check:
	     it does not sign in as the person, uses no PIN and leaves nothing in the record. The exact operation by name stays folded for the expert (AccessCheck).
	       <access-can-try :user="'Maria'" :role="'operator'" :caps="caps" :damaged="false" /> -->
	<div class="can-try">
		<div class="wf-help mb-2">{{ $t('plugins.WorkshopService.access.who_try_note') }}</div>
		<sv-select v-model="capId" :items="capItems" :label="$t('plugins.WorkshopService.access.who_try_action')" :placeholder="$t('plugins.WorkshopService.access.who_try_pick')" />
		<details class="mt-2">
			<summary class="can-try-sum access-touch">{{ $t('plugins.WorkshopService.access.who_try_context') }}</summary>
			<div class="access-check-form">
				<sv-select v-model="form.mode" :items="modeItems" :label="$t('plugins.WorkshopService.access.check_mode')" />
				<sv-select v-model="form.job" :items="stateItems" :label="$t('plugins.WorkshopService.access.check_job')" />
				<sv-select v-model="form.machineOn" :items="stateItems" :label="$t('plugins.WorkshopService.access.check_machine_on')" />
				<sv-select v-model="form.via" :items="viaItems" :label="$t('plugins.WorkshopService.access.check_via')" />
			</div>
		</details>
		<div v-if="capId && !operation" class="wf-help mt-2">{{ $t('plugins.WorkshopService.access.who_try_no_op') }}</div>
		<v-btn small color="primary" class="access-touch mt-2" :loading="busy" :disabled="!operation" @click="run()">{{ $t('plugins.WorkshopService.access.check_try') }}</v-btn>
		<access-state :state="state" :detail="detail" @retry="run()">
			<access-check-result v-if="outcome" :outcome="outcome" :role="role" />
		</access-state>
		<details class="mt-3">
			<summary class="can-try-sum access-touch">{{ $t('plugins.WorkshopService.access.who_try_other') }}</summary>
			<access-check :user="user" :role="role" :damaged="damaged" />
		</details>
	</div>
</template>

<script>
'use strict'

import SvSelect from './ui/SvSelect.vue'
import AccessState from './AccessState.vue'
import AccessCheck from './AccessCheck.vue'
import AccessCheckResult from './AccessCheckResult.vue'
import { accessApi } from './access-api.js'
import { MODE_CHOICES, TRISTATE, VIA_CHOICES, checkOutcome, checkRequest } from './access-people-view.js'
import { stateOfError } from './access-profile-view.js'
import { AREAS, representativeOp } from './access-areas.js'

const AREA = 'plugins.WorkshopService.access.'

export default {
	name: 'AccessCanTry',
	components: { SvSelect, AccessState, AccessCheck, AccessCheckResult },
	props: {
		user: { type: String, required: true },
		role: { type: String, default: '' },
		caps: { type: Array, default: () => [] }, // roles.list capabilities
		damaged: { type: Boolean, default: false }
	},
	data() {
		return { capId: '', form: { mode: '', job: '', machineOn: '', via: 'session' }, outcome: null, state: '', detail: '', busy: false }
	},
	computed: {
		// the actions by area, with the title of the service (never the operation)
		capItems() {
			const out = []
			AREAS.forEach(a => {
				const mine = a.caps.map(id => this.caps.find(c => c.id === id)).filter(Boolean)
				if (!mine.length) return
				out.push({ header: this.$t(AREA + 'area_' + a.id) })
				mine.forEach(c => out.push({ text: c.title || c.id, value: c.id }))
			})
			return out
		},
		operation() {
			return representativeOp(this.caps.find(c => c.id === this.capId))
		},
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
		user() { this.outcome = null; this.state = '' },
		capId() { this.outcome = null; this.state = '' }
	},
	methods: {
		async run() {
			if (!this.operation || this.busy) return
			this.busy = true
			this.state = ''
			this.detail = ''
			try {
				const answer = await accessApi.check(checkRequest(Object.assign({ operation: this.operation }, this.form), this.user))
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
.can-try { margin-bottom: 12px; padding: 10px 12px; border: 1px solid var(--wf-line); border-radius: 8px; }
.can-try-sum { display: flex; align-items: center; min-height: 40px; cursor: pointer; font-size: 13px; }
</style>
