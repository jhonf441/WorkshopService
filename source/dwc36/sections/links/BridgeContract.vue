<template>
	<!-- The contract of the bridge with the service, shown to the person: the channels (one card each: who writes, who reads, the file), the keys of the state
	     file, the rules, and the REAL state file compared with them. Read-only: it writes nothing and reads only what the screen already read.
	     Props: open, stopped (the unit was stopped: what the file holds is from before). Event: close. -->
	<wf-sheet :open="open" :title="tr('contract_title')" wide @close="$emit('close')">
		<div class="sv-sheet-flow">
		<div class="sv-ct-head"><span class="sv-chip-sm" data-part="version">{{ tr('contract_dlg_version', { n: version }) }}</span></div>
		<span class="sv-seg sv-seg-full" role="group" :aria-label="tr('contract_tabs_label')">
			<button v-for="(k, i) in TABS" :key="k" type="button" :aria-pressed="tab === i ? 'true' : 'false'" :data-tab="k" @click="tab = i">{{ tr('contract_tab_' + k) }}</button>
		</span>
		<div v-if="tab === 0" data-part="channels">
			<p class="sv-quiet">{{ tr('contract_intro_channels') }}</p>
			<div class="sv-ct-cards">
				<article v-for="c in channelCards" :key="c.id" class="sv-ct-card" :data-channel="c.id">
					<header class="sv-ct-card-head"><b class="sv-ct-id">{{ c.id }}</b><span class="sv-chip-sm">{{ tr('contract_section', { n: c.section }) }}</span></header>
					<div class="sv-ct-flow" role="group" :aria-label="tr('contract_col_flow')">
						<span v-for="w in c.writers" :key="'w' + w" class="sv-actor" :data-actor="actorOf(w)">{{ w }}</span>
						<span class="mdi mdi-arrow-right sv-ico sv-ct-arrow" aria-hidden="true" />
						<span v-for="r in c.readers" :key="'r' + r" class="sv-actor" :data-actor="actorOf(r)">{{ r }}</span>
					</div>
					<div class="sv-ct-file"><code class="sv-code" :title="c.where">{{ c.where }}</code><sv-copy-button kind="channel" :label="c.id" :done="copied === c.id" @copy="copy(c.where, c.id)" /></div>
					<p class="sv-ct-promise">{{ c.promise }}</p>
				</article>
			</div>
		</div>
		<div v-else-if="tab === 1" data-part="keys">
			<p class="sv-quiet">{{ tr('contract_intro_state', { s: schemas }) }}</p>
			<ul class="sv-ct-keys">
				<li v-for="k in keys" :key="k.path" class="sv-ct-key"><div class="sv-ct-key-head"><code class="sv-code">{{ k.path }}</code><span class="sv-chip-sm">{{ k.types.join(' | ') }}</span><span class="sv-chip-sm" :class="{ 'sv-chip-safety': k.required }">{{ tr(k.required ? 'contract_req_required' : 'contract_req_optional') }}</span></div><p class="sv-ct-promise">{{ k[lang] }}</p></li>
			</ul>
		</div>
		<div v-else-if="tab === 2" data-part="rules">
			<p class="sv-quiet">{{ tr('contract_intro_rules') }}</p>
			<ol class="sv-ct-rules">
				<li v-for="r in rules" :key="r.id" class="sv-ct-rule"><span class="mdi mdi-check-decagram-outline sv-ico" aria-hidden="true" /><div><div class="sv-row-name">{{ r.text[lang] }}</div><div class="sv-row-desc">{{ tr('contract_section', { n: r.section }) }}</div></div></li>
			</ol>
		</div>
		<div v-else data-part="live">
			<p class="sv-quiet">{{ tr('contract_live_intro') }} {{ tr('contract_live_readonly') }}</p>
			<p class="sv-note" :data-level="verdictLevel" role="note"><span class="mdi sv-ico" :class="verdictLevel === 'warn' ? 'mdi-alert-outline' : 'mdi-information-outline'" aria-hidden="true" /><span><b>{{ tr('contract_verdict_' + verdict) }}</b><br>{{ tr('contract_verdict_' + verdict + '_help') }}</span></p>
			<dl class="sv-facts"><dt>{{ tr('contract_val_schema') }}</dt><dd><span class="sv-chip-sm">{{ values.schema }}</span></dd><dt>{{ tr('contract_val_contract') }}</dt><dd><span class="sv-chip-sm">{{ values.contract }}</span></dd><dt>{{ tr('contract_val_version') }}</dt><dd><span class="sv-chip-sm">{{ values.version }}</span></dd><dt>{{ tr('contract_val_age') }}</dt><dd><span class="sv-chip-sm">{{ values.age }}</span></dd></dl>
			<p v-if="!cmp.available" class="sv-quiet">{{ tr('contract_live_nodata') }}</p>
			<template v-else>
				<p class="sv-quiet" data-part="counts">{{ countsText }}</p>
				<ul class="sv-ct-keys">
					<li v-for="r in rows" :key="r.path" class="sv-ct-key" :data-bad="r.bad ? '' : null"><div class="sv-ct-key-head"><code class="sv-code">{{ r.path }}</code><span class="sv-chip-sm">{{ tr(r.required ? 'contract_req_required' : 'contract_req_optional') }}</span><span class="sv-state" :data-level="r.bad ? 'error' : 'ok'">{{ r.text }}</span></div></li>
				</ul>
			</template>
		</div>
		</div>
		<template #foot><button type="button" class="wf-btn sv-btn" data-wf-autofocus @click="$emit('close')">{{ tr('contract_close') }}</button></template>
	</wf-sheet>
</template>

<script>
import { bridge } from '../../core/store/bridge.js'
import { locale } from '../../core/dwc.js'
import { timeNow } from '../../core/clock.js'
import * as contract from '../../bridge-contract.js'
import { CHANNELS, CONTRACT_VERSION, KNOWN_SCHEMAS, RULES, STATE_KEYS } from '../../bridge-contract-data.js'
import WfSheet from '../../WfSheet.vue'
import SvCopyButton from '../../ui/SvCopyButton.vue'
import { copyText } from '../../copy.js'
import { tr } from './bridge-orders.js'

const TABS = Object.freeze(['channels', 'state', 'rules', 'live'])

export default {
	name: 'BridgeContract',
	components: { WfSheet, SvCopyButton },
	props: { open: { type: Boolean, default: false }, stopped: { type: Boolean, default: false } },
	data() {
		return { TABS, copied: '', tab: 0, channels: CHANNELS, keys: STATE_KEYS, rules: RULES, version: CONTRACT_VERSION, schemas: KNOWN_SCHEMAS.join(', ') }
	},
	computed: {
		lang() {
			return String(locale() || 'es').toLowerCase().indexOf('es') === 0 ? 'es' : 'en'
		},
		// one card per channel: the writers and the readers apart ("bridge -> service, jog, page"), the file, the promise
		channelCards() {
			return this.channels.map(c => {
				const [w, r] = String(c.flow[this.lang] || c.flow.en).split('->').map(x => x.split(',').map(y => y.trim()).filter(Boolean))
				return { id: c.id, section: c.section, writers: w || [], readers: r || [], where: c.where, promise: c.promise[this.lang] }
			})
		},
		ageS() {
			return bridge.received ? Math.max(0, (timeNow() - bridge.received) / 1000) : null
		},
		read() {
			return bridge.e ? contract.parse(bridge.e, this.ageS) : contract.missing()
		},
		verdict() {
			return contract.verdict(this.read, this.stopped)
		},
		verdictLevel() {
			return ['old', 'newer', 'unknown_format'].indexOf(this.verdict) >= 0 ? 'warn' : 'info'
		},
		values() {
			const r = this.read
			const none = tr('contract_val_none')
			const hasFile = r.status !== 'missing'
			return {
				schema: hasFile && r.schema !== null && r.schema !== undefined ? String(r.schema) : none,
				contract: r.status === 'ok' ? (r.legacy ? tr('contract_val_not_declared') : String(r.contract)) : none,
				version: r.version || none,
				age: this.ageS === null ? none : tr('contract_val_seconds', { n: Math.round(this.ageS) })
			}
		},
		cmp() {
			return contract.compareState(bridge.e, STATE_KEYS)
		},
		rows() {
			const by = {}
			STATE_KEYS.forEach(k => { by[k.path] = k })
			return this.cmp.rows.map(r => ({ path: r.path, required: by[r.path].required, bad: r.status === 'missing_required' || r.status === 'wrong_type', text: r.status === 'wrong_type' ? tr('contract_st_wrong_type', { found: r.found }) : tr('contract_st_' + r.status) }))
		},
		countsText() {
			const c = { ok: 0, opt: 0, bad: 0, na: 0 }
			this.cmp.rows.forEach(r => { if (r.status === 'ok') c.ok++; else if (r.status === 'na') c.na++; else if (r.status === 'missing_optional') c.opt++; else c.bad++ })
			return tr('contract_counts', { ok: tr('contract_n_ok', { n: c.ok }, c.ok), opt: tr('contract_n_opt', { n: c.opt }, c.opt), bad: tr('contract_n_bad', { n: c.bad }, c.bad), na: tr('contract_n_na', { n: c.na }, c.na) })
		}
	},
	methods: {
		tr,
		// the hue of an actor in the flow: the same word in both languages
		actorOf(name) {
			const n = String(name).toLowerCase()
			return /puente|bridge/.test(n) ? 'bridge' : /servicio|service/.test(n) ? 'service' : /jog/.test(n) ? 'jog' : /p.gina|page/.test(n) ? 'page' : 'other'
		},
		async copy(text, id) {
			if (!(await copyText(text))) return
			this.copied = id
			setTimeout(() => { if (this.copied === id) this.copied = '' }, 1500)
		}
	}
}
</script>
