<template>
	<div class="svc-proc">
		<div class="d-flex align-center flex-wrap">
			<v-icon class="mr-3 svx-ico">{{ p.info.icon }}</v-icon>
			<div class="svc-proc-txt">
				<div class="font-weight-medium">
					{{ p.title }}
					<v-chip x-small label outlined :color="p.info.color" class="ml-1">{{ p.info.cat }}</v-chip>
				</div>
				<div class="text-caption grey--text">{{ p.description }}</div>
				<div v-if="p.detail" class="text-caption svc-detail"><v-icon x-small class="mr-1">mdi-information-outline</v-icon>{{ p.detail }}</div>
			</div>
			<v-spacer />
			<v-chip small label dark :color="p.state.color" :title="p.state.detail">
				<v-icon left x-small>{{ p.state.icon }}</v-icon>{{ p.state.text }}
			</v-chip>
		</div>

		<!-- when it runs: automatic (a plugin that needs it is enabled), always or never -->
		<div v-if="p.module" class="ml-10 mt-2 d-flex align-center flex-wrap svc-modo" style="gap:8px">
			<span class="text-caption grey--text" :title="$t('plugins.WorkshopService.servicePage.mode_help')">{{ $t('plugins.WorkshopService.servicePage.mode_label') }}</span>
			<v-btn-toggle :value="p.module.mode" mandatory dense class="svc-mode-buttons" @change="v => $emit('mode', v)">
				<v-btn v-for="m in ['auto', 'on', 'off']" :key="m" :value="m" x-small>{{ $t('plugins.WorkshopService.servicePage.mode_' + m) }}</v-btn>
			</v-btn-toggle>
			<span class="text-caption grey--text">{{ reason }}</span>
			<span v-if="p.modeError" class="text-caption svc-err">{{ p.modeError }}</span>
		</div>

		<div class="text-caption ml-10 mt-1">
			<span v-if="p.age_ok_s != null" class="grey--text">{{ $t('plugins.WorkshopService.servicePage.last_heartbeat_t', { t: age(p.age_ok_s) }) }}</span>
			<span class="svc-metricas grey--text">
				<span v-if="p.cpu_pct != null" :title="$t('plugins.WorkshopService.servicePage.cpu_used_by_this_thread')">CPU {{ p.cpu_pct }}%</span>
				<span v-if="p.active_s != null" :title="$t('plugins.WorkshopService.servicePage.since_this_process_last_started')">{{ $t('plugins.WorkshopService.servicePage.active_for_t', { t: duration(p.active_s) }) }}</span>
				<span v-if="p.cycles" :title="$t('plugins.WorkshopService.servicePage.loops_completed_since_the_service_started')">{{ $t('plugins.WorkshopService.servicePage.n_loops', { n: p.cycles }) }}</span>
				<span v-if="p.errors_total" class="warning--text" :title="$t('plugins.WorkshopService.servicePage.errors_since_the_service_started')">{{ $t('plugins.WorkshopService.servicePage.n_errors', { n: p.errors_total }) }}</span>
			</span>
			<v-chip v-if="p.restarts" x-small label color="orange darken-2" dark class="ml-2">
				<v-icon left x-small>mdi-restart</v-icon>{{ $t('plugins.WorkshopService.servicePage.relaunched_n', { n: p.restarts }) }}
			</v-chip>
		</div>

		<!-- heartbeat pace: average interval against the expected one -->
		<div v-if="step" class="ml-10 mt-2 svc-paso" :title="$t('plugins.WorkshopService.procDocs.ui_cadence_help')">
			<div class="d-flex text-caption" style="gap:8px">
				<span class="grey--text">{{ $t('plugins.WorkshopService.procDocs.ui_cadence') }}</span>
				<v-spacer />
				<span class="grey--text">{{ $t('plugins.WorkshopService.servicePage.every_t', { t: sec(p.interval_avg) }) }}<template v-if="p.interval_max != null"> &middot; {{ $t('plugins.WorkshopService.servicePage.max_t', { t: sec(p.interval_max) }) }}</template></span>
				<span class="grey--text">{{ $t('plugins.WorkshopService.procDocs.ui_expected', { t: sec(p.expected_s) }) }}</span>
				<b :class="step.color + '--text'">{{ step.pct }} %</b>
			</div>
			<v-progress-linear :value="Math.min(100, step.pct / 2)" height="5" rounded :color="step.color" background-color="grey darken-3" class="mt-1" />
		</div>

		<div v-if="p.error && p.errorRecent" class="text-caption ml-10 mt-1 svc-err">
			<v-icon x-small color="error">mdi-alert-circle</v-icon>
			{{ p.error_hour }}: {{ p.error }}
		</div>

		<div v-if="hasDocs || hist" class="ml-10 mt-1">
			<a href="#" class="text-caption" @click.prevent="open = !open">
				<v-icon x-small color="primary">{{ open ? 'mdi-chevron-up' : 'mdi-chevron-down' }}</v-icon>
				{{ open ? $t('plugins.WorkshopService.procDocs.ui_less') : $t('plugins.WorkshopService.procDocs.ui_more') }}
			</a>
		</div>

		<div v-if="open" class="ml-10 mt-2 svc-doc">
			<div v-if="hasDocs" class="svc-doc-list">
				<div v-for="d in docs" :key="d.k" class="svc-doc-row">
					<div class="svc-doc-k">{{ d.k }}</div>
					<div class="svc-doc-v">{{ d.v }}</div>
				</div>
			</div>
			<div v-if="hist" class="svc-doc-chart mt-2">
				<spark :values="hist.cpu" :title="$t('plugins.WorkshopService.procDocs.ui_cpu_hist')" unit="%" :color="p.info.color" />
				<spark :values="hist.interval" :title="$t('plugins.WorkshopService.procDocs.ui_int_hist')" unit="s" :decimals="2" :color="p.info.color" />
			</div>
			<div v-if="p.error" class="text-caption svc-err mt-2">
				<b>{{ $t('plugins.WorkshopService.procDocs.ui_last_error') }}</b> &middot; {{ p.error_hour }}: {{ p.error }}
			</div>
		</div>
	</div>
</template>

<script>
'use strict'

import Spark from './Spark.vue'
import { sec, duration, age, rhythm } from './format.js'

import { pluginActive } from './workshop-ids.js'

const D = 'plugins.WorkshopService.procDocs.'
// the plugin whose page or panel each process serves: the "where" line names it only when that plugin is there
const PLUGIN_OF = { status_light: 'lights', consumption: 'consumption', motors: 'motors', jog: 'jog', health: 'health', events: 'activity', jobs: 'activity' }

// One internal process of the service: what the backend publishes about it (state, heartbeat,
// pace, CPU, loops, errors, relaunches) and, unfolded, what it is, what it is for, what happens if
// it stops, what it relies on and where it is adjusted, plus the history of its last minutes.
export default {
	name: 'ProcessRow',
	components: { Spark },
	props: {
		p: { type: Object, required: true },
		hist: { type: Object, default: null },
		openInitial: { type: Boolean, default: false }
	},
	data() {
		return { open: this.openInitial }
	},
	computed: {
		step() {
			return rhythm(this.p)
		},
		docs() {
			const out = []
			const add = (key, sufijo) => {
				const k = D + this.p.id + '_' + sufijo
				if (sufijo === 'where' && PLUGIN_OF[this.p.id] && !pluginActive(this.$store, PLUGIN_OF[this.p.id])) return
				if (this.$te(k)) out.push({ k: this.$t(D + key), v: this.$t(k) })
			}
			add('ui_what', 'what')
			add('ui_why', 'why')
			add('ui_fails', 'fails')
			add('ui_uses', 'uses')
			add('ui_where', 'where')
			return out
		},
		reason() {
			const r = (this.p.module || {}).reason || {};
			const k = 'plugins.WorkshopService.servicePage.why_' + r.code;
			return this.$te(k) ? this.$t(k, { p: (r.plugins || []).join(', ') }) : '';
		},
		hasDocs() {
			return this.docs.length > 0
		}
	},
	methods: { sec: sec, duration: duration, age: age }
};
</script>

<style scoped>
.svc-proc {
	padding: 10px 0;
	border-top: 1px solid var(--wf-line);
}
.svc-proc-txt {
	min-width: 0;
	flex: 1 1 200px;
}
.svc-detail {
	margin-top: 2px;
	opacity: 0.8;
}
.svc-metricas span {
	margin-left: 10px;
	white-space: nowrap;
}
.svc-err {
	word-break: break-word;
	color: var(--tp-red-bright, #ef9a9a);
}
.svc-doc {
	border-top: 1px solid var(--wf-line);
	padding-top: 8px;
}
.svc-doc-row {
	display: flex;
	gap: 10px;
	padding: 3px 0;
	font-size: 12px;
	line-height: 1.4;
}
.svc-doc-k {
	flex: 0 0 118px;
	color: var(--tp-faint, #9e9e9e);
}
.svc-doc-v {
	flex: 1 1 auto;
	min-width: 0;
	word-break: break-word;
}
.svc-doc-chart {
	display: grid;
	grid-template-columns: repeat(auto-fit, minmax(190px, 1fr));
	gap: 10px;
}
@media (max-width: 480px) {
	.svc-doc-row {
		flex-direction: column;
		gap: 0;
	}
	.svc-doc-k {
		flex: none;
	}
}
</style>
