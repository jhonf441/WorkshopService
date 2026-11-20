<template>
	<!-- Connections > Bridge: the G-code bridge, a separate service of the Pi that programs reach by Telnet. One verdict (is it up, who has the machine,
	     with or without key, version and contract), the switch of its unit (technician, two touches to turn it off), the figures, the last hour and,
	     folded, who is connected, security and key, settings, activity, the commands it understands and the debug lines. The states of the file are
	     said as what they are: not installed, old, unknown format, unreadable, or its unit stopped. Prop: active (this tab is in view). -->
	<div class="sv-links-bridge">
		<sv-zone :status="zone" :error="problem" :empty-title="t('bridgeCard.reading_status')" @retry="bridge.readFails = 0; readState()">
			<sv-verdict :level="level" :title="stateText" :facts="facts">
				<button v-if="e && !stopped && !schemaProblem" type="button" class="sv-btn" data-act="contract" @click="contractOpen = true">{{ tr('contract_open') }}</button>
			</sv-verdict>

			<section class="sv-card" aria-labelledby="sv-lb-title" data-card="bridge">
				<div class="sv-card-head"><h2 id="sv-lb-title"><span class="mdi mdi-lan-connect sv-ico" aria-hidden="true" />{{ tr('g_code_bridge_telnet') }}</h2><code class="sv-code" data-part="address">{{ portError ? tr('port_not_listening') : host + ':' + ((e && e.port) || 23) }}</code></div>
				<p class="sv-lead">{{ tr('cutting_programs_terminals_scripts_or') }}</p>
				<ul class="sv-rows">
					<sv-action-row v-if="unit && unit.installed" icon="mdi-power" :name="tr('unit_switch')" :desc="unitDesc" :action="unitSwitch" :permission="perm('bridge.service.set')" :stale="false" :error-text="unitError" @retry="toggleUnit">
						<template #control="c">
							<sv-switch :checked="unit.active" :word="t(unit.active ? 'home.word_on' : 'home.word_off')" :label="tr('unit_switch')" :state="c.state" :disabled="c.disabled || unit.can_control === false" @toggle="toggleUnit" @hold="on => held(c, on)" @escape="c.cancel" />
						</template>
						<p v-if="unit.can_control === false" class="sv-row-desc" data-part="no-control">{{ tr('unit_no_permission') }}</p>
						<template #help><sv-help v-bind="help('unit', 'links')" /></template>
					</sv-action-row>
					<sv-action-row v-if="e && !stopped && !schemaProblem" icon="mdi-restart" :name="tr('restart_bridge')" :desc="inUse || ''" :permission="perm('bridge.service.set')" :label="tr(armed === 'restart' ? 'restart_bridge_confirm' : 'restart_bridge').split(' (')[0]" :stale="!!inUse" @run="restart">
						<template #help><sv-help v-bind="help('restart', 'links')" /></template>
					</sv-action-row>
				</ul>
				<sv-reason :lock="lockOf(['bridge.service.set'])" @sign-in="signIn" />
				<div v-if="outcome" class="sv-row-out" :data-kind="outcome.ok ? 'done' : 'error'" :role="outcome.ok ? 'status' : 'alert'" data-part="outcome"><span class="mdi sv-ico sv-ico-s" :class="outcome.ok ? 'mdi-check-circle-outline' : 'mdi-close-circle-outline'" aria-hidden="true" />{{ outcome.text }}</div>
				<p v-if="portError" class="sv-field-error" role="alert" data-part="port-error"><span class="mdi mdi-alert-outline sv-ico sv-ico-s" aria-hidden="true" />{{ errorText }}</p>

				<p v-if="status === 'missing'" class="sv-note" data-level="info" role="note" data-part="not-installed"><span class="mdi mdi-information-outline sv-ico" aria-hidden="true" /><span>{{ tr('new_bridge_not_installed_yet') }} <code class="sv-code">bridge</code> {{ tr('of_the_repository') }} <code class="sv-code">sudo ./install.sh</code></span></p>
				<p v-else-if="stopped" class="sv-quiet" data-part="stopped">{{ tr('unit_stopped_text') }}</p>
				<p v-else-if="schemaProblem" class="sv-note" data-level="warn" role="note" data-part="schema"><span class="mdi mdi-alert-outline sv-ico" aria-hidden="true" /><span>{{ schemaProblem }}</span></p>
			</section>

			<template v-if="ready">
				<section class="sv-card" aria-labelledby="sv-lb-now" data-card="now">
					<div class="sv-card-head"><h2 id="sv-lb-now"><span class="mdi mdi-steering sv-ico" aria-hidden="true" />{{ tr('machine_control') }}</h2></div>
					<p v-if="!e.exclusive" class="sv-value" data-part="control"><span class="mdi mdi-account-multiple-outline sv-ico" aria-hidden="true" />{{ tr('shared') }} · {{ tr('non_exclusive_mode_every_connection_can') }}</p>
					<p v-else-if="e.owner" class="sv-value" data-part="control"><span class="mdi mdi-steering sv-ico" aria-hidden="true" />{{ e.owner }} · {{ ipOf(e.owner_id) }} · {{ tr('has_had_it_for_t_others_only_query', { t: dur(e.owner_since_s) }) }}</p>
					<p v-else class="sv-value" data-part="control"><span class="mdi mdi-steering-off sv-ico" aria-hidden="true" />{{ tr('free') }} · {{ tr('the_first_connection_that_sends_a') }}</p>
					<div v-if="e.exclusive && e.owner" class="sv-row-ctl"><button type="button" class="sv-btn" data-act="release" :disabled="!mayOrder || busy('release')" @click="order({ action: 'release' }, 'release')">{{ tr('release_control') }}</button></div>
					<div class="sv-stats" data-part="figures">
						<div class="sv-stat" data-stat="connected"><b>{{ e.clients.length }}<small v-if="sec"> / {{ sec.max_connections }}</small></b><span>{{ tr('connected_title') }} · {{ tr('n_since_it_started', { n: e.totals.connections }) }}</span></div>
						<div class="sv-stat" data-stat="orders"><b>{{ num(e.totals.orders) }}</b><span>{{ tr('commands_title') }} · {{ tr('n_queries', { n: num(e.totals.queries) }, e.totals.queries) }}</span></div>
						<div class="sv-stat" data-stat="rejected" :data-level="e.totals.rejects ? 'warn' : null"><b>{{ num(e.totals.rejects) }}</b><span>{{ tr('rejected_title') }}</span></div>
						<div class="sv-stat" data-stat="response" :data-level="(e.duet_ms_max || 0) > 2000 ? 'warn' : null"><b>{{ e.duet_ms_avg != null ? Math.round(e.duet_ms_avg) + ' ms' : '–' }}</b><span>{{ tr('machine_response') }} · {{ tr('max_n_ms_5_min', { n: Math.round(e.duet_ms_max || 0) }) }}</span></div>
						<div class="sv-stat" data-stat="traffic"><b>{{ bytes(e.totals.bytes_rx) }} ↓ {{ bytes(e.totals.bytes_tx) }} ↑</b><span>{{ tr('traffic') }}</span></div>
						<div class="sv-stat" data-stat="errors" :data-level="e.totals.duet_errors ? 'warn' : null"><b>{{ e.totals.duet_errors }}</b><span>{{ tr('errors_title') }} · {{ tr('n_kicked', { n: e.totals.kicked || 0 }, e.totals.kicked || 0) }}</span></div>
					</div>
					<div v-if="e.history" class="sv-chart" data-part="chart">
						<p class="sv-quiet">{{ tr('last_hour_per_minute') }} · {{ hourText }}</p>
						<svg :viewBox="'0 0 600 ' + GH" preserveAspectRatio="none" role="img" :aria-label="tr('last_hour_per_minute')"><g v-for="(b, i) in bars" :key="i"><title>{{ barTitle(b) }}</title><rect class="sv-bar-q" :x="i * 10 + 1" :y="GH - b.hc" width="8" :height="b.hc" /><rect class="sv-bar-o" :x="i * 10 + 1" :y="GH - b.hc - b.ho" width="8" :height="b.ho" /><rect v-if="b.r" class="sv-bar-r" :x="i * 10 + 1" y="0" width="8" height="3" /></g></svg>
					</div>
				</section>

				<details class="sv-fold" data-part="connections" open>
					<summary><span class="mdi mdi-chevron-right sv-ico sv-chev" aria-hidden="true" /><span class="sv-fold-name">{{ tr('connections_n', { n: e.clients.length }) }}</span></summary>
					<div class="sv-fold-body"><bridge-connections :host="host" /></div>
				</details>
				<details class="sv-fold" data-part="safety">
					<summary><span class="mdi mdi-chevron-right sv-ico sv-chev" aria-hidden="true" /><span class="sv-fold-name">{{ tr('security_and_key') }}</span><span v-if="sec" class="sv-fold-sum">{{ tr(sec.local_only ? 'local_network' : 'chosen_ips') }} · {{ tr(sec.password ? 'with_key' : 'no_key') }}</span></summary>
					<div class="sv-fold-body"><bridge-safety v-if="sec" /></div>
				</details>
				<details class="sv-fold" data-part="settings" @toggle="e2 => e2.target.open && $refs.settings && $refs.settings.open()">
					<summary><span class="mdi mdi-chevron-right sv-ico sv-chev" aria-hidden="true" /><span class="sv-fold-name">{{ tr('configuration') }}</span></summary>
					<div class="sv-fold-body"><bridge-settings ref="settings" /></div>
				</details>
				<bridge-tools />
			</template>
		</sv-zone>
		<bridge-contract :open="contractOpen" :stopped="stopped" @close="contractOpen = false" />
	</div>
</template>

<script>
import { bridge, readState, watchBridge } from '../../core/store/bridge.js'
import { unitSwitch } from '../../core/actions/bridge.js'
import { machineStatus } from '../../core/dwc.js'
import { want } from '../../core/store/session.js'
import { rowsMixin } from '../../core/rows-mixin.js'
import * as contract from '../../bridge-contract.js'
import { parsePortError } from '../../bridge-port.js'
import { CHART_HEIGHT, READ_FAILS, bytes, chartBars, dur, hourTotals, inUseReason, ipOf, num } from '../../bridge-view.js'
import SvActionRow from '../../ui/SvActionRow.vue'
import SvHelp from '../../ui/SvHelp.vue'
import SvReason from '../../ui/SvReason.vue'
import SvSwitch from '../../ui/SvSwitch.vue'
import SvVerdict from '../../ui/SvVerdict.vue'
import SvZone from '../../ui/SvZone.vue'
import { timeNow } from '../../core/clock.js'
import BridgeConnections from './BridgeConnections.vue'
import BridgeContract from './BridgeContract.vue'
import BridgeSafety from './BridgeSafety.vue'
import BridgeSettings from './BridgeSettings.vue'
import BridgeTools from './BridgeTools.vue'
import { bridgeOrders, tr } from './bridge-orders.js'

export default {
	name: 'BridgeTab',
	components: { BridgeConnections, BridgeContract, BridgeSafety, BridgeSettings, BridgeTools, SvActionRow, SvHelp, SvReason, SvSwitch, SvVerdict, SvZone },
	mixins: [rowsMixin, bridgeOrders],
	props: { active: { type: Boolean, default: false } },
	data() {
		return { unitSwitch, contractOpen: false, GH: CHART_HEIGHT }
	},
	computed: {
		e() {
			return this.bridge.e
		},
		status() {
			return this.bridge.status
		},
		unit() {
			return this.bridge.unit
		},
		sec() {
			return this.e && this.e.security
		},
		host() {
			return typeof window !== 'undefined' ? window.location.hostname : ''
		},
		stopped() {
			return !!(this.unit && this.unit.installed && !this.unit.active)
		},
		read() {
			return contract.parse(this.e, this.bridge.received ? (timeNow() - this.bridge.received) / 1000 : null)
		},
		schemaUnknown() {
			return !!(this.e && this.e.schema) && this.read.status === 'incompatible'
		},
		// why what the file holds cannot be drawn: an unknown format, or a bridge older than the file
		schemaProblem() {
			if (!this.e || this.stopped) return ''
			if (this.schemaUnknown) return tr('schema_unknown', { s: String(this.e.schema), v: this.e.version || '?' })
			if (!this.e.schema) return tr('bridge_running_is_version_v', { v: this.e.version })
			return ''
		},
		ready() {
			return !!this.e && !this.stopped && !this.schemaProblem && this.status !== 'missing'
		},
		portError() {
			return this.e && this.e.error ? parsePortError(this.e.error) : null
		},
		errorText() {
			if (!this.portError) return this.e && this.e.error
			return tr('port_err_' + this.portError.kind, { port: this.portError.port, detail: this.portError.detail })
		},
		zone() {
			if (this.status === 'unreadable' && !this.e) return 'error'
			return this.status === 'loading' && !this.e ? 'loading' : 'ready'
		},
		problem() {
			return this.status === 'unreadable' ? { message: tr('state_unreadable', { x: this.bridge.readCause }), code: '' } : null
		},
		mayOrder() {
			return this.perm('bridge.service.set').state === 'ok'
		},
		level() {
			if (this.status === 'missing' || this.stopped) return 'warn'
			if (this.portError) return 'error'
			return this.ready && contract.alive(this.read, contract.FRESH_S) ? 'ok' : 'warn'
		},
		stateText() {
			if (this.status === 'missing') return tr('not_installed')
			if (this.stopped) return tr('stopped_chip')
			if (!this.e) return tr('reading_chip')
			if (this.portError) return tr('port_error')
			return contract.alive(this.read, contract.FRESH_S) ? tr('up_to_date') : this.t('common.no_data_2')
		},
		facts() {
			const e = this.e
			if (!e || this.stopped || !this.ready) return []
			const out = ['v' + e.version + ' · ' + tr('up_for_t', { t: dur(e.uptime_s) })]
			if (this.sec) out.push(tr(this.sec.local_only ? 'local_network' : 'chosen_ips') + ' · ' + tr(this.sec.password ? 'with_key' : 'no_key'))
			const kind = contract.contractKind(this.read)
			const n = this.read.contract
			if (kind) out.push(tr(kind === 'newer' ? 'contract_chip_newer' : kind === 'old' ? 'contract_chip_old' : 'contract_chip_ok', { n }))
			if (e.activity) out.push(tr('live_job') + ': ' + (e.activity.live_job && e.activity.live_job.active ? tr('active') + (e.activity.live_job.name ? ' (' + e.activity.live_job.name + ')' : '') : tr('none_f')))
			return out
		},
		inUse() {
			const why = inUseReason(this.e, machineStatus())
			return why ? tr('in_use_' + why) : ''
		},
		unitDesc() {
			const u = this.unit
			return u.active ? tr(u.enabled ? 'unit_on_enabled' : 'unit_on_not_enabled') : tr('unit_off')
		},
		unitError() {
			const e = this.unitSwitch.state === 'error' && this.unitSwitch.error
			if (!e || e.kind === 'session' || e.kind === 'role') return ''
			return e.reason === 'live_job' ? tr('unit_live_job') : e.reason === 'no_permission' ? tr('unit_no_permission') : tr('unit_failed', { x: e.message })
		},
		bars() {
			return chartBars(this.e.history, this.GH)
		},
		hourText() {
			const s = hourTotals(this.e.history)
			return tr('hour_summary', { o: tr('n_orders', { n: s[0] }, s[0]), q: tr('n_queries', { n: s[1] }, s[1]), r: tr('n_rejections', { n: s[2] }, s[2]) })
		}
	},
	watch: {
		active: { immediate: true, handler(on) { if (on) this.begin(); else this.end() } }
	},
	beforeDestroy() {
		this.end()
	},
	methods: {
		dur,
		num,
		bytes,
		ipOf,
		begin() {
			want(['bridge.service', 'bridge.service.set'])
			this.stop = watchBridge()
		},
		end() {
			if (this.stop) { this.stop(); this.stop = null }
			this.disarm()
		},
		readState,
		toggleUnit() {
			if (!this.unit) return
			this.unitSwitch.run({ on: !this.unit.active })
		},
		restart() {
			if (this.inUse) return
			if (this.touch('restart')) this.order({ action: 'restart' }, 'restart')
		},
		barTitle(b) {
			return tr('bar_title', { m: b.minutes, o: tr('n_orders', { n: b.orders }, b.orders), q: tr('n_queries', { n: b.queries }, b.queries) }) + (b.rejections ? tr('bar_rejections', { n: b.rejections }, b.rejections) : '') + (b.connections ? tr('bar_connections', { n: b.connections }, b.connections) : '')
		}
	}
}
</script>
