<template>
	<div class="svc-proc">
		<div class="d-flex align-center flex-wrap">
			<v-icon class="mr-3 svx-ico">{{ p.info.icon }}</v-icon>
			<div class="svc-proc-txt">
				<div class="font-weight-medium">
					{{ p.title }}
					<v-chip size="x-small" label variant="outlined" :color="p.info.color" class="ml-1">{{ p.info.cat }}</v-chip>
				</div>
				<div class="text-body-small text-medium-emphasis">{{ p.description }}</div>
				<div v-if="p.detail" class="text-body-small svc-detail"><v-icon size="x-small" class="mr-1">mdi-information-outline</v-icon>{{ p.detail }}</div>
			</div>
			<v-spacer />
			<v-chip size="small" label variant="flat" :color="p.state.color" :title="p.state.detail">
				<v-icon start size="x-small">{{ p.state.icon }}</v-icon>{{ p.state.text }}
			</v-chip>
		</div>

		<!-- when it runs: automatic (a plugin that needs it is enabled), always or never -->
		<div v-if="p.module" class="ml-10 mt-2 d-flex align-center flex-wrap svc-modo" style="gap:8px">
			<span class="text-body-small text-medium-emphasis" :title="$t('plugins.WorkshopService.servicePage.mode_help')">{{ $t('plugins.WorkshopService.servicePage.mode_label') }}</span>
			<v-btn-toggle :model-value="p.module.mode" mandatory density="compact" class="svc-mode-buttons" @update:model-value="v => $emit('mode', v)">
				<v-btn v-for="m in ['auto', 'on', 'off']" :key="m" :value="m" size="x-small">{{ $t('plugins.WorkshopService.servicePage.mode_' + m) }}</v-btn>
			</v-btn-toggle>
			<span class="text-body-small text-medium-emphasis">{{ reason }}</span>
			<span v-if="p.modeError" class="text-body-small svc-err">{{ p.modeError }}</span>
		</div>

		<div class="text-body-small ml-10 mt-1">
			<span v-if="p.age_ok_s != null" class="text-medium-emphasis">{{ $t('plugins.WorkshopService.servicePage.last_heartbeat_t', { t: age(p.age_ok_s) }) }}</span>
			<span class="svc-metricas text-medium-emphasis">
				<span v-if="p.cpu_pct != null" :title="$t('plugins.WorkshopService.servicePage.cpu_used_by_this_thread')">CPU {{ p.cpu_pct }}%</span>
				<span v-if="p.active_s != null" :title="$t('plugins.WorkshopService.servicePage.since_this_process_last_started')">{{ $t('plugins.WorkshopService.servicePage.active_for_t', { t: duration(p.active_s) }) }}</span>
				<span v-if="p.cycles" :title="$t('plugins.WorkshopService.servicePage.loops_completed_since_the_service_started')">{{ $t('plugins.WorkshopService.servicePage.n_loops', { n: p.cycles }) }}</span>
				<span v-if="p.errors_total" class="text-warning" :title="$t('plugins.WorkshopService.servicePage.errors_since_the_service_started')">{{ $t('plugins.WorkshopService.servicePage.n_errors', { n: p.errors_total }) }}</span>
			</span>
			<v-chip v-if="p.restarts" size="x-small" label color="orange-darken-2" variant="flat" class="ml-2">
				<v-icon start size="x-small">mdi-restart</v-icon>{{ $t('plugins.WorkshopService.servicePage.relaunched_n', { n: p.restarts }) }}
			</v-chip>
		</div>

		<!-- heartbeat pace: average interval against the expected one -->
		<div v-if="step" class="ml-10 mt-2 svc-paso" :title="$t('plugins.WorkshopService.procDocs.ui_cadence_help')">
			<div class="d-flex text-body-small" style="gap:8px">
				<span class="text-medium-emphasis">{{ $t('plugins.WorkshopService.procDocs.ui_cadence') }}</span>
				<v-spacer />
				<span class="text-medium-emphasis">{{ $t('plugins.WorkshopService.servicePage.every_t', { t: sec(p.interval_avg) }) }}<template v-if="p.interval_max != null"> &middot; {{ $t('plugins.WorkshopService.servicePage.max_t', { t: sec(p.interval_max) }) }}</template></span>
				<span class="text-medium-emphasis">{{ $t('plugins.WorkshopService.procDocs.ui_expected', { t: sec(p.expected_s) }) }}</span>
				<b :class="'text-' + step.color">{{ step.pct }} %</b>
			</div>
			<v-progress-linear :model-value="Math.min(100, step.pct / 2)" height="5" rounded :color="step.color" bg-color="grey-darken-3" class="mt-1" />
		</div>

		<div v-if="p.error && p.errorRecent" class="text-body-small ml-10 mt-1 svc-err">
			<v-icon size="x-small" color="error">mdi-alert-circle</v-icon>
			{{ p.error_hour }}: {{ p.error }}
		</div>

		<div v-if="hasDocs || hist" class="ml-10 mt-1">
			<a href="#" class="text-body-small" @click.prevent="open = !open">
				<v-icon size="x-small" color="primary">{{ open ? 'mdi-chevron-up' : 'mdi-chevron-down' }}</v-icon>
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
			<div v-if="p.error" class="text-body-small svc-err mt-2">
				<b>{{ $t('plugins.WorkshopService.procDocs.ui_last_error') }}</b> &middot; {{ p.error_hour }}: {{ p.error }}
			</div>
		</div>
	</div>
</template>

<script setup>
import { computed, ref } from 'vue'
import { i18n } from './dwc-host.js'
import Spark from './Spark.vue'
import { sec, duration, age, rhythm } from './format.js'
import { pluginActive } from './workshop-ids.js'

const D = 'plugins.WorkshopService.procDocs.'
// the plugin whose page or panel each process serves: the "where" line names it only when that plugin is there
const PLUGIN_OF = { status_light: 'lights', consumption: 'consumption', motors: 'motors', jog: 'jog', health: 'health', events: 'activity', jobs: 'activity' }

// One internal process of the service: what the backend publishes about it (state, heartbeat,
// pace, CPU, loops, errors, relaunches) and, unfolded, what it is, what it is for, what happens if
// it stops, what it relies on and where it is adjusted, plus the history of its last minutes.
const props = defineProps({
	p: { type: Object, required: true },
	hist: { type: Object, default: null },
	openInitial: { type: Boolean, default: false }
})
defineEmits(['mode'])

const open = ref(props.openInitial)

const step = computed(() => rhythm(props.p))
const docs = computed(() => {
	const out = []
	const add = (key, suffix) => {
		const k = D + props.p.id + '_' + suffix
		if (suffix === 'where' && PLUGIN_OF[props.p.id] && !pluginActive(PLUGIN_OF[props.p.id])) return
		if (i18n.te(k)) out.push({ k: i18n.t(D + key), v: i18n.t(k) })
	}
	add('ui_what', 'what')
	add('ui_why', 'why')
	add('ui_fails', 'fails')
	add('ui_uses', 'uses')
	add('ui_where', 'where')
	return out
})
const reason = computed(() => {
	const r = (props.p.module || {}).reason || {}
	const k = 'plugins.WorkshopService.servicePage.why_' + r.code
	return i18n.te(k) ? i18n.t(k, { p: (r.plugins || []).join(', ') }) : ''
})
const hasDocs = computed(() => docs.value.length > 0)
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
