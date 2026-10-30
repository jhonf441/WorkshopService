<template>
	<v-card outlined class="mb-3 svc-caja-card">
		<v-card-title class="flex-wrap" style="gap:4px">
			<v-icon small color="warning" class="mr-2">mdi-power-plug-off-outline</v-icon>{{ $t(T + 'box_title') }}
			<v-spacer />
			<v-btn small text color="primary" :loading="lowering" @click="$emit('download')">
				<v-icon small left>mdi-download</v-icon>{{ $t('plugins.WorkshopService.common.download') }}
			</v-btn>
			<v-btn small text :disabled="sending" @click="$emit('hide')">
				<v-icon small left>mdi-eye-off</v-icon>{{ $t(T + 'hide') }}
			</v-btn>
		</v-card-title>
		<v-card-text>
			<!-- cuando: ultimo dato y cuanto llevaba encendida -->
			<div class="text-body-2 mb-2">
				{{ $t(T + 'box_when_intro') }}
				<b>{{ when }}</b><span v-if="a.last"> &middot; {{ $t(T + 'box_was_on_for', { t: duration(a.last.up) }) }}</span>.
				<span v-if="report.detected" class="grey--text">{{ $t(T + 'detected_x', { x: report.detected }) }}.</span>
			</div>

			<!-- how things are NOW: the card reports something that already happened, and says so -->
			<v-alert dense text type="success" icon="mdi-check-circle-outline" class="mb-3">
				<div class="font-weight-medium">{{ $t(T + 'box_now_t') }}</div>
				<div class="text-caption">{{ $t(T + 'box_now_d') }}</div>
				<div class="text-caption mt-1">{{ $t(T + 'box_now_hide') }}</div>
			</v-alert>

			<!-- what the last minutes say (an estimate, written as such) -->
			<v-alert dense text :type="alert.kind" :icon="alert.icon" class="mb-3">
				<div class="font-weight-medium">{{ $t(T + 'box_v_' + a.verdict + '_t') }}</div>
				<div class="text-caption">{{ $t(T + 'box_v_' + a.verdict + '_d', dataVerdict) }}</div>
				<div v-if="a.inJob" class="text-caption mt-1"><v-icon x-small class="mr-1">mdi-alert-outline</v-icon>{{ $t(T + 'box_in_job') }}</div>
			</v-alert>

			<!-- what to do according to the verdict: concrete steps -->
			<div v-if="steps.length" class="mb-3 svc-box-steps">
				<div class="text-subtitle-2 mb-1">{{ $t(T + 'box_todo') }}</div>
				<ol class="text-body-2 pl-5">
					<li v-for="p in steps" :key="p">{{ p }}</li>
				</ol>
			</div>

			<!-- the last minutes, one chart per thing -->
			<div v-if="a.samples.length > 1" class="text-caption grey--text mb-1">{{ $t(T + 'box_charts_note') }}</div>
			<v-row v-if="a.samples.length > 1" dense class="mb-1">
				<v-col cols="12" sm="6" md="3"><spark :values="serial('cpu')" :title="$t(T + 'box_cpu')" unit="%" color="#42A5F5" :decimals="0" /></v-col>
				<v-col cols="12" sm="6" md="3"><spark :values="serial('ram')" :title="$t(T + 'box_ram')" unit="%" color="#AB47BC" :decimals="0" /></v-col>
				<v-col cols="12" sm="6" md="3"><spark :values="serial('temp')" :title="$t(T + 'box_temp')" unit="°C" :color="a.temp.max >= 75 ? '#EF5350' : '#FFA726'" /></v-col>
				<v-col cols="12" sm="6" md="3"><spark :values="a.samples.map(m => m.load[0])" :title="$t(T + 'box_load')" unit="" color="#66BB6A" :decimals="2" /></v-col>
			</v-row>

			<!-- what was happening at the last reading -->
			<div v-if="a.last" class="d-flex flex-wrap align-center mb-2" style="gap:6px">
				<v-chip small outlined><v-icon x-small left>mdi-cog-outline</v-icon>{{ $t(T + 'box_machine') }}: {{ stateMachine(a.last.machine) }}</v-chip>
				<v-chip small outlined :color="a.last.dsf >= 3 ? 'warning' : undefined"><v-icon x-small left>mdi-timer-sand</v-icon>{{ $t(T + 'box_dsf') }}: {{ a.last.dsf }} s</v-chip>
				<v-chip v-for="b in a.last.locks" :key="'b' + b.name" small outlined color="warning">
					<v-icon x-small left>mdi-lock-clock</v-icon>{{ $t(T + 'box_lock', { n: b.name, t: duration(b.s) }) }}
				</v-chip>
				<v-chip v-for="l in a.last.slow" :key="'l' + l.name" small outlined color="warning">
					<v-icon x-small left>mdi-tortoise</v-icon>{{ $t(T + 'box_slow', { n: l.name, t: duration(l.s) }) }}
				</v-chip>
			</div>

			<!-- the lines as they are, for whoever wants to read them -->
			<v-expansion-panels flat accordion class="svc-box-lines">
				<v-expansion-panel>
					<v-expansion-panel-header class="px-0 py-0 text-caption" style="min-height:36px">
						{{ $t(T + 'box_raw', { n: (report.lines || []).length, s: interval || 5 }) }}
					</v-expansion-panel-header>
					<v-expansion-panel-content>
						<pre class="svc-box">{{ (report.lines || []).join('\n') }}</pre>
					</v-expansion-panel-content>
				</v-expansion-panel>
			</v-expansion-panels>
			<div v-if="msg" class="text-caption mt-1">{{ msg }}</div>
		</v-card-text>
	</v-card>
</template>

<script>
'use strict'

import Spark from './Spark.vue'
import { analyzeBox, dateOf } from './black-box.js'
import { duration } from './format.js'

// Card of the last unclean shutdown (black box, dsf/box_black.py): says what happened in a few words, draws the last minutes and keeps the
// raw lines one tap away. The numbers come from black-box.js (pure, tested); the words are here and in i18n (servicePage.caja_*).
export default {
	name: 'BlackBoxCard',
	components: { Spark },
	props: {
		report: { type: Object, required: true },
		interval: { type: Number, default: 5 },
		lowering: { type: Boolean, default: false },
		sending: { type: Boolean, default: false },
		msg: { type: String, default: '' }
	},
	data() {
		return { T: 'plugins.WorkshopService.servicePage.' }
	},
	computed: {
		a() {
			return analyzeBox(this.report.lines || [])
		},
		when() {
			const d = dateOf(this.report.last_datum)
			if (!d) return this.report.last_datum || '?'
			return d.toLocaleString(this.$i18n.locale, { day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit', second: '2-digit' })
		},
		alert() {
			const v = this.a.verdict
			if (v === 'calm') return { kind: 'info', icon: 'mdi-flash-off' }
			if (v === 'without_data') return { kind: 'info', icon: 'mdi-help-circle-outline' }
			if (v === 'stuck') return { kind: 'warning', icon: 'mdi-lock-clock' }
			return { kind: 'warning', icon: v === 'heat' ? 'mdi-thermometer-alert' : v === 'memory' ? 'mdi-memory' : 'mdi-gauge-full' }
		},
		steps() {
			const out = []
			for (let i = 1; i <= 6; i++) {
				const k = this.T + 'box_v_' + this.a.verdict + '_s' + i
				if (this.$te(k)) out.push(this.$t(k))
			}
			return out
		},
		thingStuck() {
			const u = this.a.last
			if (!u) return '?'
			const x = u.locks.concat(u.slow).sort((p, q) => q.s - p.s)[0]
			return x ? x.name + ' (' + Math.round(x.s / 60 * 10) / 10 + ' min)' : '?'
		},
		dataVerdict() {
			const a = this.a
			const f = v => (v == null ? '?' : Math.round(v * 10) / 10)
			return { cpu: f(a.cpu.max), ram: f(a.ram.max), temp: f(a.temp.max), thing: this.thingStuck, min: Math.round(a.samples.length * (this.interval || 5) / 60 * 10) / 10 }
		}
	},
	methods: {
		duration: duration,
		serial(k) {
			return this.a.samples.map(m => m[k])
		},
		stateMachine(s) {
			const key = this.T + 'box_m_' + s
			return this.$te(key) ? this.$t(key) : s
		}
	}
}
</script>

<style scoped>
.svc-box {
	font-family: ui-monospace, 'Cascadia Mono', 'DejaVu Sans Mono', Consolas, Menlo, monospace;
	font-size: 12px;
	line-height: 1.5;
	max-height: 260px;
	overflow: auto;
	white-space: pre;
	padding: 10px 12px;
	margin: 0;
	border-radius: 8px;
	border: 1px solid rgba(128, 128, 128, 0.25);
	background: rgba(0, 0, 0, 0.25);
	color: rgba(255, 255, 255, 0.8);
	tab-size: 4;
	/* thin dark scrollbars (the browser default is a thick light bar that looks out of place on the dark theme) */
	scrollbar-width: thin;
	scrollbar-color: rgba(255, 255, 255, 0.3) transparent;
}
.theme--light .svc-box {
	background: rgba(0, 0, 0, 0.04);
	color: rgba(0, 0, 0, 0.8);
	scrollbar-color: rgba(0, 0, 0, 0.35) transparent;
}
.svc-box::-webkit-scrollbar {
	width: 8px;
	height: 8px;
}
.svc-box::-webkit-scrollbar-track {
	background: transparent;
}
.svc-box::-webkit-scrollbar-thumb {
	background: rgba(255, 255, 255, 0.3);
	border-radius: 4px;
}
.svc-box::-webkit-scrollbar-thumb:hover {
	background: rgba(255, 255, 255, 0.5);
}
.theme--light .svc-box::-webkit-scrollbar-thumb {
	background: rgba(0, 0, 0, 0.3);
}
.svc-box-steps ol {
	margin: 0;
}
.svc-box-steps li {
	margin-bottom: 4px;
}
.svc-box-lines >>> .v-expansion-panel-content__wrap {
	padding: 0 0 8px 0;
}
.svc-box-lines >>> .v-expansion-panel {
	background: transparent;
}
</style>
