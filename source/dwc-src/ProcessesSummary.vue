<template>
	<div class="svc-res-wrap">
		<div class="svc-res" :data-n="guard ? 7 : 6">
		<div class="svc-res-tile" :style="{ borderTopColor: service.color }">
			<div class="svc-res-t">{{ $t('plugins.WorkshopService.procDocs.ui_summary_service') }}</div>
			<div class="svc-res-n" :class="'text-' + service.color">{{ service.text }}</div>
			<div v-if="process" class="svc-res-s">
				PID {{ process.pid }} &middot; {{ $t('plugins.WorkshopService.procDocs.ui_uptime') }} {{ duration(process.age_s) }}
			</div>
		</div>
		<div class="svc-res-tile">
			<div class="svc-res-t">{{ $t('plugins.WorkshopService.procDocs.ui_cpu_total') }}</div>
			<div class="svc-res-n">{{ process && process.cpu_pct != null ? process.cpu_pct + ' %' : '-' }}</div>
			<spark :values="histService.cpu" title="" unit="%" color="#42A5F5" :height="26" />
		</div>
		<div class="svc-res-tile">
			<div class="svc-res-t">{{ $t('plugins.WorkshopService.procDocs.ui_mem') }}</div>
			<div class="svc-res-n">{{ process && process.memory_mb != null ? process.memory_mb + ' MB' : '-' }}</div>
			<spark :values="histService.mem" title="" unit="MB" color="#AB47BC" :height="26" :minZero="false" :decimals="0" />
		</div>
		<div class="svc-res-tile">
			<div class="svc-res-t">{{ $t('plugins.WorkshopService.procDocs.ui_summary_procs') }}</div>
			<div class="svc-res-n">{{ count ? total : '-' }}</div>
			<div class="svc-res-s">
				<template v-if="count">
				<span class="text-success">{{ $t('plugins.WorkshopService.procDocs.ui_summary_ok', { n: count.ok }) }}</span>
				<span v-if="count.notice" class="text-warning"> &middot; {{ $t('plugins.WorkshopService.procDocs.ui_summary_warn', { n: count.notice }) }}</span>
				<span v-if="count.bad" class="text-error"> &middot; {{ $t('plugins.WorkshopService.procDocs.ui_summary_bad', { n: count.bad }) }}</span>
				</template>
				<span v-else>{{ $t('plugins.WorkshopService.procDocs.ui_summary_unavailable') }}</span>
			</div>
			<div v-if="process" class="svc-res-s">{{ $t('plugins.WorkshopService.servicePage.n_threads', { n: process.threads }) }}</div>
		</div>
		<div class="svc-res-tile">
			<div class="svc-res-t">{{ $t('plugins.WorkshopService.procDocs.ui_summary_restarts') }} / {{ $t('plugins.WorkshopService.procDocs.ui_summary_errors') }}</div>
			<div class="svc-res-n" v-if="!count">-</div>
			<div v-else class="svc-res-n"><span :class="restarts ? 'text-warning' : ''">{{ restarts }}</span> / <span :class="errors ? 'text-warning' : ''">{{ errors }}</span></div>
			<div v-if="count" class="svc-res-s">{{ $t('plugins.WorkshopService.servicePage.n_loops', { n: turns }) }}</div>
		</div>
		<div v-if="guard" class="svc-res-tile" :style="{ borderTopColor: guardView.hex }">
			<div class="svc-res-t">{{ $t('plugins.WorkshopService.procDocs.ui_guard_title') }}</div>
			<div class="svc-res-n" :class="'text-' + guardView.color">{{ guardView.text }}</div>
			<div v-if="guardView.names" class="svc-res-s">{{ guardView.names }}</div>
		</div>
		<div class="svc-res-tile" :style="{ borderTopColor: load.color === 'success' ? '#43A047' : (load.color === 'warning' ? '#FB8C00' : (load.color === 'error' ? '#E53935' : '#757575')) }">
			<div class="svc-res-t">{{ $t('plugins.WorkshopService.procDocs.ui_summary_board') }}</div>
			<div class="svc-res-n" :class="'text-' + load.color">{{ load.text }}</div>
			<div v-if="ipc" class="svc-res-s">{{ $t('plugins.WorkshopService.servicePage.n_calls_min', { n: ipc.per_min }) }}</div>
		</div>
		</div>
	</div>
</template>

<script setup>
import { computed } from 'vue'
import { i18n } from './dwc-host.js'
import Spark from './Spark.vue'
import { duration } from './format.js'
import { serviceText } from './service-text.js'

// Strip of tiles at the top of "Processes and automations": the service itself (state, CPU and memory
// with their last minutes), how many processes are fine / late / failing, restarts and errors added up,
// and the load the service puts on the board.
const props = defineProps({
	service: { type: Object, required: true }, // { text, color }
	process: { type: Object, default: null }, // pid, age_s, memory_mb, cpu_pct, threads
	processes: { type: Array, default: () => [] },
	count: { type: Object, default: null }, // { ok, notice, bad } of the ONE list (processes + separate services); null = service not available
	load: { type: Object, required: true }, // { text, color }
	ipc: { type: Object, default: null },
	histService: { type: Object, required: true }, // { cpu: [], mem: [] }
	guard: { type: Object, default: null } // data.guardStatus of the service (protection_guard.py)
})

// Protection guard: are the safety processes (status lights, Vision, RS485...) alive? Discreet: one tile.
const guardView = computed(() => {
	const g = props.guard || {}
	const t = k => i18n.t('plugins.WorkshopService.procDocs.' + k)
	if (g.enabled === false) return { hex: '#757575', color: 'grey', text: t('ui_guard_off'), names: '' }
	if (g.degraded) {
		const down = (g.watches || []).filter(w => w.state === 'down').map(w => serviceText(w.title))
		return { hex: '#E53935', color: 'error', text: t('ui_guard_degraded'), names: down.join(', ') }
	}
	return { hex: '#43A047', color: 'success', text: t('ui_guard_ok'), names: '' }
})
const total = computed(() => props.count ? props.count.ok + props.count.notice + props.count.bad : 0)
const restarts = computed(() => props.processes.reduce((a, p) => a + (p.restarts || 0), 0))
const errors = computed(() => props.processes.reduce((a, p) => a + (p.errors_total || 0), 0))
const turns = computed(() => props.processes.reduce((a, p) => a + (p.cycles || 0), 0))
</script>

<style scoped>
.svc-res-wrap { container-type: inline-size; margin-bottom: 12px; }
.svc-res {
	display: grid;
	grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
	gap: 8px;
}
/* The tiles come in 6 or 7 (the guard tile is optional); the columns follow the width of the strip itself, not the window, so no
   tile is left alone on a last row: 2 columns (an odd last tile spans both), then 3 for six tiles / 4 for seven. */
@container (max-width: 419px) {
	.svc-res { grid-template-columns: repeat(2, minmax(0, 1fr)); }
	.svc-res > :last-child:nth-child(odd) { grid-column: 1 / -1; }
}
@container (min-width: 420px) {
	.svc-res[data-n="6"] { grid-template-columns: repeat(3, minmax(0, 1fr)); }
	.svc-res[data-n="7"] { grid-template-columns: repeat(2, minmax(0, 1fr)); }
	.svc-res[data-n="7"] > :last-child { grid-column: 1 / -1; }
}
@container (min-width: 640px) {
	.svc-res[data-n="7"] { grid-template-columns: repeat(4, minmax(0, 1fr)); }
	.svc-res[data-n="7"] > :last-child { grid-column: auto; }
}
.svc-res-tile {
	padding: 8px 10px;
	border: 1px solid var(--wf-line);
	border-radius: 8px;
	min-width: 0;
}
.svc-res-t {
	font-size: 12px;
	color: var(--tp-faint, #9e9e9e);
	white-space: nowrap;
	overflow: hidden;
	text-overflow: ellipsis;
}
.svc-res-n {
	font-size: 20px;
	font-weight: 500;
	line-height: 1.3;
	white-space: nowrap;
	overflow: hidden;
	text-overflow: ellipsis;
}
.svc-res-s {
	font-size: 11px;
	color: var(--tp-faint, #9e9e9e);
	line-height: 1.4;
}
</style>
