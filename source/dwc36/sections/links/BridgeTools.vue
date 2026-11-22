<template>
	<!-- Bridge > what it did and how to talk to it: the events it keeps (filtered by kind), the commands it understands with a way to try each one,
	     and the debug lines (off by itself after a while). -->
	<div class="sv-bridge-tools">
		<details class="sv-fold" data-part="activity">
			<summary><span class="mdi mdi-chevron-right sv-ico sv-chev" aria-hidden="true" /><span class="sv-fold-name">{{ t('common.activity') }}</span><span class="sv-fold-sum">{{ tc('links.bridge_events', events.length, { n: events.length }) }}</span></summary>
			<div class="sv-fold-body">
				<span class="sv-seg" role="group" :aria-label="t('links.bridge_kind_label')">
					<button v-for="k in kinds" :key="k.id" type="button" :aria-pressed="filter === k.id ? 'true' : 'false'" :data-kind="k.id" @click="filter = filter === k.id ? '' : k.id">{{ tr(k.name) }} {{ count(k.id) }}</button>
				</span>
				<ul class="sv-rows" data-part="events">
					<li v-for="(ev, i) in shown" :key="i" class="sv-row" :data-event="ev.type || 'info'"><div class="sv-row-main"><div><div class="sv-row-name">{{ ev.time }} · {{ eventText(ev) }}</div></div></div></li>
				</ul>
				<p v-if="!shown.length" class="sv-quiet" data-part="no-events">{{ tr('no_events') }}</p>
			</div>
		</details>

		<details class="sv-fold" data-part="commands">
			<summary><span class="mdi mdi-chevron-right sv-ico sv-chev" aria-hidden="true" /><span class="sv-fold-name">{{ tr('commands_tab') }}</span></summary>
			<div class="sv-fold-body">
				<div class="sv-note" data-level="info" role="note"><span class="mdi mdi-information-outline sv-ico" aria-hidden="true" /><span><b>{{ tr('paste_in_program_title') }}</b> {{ tr('paste_in_program_help') }}
					<span v-for="g in gcodes" :key="g.k" class="sv-code-line"><br>{{ tr(g.k) }}: <code class="sv-code">{{ g.v }}</code> <sv-copy-button kind="program" :done="copied === g.v" @copy="copy(g.v)" /></span><br>{{ tr('paste_in_program_note') }}</span></div>
				<p class="sv-quiet">{{ tr('they_are_typed_in_the_same') }} <b>{{ e.port }}</b>{{ tr('and_do_not_reach_the_duet') }} {{ tr('tap_a_command_to_copy_it') }}</p>
				<ul class="sv-rows">
					<li v-for="c in commands" :key="c.cmd" class="sv-row" :data-command="c.cmd">
						<div class="sv-row-main"><div><div class="sv-row-name"><code class="sv-code">{{ c.cmd }}</code> <sv-copy-button kind="command" :label="c.cmd" :done="copied === c.cmd" @copy="copy(c.cmd)" /></div><div class="sv-row-desc">{{ c.desc }}<template v-if="!c.test"> · <span :title="c.because">{{ tr('only_from_your_program') }}</span></template></div></div></div>
						<div v-if="c.test" class="sv-row-ctl">
							<label class="sv-field"><span class="sv-vh">{{ tr('sends') }}</span><input :value="field(c)" type="text" :aria-label="tr('sends')" @input="fields[c.cmd] = $event.target.value" @keyup.enter="test(c)"></label>
							<button type="button" class="wf-btn sv-btn" data-act="test" :disabled="tests[c.cmd] && tests[c.cmd].sending" @click="test(c)">{{ tr('test') }}</button>
						</div>
						<div v-if="tests[c.cmd] && tests[c.cmd].text" class="sv-row-out" :data-kind="tests[c.cmd].ok ? 'done' : 'error'" :role="tests[c.cmd].ok ? 'status' : 'alert'" data-part="test-result"><span>{{ tests[c.cmd].hour }}<template v-if="tests[c.cmd].ms != null"> · {{ tests[c.cmd].ms }} ms</template> · {{ tr('sent') }} <code class="sv-code">{{ tests[c.cmd].sent }}</code> {{ tr('bridge_response') }}</span></div>
						<pre v-if="tests[c.cmd] && tests[c.cmd].text" class="sv-diff">{{ tests[c.cmd].text }}</pre>
					</li>
				</ul>
				<p class="sv-quiet">{{ tr('test_opens_a_short_connection') }} {{ tr('queries_only_the_bridge_commands_above') }}</p>
			</div>
		</details>

		<details class="sv-fold" data-part="debug" @toggle="e2 => onDebug(e2.target.open)">
			<summary><span class="mdi mdi-chevron-right sv-ico sv-chev" aria-hidden="true" /><span class="sv-fold-name">{{ tr('debug') }}</span><span class="sv-fold-sum">{{ dbg && dbg.active ? tr('on_turns_off_in') + dur(dbg.remaining_s) : tr('off') }}</span></summary>
			<div class="sv-fold-body">
				<!-- the state first: ONE switch (it IS the control) with its colour and its words; the actions only make sense while it is on -->
				<div class="sv-dbg-head" data-part="debug-head">
					<sv-switch :checked="isOn" :word="stateWord" :label="tr('debug')" :state="paused && isOn ? 'armed' : ''" :disabled="!mayOrder || busy('debug')" data-part="debug-switch" @toggle="order({ action: 'debug', on: !isOn }, 'debug')" />
					<span class="sv-chip-sm sv-dbg-count" data-part="count">{{ tr('n_lines', { n: lines.length }, lines.length) }}</span>
				</div>
				<div class="sv-dbg-tools" role="group" :aria-label="tr('debug')">
					<button type="button" class="wf-btn sv-btn" data-act="debug_extend" :disabled="!isOn || !mayOrder || busy('debug_extend')" @click="order({ action: 'debug_extend' }, 'debug_extend')"><span class="mdi mdi-timer-plus-outline sv-ico sv-ico-s" aria-hidden="true" />{{ tr('debug_extend') }}</button>
					<button type="button" class="wf-btn sv-btn" data-act="pause" :disabled="!isOn" :aria-pressed="paused ? 'true' : 'false'" @click="paused = !paused"><span class="mdi sv-ico sv-ico-s" :class="paused ? 'mdi-play' : 'mdi-pause'" aria-hidden="true" />{{ t(paused ? 'common.follow' : 'common.pause') }}</button>
					<button type="button" class="wf-btn sv-btn" data-act="clear" :disabled="!isOn && !lines.length" @click="clear"><span class="mdi mdi-broom sv-ico sv-ico-s" aria-hidden="true" />{{ tr('clear') }}</button>
					<span class="sv-dbg-sep" aria-hidden="true" />
					<sv-copy-button kind="debug" :done="copiedLines" @copy="copyLines" />
					<sv-select v-model="client" :options="clientOptions" :aria-label="tr('debug_client')" :disabled="!isOn" />
				</div>
				<pre class="sv-diff" data-part="lines"><span v-for="l in lines" :key="l.id" :class="'d-' + (l.k === 'err' ? 'del' : 'same')">{{ l.t }} {{ l.c }} {{ l.k }} {{ l.x }}
</span></pre>
				<p v-if="!lines.length" class="sv-quiet" data-part="empty">{{ tr(isOn ? 'waiting_for_lines' : 'no_lines_turn_debug_on_to') }}</p>
			</div>
		</details>
	</div>
</template>

<script>
import { call } from '../../core/api/call.js'
import { bridge } from '../../core/store/bridge.js'
import { rowsMixin } from '../../core/rows-mixin.js'
import { every, timeNow } from '../../core/clock.js'
import { writeJson } from '../../core/api/files.js'
import { copyText } from '../../copy.js'
import { VIEWER_FILE } from '../../bridge-io.js'
import { debugClients, debugCopyText, debugVisible, dur } from '../../bridge-view.js'
import * as words from '../../bridge-texts.js'
import SvCopyButton from '../../ui/SvCopyButton.vue'
import SvSwitch from '../../ui/SvSwitch.vue'
import SvSelect from '../../ui/SvSelect.vue'
import { bridgeOrders, tr } from './bridge-orders.js'

export default {
	name: 'BridgeTools',
	components: { SvCopyButton, SvSelect, SvSwitch },
	mixins: [rowsMixin, bridgeOrders],
	data() {
		return { filter: '', copied: '', copiedLines: false, fields: {}, tests: {}, paused: false, client: '', since: 0, views: [], debugOpen: false }
	},
	computed: {
		e() {
			return bridge.e
		},
		events() {
			return (this.e && this.e.events) || []
		},
		shown() {
			return this.filter ? this.events.filter(x => (x.type || 'info') === this.filter) : this.events
		},
		kinds() {
			return words.KINDS
		},
		commands() {
			return words.COMMANDS.map(c => ({ cmd: c.cmd, desc: tr(c.desc), test: c.test, because: c.because ? tr(c.because) : '' }))
		},
		gcodes() {
			return words.PROGRAM_GCODES
		},
		mayOrder() {
			return this.perm('bridge.service.set').state === 'ok'
		},
		dbg() {
			return this.e && this.e.debug
		},
		isOn() {
			return !!(this.dbg && this.dbg.active)
		},
		// "Active - turns itself off in 30 min" (counted as text, no blinking), "Paused" (amber) or "Off" (grey)
		stateWord() {
			if (!this.isOn) return this.t('links.debug_state_off')
			return this.paused ? this.t('links.debug_state_paused') : this.t('links.debug_state_on', { t: dur(this.dbg.remaining_s) })
		},
		lines() {
			return debugVisible(this.views, this.since, this.client)
		},
		clientOptions() {
			return [{ value: '', label: this.tr('all_clients') }].concat(this.clientNames.map(n => ({ value: n, label: n })))
		},
		clientNames() {
			return debugClients(this.views, this.client)
		}
	},
	watch: {
		// what the bridge keeps in memory, the last 300 lines, unless it is paused
		'bridge.e'(e) {
			if (!this.paused && e && e.debug) this.views = (e.debug.lines || []).slice(-300)
		}
	},
	beforeDestroy() {
		this.onDebug(false)
	},
	methods: {
		dur,
		eventText(ev) {
			return words.eventText(ev, tr)
		},
		count(id) {
			return this.events.filter(x => (x.type || 'info') === id).length
		},
		field(c) {
			return this.fields[c.cmd] != null ? this.fields[c.cmd] : c.cmd
		},
		async copy(text) {
			if (!(await copyText(text))) return
			this.copied = text
			setTimeout(() => { if (this.copied === text) this.copied = '' }, 1500)
		},
		// while the lines are on screen the bridge is told every 10 s that somebody looks (it turns the debug off by itself when nobody does)
		onDebug(open) {
			this.debugOpen = open
			if (this.offBeat) { this.offBeat(); this.offBeat = null }
			if (!open) return
			let last = 0
			this.offBeat = every(2, () => {
				if (!this.dbg || !this.dbg.active || timeNow() - last < 10000) return
				last = timeNow()
				writeJson(VIEWER_FILE, { viewer: 'page', at: new Date().toISOString() }).catch(() => {})
			})
		},
		clear() {
			this.since = Math.max(this.since, (this.dbg && this.dbg.last_id) || 0)
		},
		async copyLines() {
			this.copiedLines = await copyText(debugCopyText(this.lines))
			if (this.copiedLines) setTimeout(() => { this.copiedLines = false }, 1500)
		},
		async test(c) {
			const line = String(this.field(c)).replace(/"/g, "'").trim()
			const hour = new Date().toTimeString().slice(0, 8)
			this.$set(this.tests, c.cmd, { sending: true })
			try {
				const r = await call('bridge.test', { line })
				const d = r.data || {}
				this.$set(this.tests, c.cmd, d.error ? { ok: false, text: d.error, hour, sent: line } : { ok: true, text: d.response || this.t('common.no_response'), ms: d.ms, hour, sent: line })
			} catch (e) {
				this.$set(this.tests, c.cmd, { ok: false, text: tr('could_not_test_x', { x: e.message }) + tr('needs_updated_workshopservice'), hour, sent: line })
			}
		}
	}
}
</script>
