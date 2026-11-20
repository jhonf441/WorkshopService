<template>
	<!-- The whole event of one row, without secrets: who, what, the rule that decided, the target, the context (device, way in, the address that only informs),
	     the summary of the arguments and the fingerprint of its link of the chain (audit.export of that one row; a row older than the chain has none).
	     A change of access shows what it was and what it became.
	       <activity-event :row="row" @close="..." /> -->
	<v-dialog :value="true" max-width="680" width="100%" scrollable content-class="activity-event" @input="$emit('close')">
		<v-card role="dialog" aria-labelledby="activity-event-title">
			<v-card-title id="activity-event-title" class="text-subtitle-1">{{ $t('plugins.WorkshopService.access.audit_drawer_title', { id: row.id }) }}</v-card-title>
			<v-card-text>
				<dl class="activity-fields">
					<template v-for="f in fields">
						<dt :key="'k' + f.key">{{ $t('plugins.WorkshopService.access.' + f.key) }}</dt>
						<dd :key="'v' + f.key"><pre v-if="f.block" class="sv-diff">{{ f.value }}</pre><template v-else>{{ f.value }}<code v-if="f.code" class="access-id">{{ f.code }}</code></template></dd>
					</template>
				</dl>
				<div v-if="!view.hasDetail" class="wf-help">{{ $t('plugins.WorkshopService.access.audit_d_no_detail') }}</div>
				<div v-if="change" class="activity-change">
					<strong>{{ $t('plugins.WorkshopService.access.audit_d_change', { name: change.name }) }}</strong>
					<div class="access-change-cols">
						<section class="access-change-col"><div class="text-caption">{{ $t('plugins.WorkshopService.access.audit_before') }}</div><code>{{ change.before }}</code></section>
						<section class="access-change-col"><div class="text-caption">{{ $t('plugins.WorkshopService.access.audit_after') }}</div><code>{{ change.after }}</code></section>
					</div>
				</div>
				<div class="activity-chain-hash">
					<strong>{{ $t('plugins.WorkshopService.access.audit_d_hash') }}</strong>
					<div v-if="hash === null && !hashFailed" class="text-caption">{{ $t('plugins.WorkshopService.access.common_loading') }}</div>
					<div v-else-if="hashFailed" class="text-caption">{{ $t('plugins.WorkshopService.access.audit_d_hash_failed') }}</div>
					<div v-else-if="!hash.hash" class="text-caption">{{ $t('plugins.WorkshopService.access.audit_d_no_chain') }}</div>
					<template v-else>
						<code class="activity-hash">{{ hash.hash }}</code>
						<div class="text-caption">{{ $t('plugins.WorkshopService.access.audit_d_prev') }}</div>
						<code class="activity-hash">{{ hash.prev_hash }}</code>
					</template>
				</div>
			</v-card-text>
			<v-card-actions>
				<v-spacer />
				<v-btn small color="primary" class="access-touch" @click="$emit('close')">{{ $t('plugins.WorkshopService.access.common_back') }}</v-btn>
			</v-card-actions>
		</v-card>
	</v-dialog>
</template>

<script>
'use strict'

import { accessApi } from './access-api.js'
import { RESULTS, changeOf, rowView } from './access-audit-view.js'
import { displayNamesMixin } from './display-names-mixin.js'
import { niceResponse } from './sections/links/commands-view.js'

export default {
	mixins: [displayNamesMixin],
	props: { row: { type: Object, required: true } },
	data() {
		return { hash: null, hashFailed: false, extra: null }
	},
	computed: {
		// the row of the list, plus the detail the export of this one row brings when the list was asked without it
		merged() {
			return Object.assign({}, this.row, { detail: this.row.detail || (this.extra && this.extra.detail) || null })
		},
		view() {
			return rowView(this.merged)
		},
		change() {
			return changeOf(this.row)
		},
		// only what the row has: nothing is invented, nothing secret is in the row (the service keeps the arguments without PINs or keys)
		fields() {
			const r = this.merged
			const d = r.detail && typeof r.detail === 'object' ? r.detail : {}
			const f = []
			// `raw` is the identifier behind a readable text: it is drawn as quiet code when the text is not the identifier itself
			const add = (key, value, raw, block) => { if (value !== undefined && value !== null && value !== '') f.push({ key, value: String(value), block: !!block, code: raw !== undefined && String(raw) !== String(value) ? String(raw) : '' }) }
			// the message of a row that failed is the text of the service; the words of the result are shown in their own field
			const said = d.message || (RESULTS.includes(r.result) || r.result === 'ok' ? '' : r.result)
			add('audit_col_when', this.view.when)
			add('audit_col_person', r.user ? r.user + (r.role ? ' (' + this.roleText(r.role) + ')' : '') : '')
			add('audit_col_operation', r.op)
			add('audit_col_result', this.$t('plugins.WorkshopService.access.audit_f_result_' + this.view.result))
			add('audit_d_code', r.code ? this.codeText(r.code) : '', r.code)
			add('audit_d_reason', d.reason ? this.causeText(d.reason) : '', d.reason)
			add('audit_d_profile', d.profile ? this.profileText(d.profile) : '', d.profile)
			add('audit_d_rule', d.rule ? this.ruleText(d.rule, d.profile) : '', d.rule)
			add('audit_d_ceiling', d.ceiling ? this.profileText(d.ceiling) : '', d.ceiling)
			add('audit_d_target', d.target)
			add('audit_d_message', said)
			if (Number.isInteger(d.duration_ms)) add('audit_d_duration', this.$t('plugins.WorkshopService.access.audit_d_ms', { n: d.duration_ms }))
			add('audit_d_device', r.device)
			add('audit_d_via', r.via ? this.viaText(r.via) : '', r.via)
			add('audit_d_ip', r.ip)
			// the summary of the arguments is JSON in one line: indented, in a block that wraps (as the code and the response of the calls)
			if (!this.change) add('audit_d_args', r.args === undefined || r.args === null || r.args === '' ? '' : niceResponse(typeof r.args === 'string' ? r.args : JSON.stringify(r.args)), undefined, true)
			return f
		}
	},
	created() {
		this.loadHash()
	},
	methods: {
		async loadHash() {
			const day = String(this.row.ts || '').slice(0, 10)
			try {
				const page = await accessApi.auditExport({ from: day, to: day }, (this.row.id | 0) - 1, 1)
				const one = JSON.parse(String(page.jsonl || '').split('\n')[0] || 'null')
				if (one && one.id === this.row.id) {
					this.extra = one
					this.hash = { hash: one.hash || '', prev_hash: one.prev_hash || '' }
				} else this.hashFailed = true
			} catch (e) {
				this.hashFailed = true
			}
		}
	}
}
</script>

<style>
.activity-fields { display: grid; grid-template-columns: max-content 1fr; gap: 4px 16px; margin: 0 0 12px; }
.activity-fields dt { font-weight: 600; }
.activity-fields dd { margin: 0; overflow-wrap: anywhere; }
.activity-hash { display: block; overflow-wrap: anywhere; }
.activity-change { margin: 8px 0; }
@media (max-width: 900px) { .activity-event { margin: 0; max-height: 100%; height: 100%; max-width: 100%; } }
</style>
