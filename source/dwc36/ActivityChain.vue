<template>
	<!-- The verification chain of the recorded activity: "Verify now" walks audit.verify page by page (progress, cancel) and says "correct: N links" or the
	     first broken row with its reason. A row older than the chain is outside it, not an error. Emits `broken` (true / false) so the page can show its chip.
	       <activity-chain :can-verify="true" @broken="v => ..." /> -->
	<div class="activity-chain">
		<access-state :state="verdict === 'broken' ? 'chain_broken' : ''" :params="noticeParams">
			<div class="activity-chain-line">
				<strong class="activity-chain-title">{{ $t('plugins.WorkshopService.access.audit_chain') }}</strong>
				<v-chip small outlined label :color="chipColor">{{ line }}</v-chip>
				<span v-if="at" class="text-caption">{{ at }}</span>
				<v-spacer />
				<v-btn v-if="running" small outlined class="access-touch" @click="cancelled = true"><v-icon left small>mdi-close</v-icon>{{ $t('plugins.WorkshopService.access.audit_chain_cancel') }}</v-btn>
				<v-btn v-else small outlined class="access-touch" :disabled="!canVerify" @click="verify()"><v-icon left small>mdi-shield-check-outline</v-icon>{{ $t('plugins.WorkshopService.access.audit_chain_verify') }}</v-btn>
			</div>
			<div v-if="notes.length" class="text-caption activity-chain-notes">{{ notes.join(' - ') }}</div>
		</access-state>
	</div>
</template>

<script>
'use strict'

import AccessState from './AccessState.vue'
import { accessApi } from './access-api.js'
import { chainReasonKey, verifyChain } from './access-audit-view.js'

const AREA = 'plugins.WorkshopService.access.'

export default {
	components: { AccessState },
	props: { canVerify: { type: Boolean, default: true } },
	data() {
		return { running: false, cancelled: false, verdict: '', checked: 0, result: null, failure: '', at: '' }
	},
	computed: {
		reason() {
			const b = this.result && this.result.broken
			return b ? this.$t(AREA + chainReasonKey(b.reason), { code: b.reason }) : ''
		},
		noticeParams() {
			const b = this.result && this.result.broken
			return { id: b ? b.audit_id : '', reason: this.reason }
		},
		chipColor() {
			return { ok: 'success', broken: 'error', error: 'error', cancelled: 'warning' }[this.verdict] || ''
		},
		line() {
			if (this.running) return this.$tc(AREA + 'audit_chain_progress', this.checked, { n: this.checked })
			const r = this.result
			if (this.verdict === 'ok') return r.links || r.cuts ? this.$tc(AREA + 'audit_chain_ok', r.links, { n: r.links }) : this.$t(AREA + 'audit_chain_empty')
			if (this.verdict === 'broken') return this.$t(AREA + 'audit_chain_broken', this.noticeParams)
			if (this.verdict === 'cancelled') return this.$tc(AREA + 'audit_chain_cancelled', this.checked, { n: this.checked })
			if (this.verdict === 'error') return this.$t(AREA + 'audit_chain_error', { detail: this.failure })
			return this.$t(AREA + 'audit_chain_unknown')
		},
		notes() {
			const r = this.result
			const out = []
			if (r && r.done && r.pre) out.push(this.$tc(AREA + 'audit_chain_pre', r.pre, { n: r.pre }))
			if (r && r.done && r.cuts) out.push(this.$tc(AREA + 'audit_chain_cuts', r.cuts, { n: r.cuts }))
			return out
		}
	},
	methods: {
		async verify() {
			this.running = true
			this.cancelled = false
			this.checked = 0
			this.failure = ''
			try {
				const r = await verifyChain(after => accessApi.auditVerify(after), { progress: n => { this.checked = n }, cancelled: () => this.cancelled })
				this.result = r
				this.verdict = r.cancelled ? 'cancelled' : r.ok ? 'ok' : 'broken'
				if (!r.cancelled) {
					this.at = new Date().toTimeString().slice(0, 5)
					this.$emit('broken', !r.ok)
				}
			} catch (e) {
				this.result = null
				this.verdict = 'error'
				this.failure = (e && e.message) || String(e)
			}
			this.running = false
		}
	}
}
</script>

<style>
.activity-chain { margin-bottom: 8px; }
.activity-chain-line { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; min-height: 44px; }
</style>
