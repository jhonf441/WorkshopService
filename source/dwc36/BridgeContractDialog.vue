<template>
	<v-dialog :value="value" max-width="1000" width="100%" scrollable content-class="ws-contract-dialog" @input="v => $emit('input', v)">
		<v-card role="dialog" aria-labelledby="ws-contract-title">
			<v-card-title id="ws-contract-title" class="text-subtitle-1">
				{{ tt('contract_dlg_title') }}
				<v-chip small label outlined class="ml-2">{{ tt('contract_dlg_version', { n: version }) }}</v-chip>
				<v-spacer />
				<v-btn icon small :aria-label="tt('contract_close')" :title="tt('contract_close')" @click="$emit('input', false)"><v-icon>mdi-close</v-icon></v-btn>
			</v-card-title>
			<v-tabs v-model="tab" show-arrows :aria-label="tt('contract_tabs_label')">
				<v-tab>{{ tt('contract_tab_channels') }}</v-tab>
				<v-tab>{{ tt('contract_tab_state') }}</v-tab>
				<v-tab>{{ tt('contract_tab_rules') }}</v-tab>
				<v-tab>{{ tt('contract_tab_live') }}</v-tab>
			</v-tabs>
			<v-card-text class="pt-3">
				<v-tabs-items v-model="tab" class="transparent">
					<!-- a) the channels of CONTRACT.md section 1 -->
					<v-tab-item>
						<div class="text-caption grey--text mb-2">{{ tt('contract_intro_channels') }}</div>
						<v-simple-table dense>
							<thead>
								<tr>
									<th class="text-left">{{ tt('contract_col_channel') }}</th>
									<th class="text-left">{{ tt('contract_col_flow') }}</th>
									<th class="text-left">{{ tt('contract_col_where') }}</th>
									<th class="text-left">{{ tt('contract_col_promise') }}</th>
								</tr>
							</thead>
							<tbody>
								<tr v-for="c in channels" :key="c.id">
									<td><strong>{{ c.id }}</strong><div class="text-caption grey--text">{{ tt('contract_section', { n: c.section }) }}</div></td>
									<td>{{ c.flow[lang] }}</td>
									<td><code class="ws-contract-code">{{ c.where }}</code></td>
									<td>{{ c.promise[lang] }}</td>
								</tr>
							</tbody>
						</v-simple-table>
					</v-tab-item>

					<!-- b) every key of the state file schema -->
					<v-tab-item>
						<div class="text-caption grey--text mb-2">{{ tt('contract_intro_state', { s: schemas }) }}</div>
						<v-simple-table dense>
							<thead>
								<tr>
									<th class="text-left">{{ tt('contract_col_key') }}</th>
									<th class="text-left">{{ tt('contract_col_type') }}</th>
									<th class="text-left">{{ tt('contract_col_req') }}</th>
									<th class="text-left">{{ tt('contract_col_desc') }}</th>
								</tr>
							</thead>
							<tbody>
								<tr v-for="k in keys" :key="k.path">
									<td><code class="ws-contract-code">{{ k.path }}</code></td>
									<td>{{ k.types.join(' | ') }}</td>
									<td>{{ k.required ? tt('contract_req_required') : tt('contract_req_optional') }}</td>
									<td>{{ k[lang] }}</td>
								</tr>
							</tbody>
						</v-simple-table>
					</v-tab-item>

					<!-- c) the rules, each with the section of CONTRACT.md it comes from -->
					<v-tab-item>
						<div class="text-caption grey--text mb-2">{{ tt('contract_intro_rules') }}</div>
						<v-list dense class="pa-0">
							<v-list-item v-for="r in rules" :key="r.id" class="px-0">
								<v-list-item-content>
									<v-list-item-title class="ws-contract-wrap">{{ r.text[lang] }}</v-list-item-title>
									<v-list-item-subtitle class="text-caption">{{ tt('contract_section', { n: r.section }) }}</v-list-item-subtitle>
								</v-list-item-content>
							</v-list-item>
						</v-list>
					</v-tab-item>

					<!-- d) the real file against the schema (read-only: it only shows what the card already read) -->
					<v-tab-item>
						<div class="text-caption grey--text mb-2">{{ tt('contract_live_intro') }} {{ tt('contract_live_readonly') }}</div>
						<v-alert dense text :type="verdictType" class="mb-3">
							<strong>{{ tt('contract_verdict_' + verdict) }}</strong>
							<div class="text-caption">{{ tt('contract_verdict_' + verdict + '_help') }}</div>
						</v-alert>
						<v-simple-table dense class="mb-3">
							<tbody>
								<tr><td>{{ tt('contract_val_schema') }}</td><td>{{ values.schema }}</td></tr>
								<tr><td>{{ tt('contract_val_contract') }}</td><td>{{ values.contract }}</td></tr>
								<tr><td>{{ tt('contract_val_version') }}</td><td>{{ values.version }}</td></tr>
								<tr><td>{{ tt('contract_val_age') }}</td><td>{{ values.age }}</td></tr>
							</tbody>
						</v-simple-table>
						<div v-if="!cmp.available" class="text-body-2 grey--text">{{ tt('contract_live_nodata') }}</div>
						<template v-else>
							<div class="text-caption mb-1">{{ tt('contract_counts', counts) }}</div>
							<v-simple-table dense>
								<thead>
									<tr>
										<th class="text-left">{{ tt('contract_col_key') }}</th>
										<th class="text-left">{{ tt('contract_col_req') }}</th>
										<th class="text-left">{{ tt('contract_col_status') }}</th>
									</tr>
								</thead>
								<tbody>
									<tr v-for="r in rows" :key="r.path" :class="r.bad ? 'ws-contract-bad' : ''">
										<td><code class="ws-contract-code">{{ r.path }}</code></td>
										<td>{{ r.required ? tt('contract_req_required') : tt('contract_req_optional') }}</td>
										<td>{{ r.text }}</td>
									</tr>
								</tbody>
							</v-simple-table>
							<div class="text-subtitle-2 mt-3">{{ tt('contract_extras_title', { n: cmp.extras.length }) }}</div>
							<div class="text-caption grey--text mb-1">{{ tt('contract_extras_help') }}</div>
							<div v-if="cmp.extras.length" class="d-flex flex-wrap">
								<code v-for="x in cmp.extras" :key="x" class="ws-contract-code mr-2 mb-1">{{ x }}</code>
							</div>
							<div v-else class="text-body-2 grey--text">{{ tt('contract_extras_none') }}</div>
						</template>
					</v-tab-item>
				</v-tabs-items>
			</v-card-text>
			<v-card-actions>
				<v-spacer />
				<v-btn text @click="$emit('input', false)">{{ tt('contract_close') }}</v-btn>
			</v-card-actions>
		</v-card>
	</v-dialog>
</template>

<script>
'use strict'

import i18n from '../../i18n'
import * as bridgeContract from './bridge-contract.js'
import { STATE_KEYS, CHANNELS, RULES, CONTRACT_VERSION, KNOWN_SCHEMAS } from './bridge-contract-data.js'

// The contract of the G-code bridge with the service, shown to the person: the channels, the keys of the state file, the key rules and the REAL
// state file compared with them. Read-only: it never writes anything and reads only what BridgeCard already read (`state`).
// The data comes from bridge/contract/*.schema.json and viewer.json through the generated bridge-contract-data.js (guarded by a test).
export default {
	name: 'BridgeContractDialog',
	props: {
		value: { type: Boolean, default: false },
		// the parsed bridge-state.json the card holds (null when there is none)
		state: { type: Object, default: null },
		// when the card saw the file change (ms) and the card's clock (ms): the age is the seconds since `seq` last moved
		received: { type: Number, default: null },
		now: { type: Number, default: 0 },
		// the unit was stopped from its own switch: what the file still holds is from before
		stopped: { type: Boolean, default: false }
	},
	data() {
		return { tab: 0 }
	},
	computed: {
		lang() {
			return String(this.$i18n.locale || 'es').toLowerCase().indexOf('es') === 0 ? 'es' : 'en'
		},
		version() {
			return CONTRACT_VERSION
		},
		schemas() {
			return KNOWN_SCHEMAS.join(', ')
		},
		channels() {
			return CHANNELS
		},
		keys() {
			return STATE_KEYS
		},
		rules() {
			return RULES
		},
		ageS() {
			return this.received ? Math.max(0, (this.now - this.received) / 1000) : null
		},
		read() {
			return this.state ? bridgeContract.parse(this.state, this.ageS) : bridgeContract.missing()
		},
		verdict() {
			return bridgeContract.verdict(this.read, this.stopped)
		},
		verdictType() {
			return { ok: 'success', old: 'warning', newer: 'warning', unknown_format: 'error', down: 'info', stopped: 'info' }[this.verdict] || 'info'
		},
		values() {
			const r = this.read
			const none = this.tt('contract_val_none')
			const hasFile = r.status !== 'missing'
			return {
				schema: hasFile && r.schema !== null && r.schema !== undefined ? String(r.schema) : none,
				contract: r.status === 'ok' ? (r.legacy ? this.tt('contract_val_not_declared') : String(r.contract)) : none,
				version: r.version || none,
				age: this.ageS === null ? none : this.tt('contract_val_seconds', { n: Math.round(this.ageS) })
			}
		},
		cmp() {
			return bridgeContract.compareState(this.state, STATE_KEYS)
		},
		rows() {
			const byPath = {}
			STATE_KEYS.forEach(k => { byPath[k.path] = k })
			return this.cmp.rows.map(r => ({
				path: r.path,
				required: byPath[r.path].required,
				bad: r.status === 'missing_required' || r.status === 'wrong_type',
				text: r.status === 'wrong_type' ? this.tt('contract_st_wrong_type', { found: r.found }) : this.tt('contract_st_' + r.status)
			}))
		},
		counts() {
			const c = { ok: 0, opt: 0, bad: 0, na: 0 }
			this.cmp.rows.forEach(r => {
				if (r.status === 'ok') c.ok++
				else if (r.status === 'na') c.na++
				else if (r.status === 'missing_optional') c.opt++
				else c.bad++
			})
			return c
		}
	},
	methods: {
		tt(key, params) {
			return i18n.t('plugins.WorkshopService.bridgeCard.' + key, params)
		}
	}
}
</script>

<style>
.ws-contract-code {
	font-size: 12px;
	word-break: break-all;
	white-space: normal;
}
.ws-contract-wrap {
	white-space: normal;
}
.ws-contract-bad td {
	background: rgba(244, 67, 54, 0.12);
}
</style>
