<template>
	<div class="svc-res-wrap">
		<!-- the state of a service restart asked from here: calm while it goes down and comes back, orange list when the machine is not at rest -->
		<session-notice v-if="restart && restart.phase === 'restarting'" kind="down" :text="$t(D + 'ui_svc_restarting')" class="mb-2" />
		<session-notice v-if="restart && restart.phase === 'slow'" kind="down" :text="$t(D + 'ui_svc_slow')" class="mb-2" />
		<div v-if="blocked" class="svc-res-blocked" role="note">
			<div>{{ $t(D + 'ui_svc_blocked') }}</div>
			<ul v-if="blocked.reasons.length" class="svc-res-pend-list">
				<li v-for="(r, i) in blocked.reasons" :key="i">{{ r }}</li>
			</ul>
			<div v-else-if="blocked.text">{{ blocked.text }}</div>
		</div>
		<session-notice v-if="restartFailure" :kind="restartFailure.kind" :text="restartFailure.text" class="mb-2" />
		<!-- processes a person paused from here: visible at the top while there is one (they do not collect data until resumed) -->
		<div v-if="paused.length" class="svc-res-paused" role="status">
			<v-icon small class="svc-res-paused-ico" aria-hidden="true">mdi-pause-circle-outline</v-icon>
			<div>
				<b>{{ $t(D + 'ui_paused_banner_title', { n: paused.length }) }}</b>: {{ paused.map(x => x.title || x.id).join(', ') }}
				<div class="text-caption">{{ $t(D + 'ui_paused_banner_text') }}</div>
			</div>
		</div>
		<!-- changes saved that only apply when the service restarts (orange, only when there is one) -->
		<div v-if="pending.length" class="svc-res-pend" role="note">
			<button type="button" class="svc-res-pend-head" :aria-expanded="pendOpen ? 'true' : 'false'" aria-controls="svc-res-pend-list" @click="pendOpen = !pendOpen">
				<v-icon small class="svc-res-pend-ico" aria-hidden="true">mdi-restart-alert</v-icon>
				<b>{{ $t('plugins.WorkshopService.procDocs.ui_pending_title', { n: pending.length }) }}</b>
				<v-icon small class="svc-res-pend-chev" aria-hidden="true">mdi-chevron-down</v-icon>
			</button>
			<div class="svc-res-pend-text">{{ $t(D + (canRestart ? 'ui_pending_text_can' : 'ui_pending_text')) }}</div>
			<ul v-if="pendOpen" id="svc-res-pend-list" class="svc-res-pend-list">
				<li v-for="x in pending" :key="x.id">{{ $t('plugins.WorkshopService.procDocs.ui_pending_item', { title: x.title, mode: $t('plugins.WorkshopService.servicePage.mode_' + x.mode) }) }}</li>
			</ul>
			<div class="svc-res-pend-act" @click="touchRestart">
				<v-btn small outlined color="warning" :disabled="!canRestart || restarting" @click="$emit('restart-service')"><v-icon v-if="!canRestart" small left aria-hidden="true">mdi-lock-outline</v-icon>{{ $t(D + 'ui_svc_restart_btn') }}</v-btn>
			</div>
		</div>
		<!-- the same button when nothing is pending: one reason below it for a role that cannot -->
		<div v-else class="svc-res-restart" @click="touchRestart">
			<v-btn small outlined :disabled="!canRestart || restarting" @click="$emit('restart-service')"><v-icon v-if="!canRestart" small left aria-hidden="true">mdi-lock-outline</v-icon>{{ $t(D + 'ui_svc_restart_btn') }}</v-btn>
			<span class="text-caption grey--text">{{ $t(D + 'ui_svc_restart_hint') }}</span>
		</div>
		<lock-reason v-if="shown" op="service.restart" need="admin" class="mb-2 svc-lock-reason" />
		<div class="svc-res" :data-n="7">
		<!-- Safety: how many of the protections are watched and on time (purple tint; orange / red only when one is late / stopped) -->
		<div class="svc-res-tile svc-res-safe" :class="{ 'svc-res-safe-warn': safetyView.level === 1, 'svc-res-safe-bad': safetyView.level === 2 }">
			<div class="svc-res-t">{{ $t('plugins.WorkshopService.procDocs.ui_tile_safety') }}</div>
			<div class="svc-res-n" :class="safetyView.color ? safetyView.color + '--text' : ''">{{ safetyView.text }}</div>
			<div v-if="safetyView.sub" class="svc-res-s">{{ safetyView.sub }}</div>
		</div>
		<div class="svc-res-tile" :style="{ borderTopColor: service.color }">
			<div class="svc-res-t">{{ $t('plugins.WorkshopService.procDocs.ui_summary_service') }}</div>
			<div class="svc-res-n" :class="service.color + '--text'">{{ service.text }}</div>
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
				<span class="success--text">{{ $t('plugins.WorkshopService.procDocs.ui_summary_ok', { n: count.ok }) }}</span>
				<span v-if="count.notice" class="warning--text"> &middot; {{ $t('plugins.WorkshopService.procDocs.ui_summary_warn', { n: count.notice }) }}</span>
				<span v-if="count.bad" class="error--text"> &middot; {{ $t('plugins.WorkshopService.procDocs.ui_summary_bad', { n: count.bad }) }}</span>
				</template>
				<span v-else>{{ $t('plugins.WorkshopService.procDocs.ui_summary_unavailable') }}</span>
			</div>
			<div v-if="process" class="svc-res-s">{{ $t('plugins.WorkshopService.servicePage.n_threads', { n: process.threads }) }}</div>
		</div>
		<div class="svc-res-tile">
			<div class="svc-res-t">{{ $t('plugins.WorkshopService.procDocs.ui_summary_restarts') }} / {{ $t('plugins.WorkshopService.procDocs.ui_summary_errors') }}</div>
			<div class="svc-res-n" v-if="!count">-</div>
			<div v-else class="svc-res-n"><span :class="restarts ? 'warning--text' : ''">{{ restarts }}</span> / <span :class="errors ? 'warning--text' : ''">{{ errors }}</span></div>
			<div v-if="count" class="svc-res-s">{{ $t('plugins.WorkshopService.servicePage.n_loops', { n: turns }) }}</div>
		</div>
		<div class="svc-res-tile" :style="{ borderTopColor: load.color === 'success' ? '#43A047' : (load.color === 'warning' ? '#FB8C00' : (load.color === 'error' ? '#E53935' : '#757575')) }">
			<div class="svc-res-t">{{ $t('plugins.WorkshopService.procDocs.ui_summary_board') }}</div>
			<div class="svc-res-n" :class="load.color + '--text'">{{ load.text }}</div>
			<div v-if="ipc" class="svc-res-s">{{ $t('plugins.WorkshopService.servicePage.n_calls_min', { n: ipc.per_min }) }}</div>
		</div>
		</div>
	</div>
</template>

<script>
'use strict'

import Spark from './Spark.vue'
import SessionNotice from './SessionNotice.vue'
import LockReason from './LockReason.vue'
import { roleMixin } from './role-mixin.js'
import { signedOut } from './workshop-auth.js'
import { blinkLocked } from './lock-attention.js'
import { duration } from './format.js'
import { serviceText } from './service-text.js'

// Strip of tiles at the top of "Processes and automations": the service itself (state, CPU and memory
// with their last minutes), how many processes are fine / late / failing, restarts and errors added up,
// and the load the service puts on the board.
export default {
	name: 'ProcessesSummary',
	components: { Spark, SessionNotice, LockReason },
	mixins: [roleMixin],
	props: {
		service: { type: Object, required: true }, // { texto, color }
		process: { type: Object, default: null }, // pid, age_s, memory_mb, cpu_pct, hilos
		processes: { type: Array, default: () => [] },
		count: { type: Object, default: null }, // { ok, notice, bad } of the ONE list (processes + separate services); null = service not available
		load: { type: Object, required: true }, // { texto, color }
		ipc: { type: Object, default: null },
		histService: { type: Object, required: true }, // { cpu: [], mem: [] }
		guard: { type: Object, default: null }, // data.guardStatus of the service (protection_guard.py)
		paused: { type: Array, default: () => [] }, // the processes paused from the page (processes-groups.js pausedList): a banner while there is one
		pending: { type: Array, default: () => [] }, // [{ id, title, mode }] processes whose stored mode waits for a service restart (processes-groups.js pendingList)
		restart: { type: Object, default: null }, // { phase: '' | 'restarting' | 'slow', failure: { kind, reasons, text } | null } of a service restart asked from this page
		safety: { type: Object, default: null } // { ok, total, warn, bad } of the safety group (processes-groups.js safetyTally); null = the service reports no group
	},
	data() {
		return { pendOpen: false, shown: false, D: 'plugins.WorkshopService.procDocs.' }
	},
	computed: {
		// Protection guard: are the safety processes (status lights, Vision, RS485...) alive? Discreet: one tile.
		guardView() {
			const g = this.guard || {}
			const t = k => this.$t('plugins.WorkshopService.procDocs.' + k)
			if (g.enabled === false) return { hex: '#757575', color: 'grey', text: t('ui_guard_off'), names: '' }
			if (g.degraded) {
				const down = (g.watches || []).filter(w => w.state === 'down').map(w => serviceText(w.title))
				return { hex: '#E53935', color: 'error', text: t('ui_guard_degraded'), names: down.join(', ') }
			}
			return { hex: '#43A047', color: 'success', text: t('ui_guard_ok'), names: '' }
		},
		// the tile of Safety: "n of m" of the safety group; a service that reports no group yet falls back to the guard tile it had
		safetyView() {
			const s = this.safety
			const t = (k, params) => this.$t('plugins.WorkshopService.procDocs.' + k, params)
			if (s && s.total) {
				const level = s.bad ? 2 : (s.warn ? 1 : 0)
				const g = this.guard && this.guard.degraded ? this.guardView.names : ''
				return { level, color: level === 2 ? 'error' : (level === 1 ? 'warning' : ''), text: t('ui_tile_safety_n', { ok: s.ok, n: s.total }), sub: g || t('ui_tile_safety_sub') }
			}
			if (this.guard) return { level: this.guardView.color === 'error' ? 2 : 0, color: this.guardView.color === 'success' ? '' : this.guardView.color, text: this.guardView.text, sub: this.guardView.names }
			return { level: 0, color: '', text: '-', sub: '' }
		},
		canRestart() {
			return this.canDo('service.restart')
		},
		restarting() {
			return !!(this.restart && (this.restart.phase === 'restarting' || this.restart.phase === 'slow'))
		},
		// the refusal because the machine is not at rest: an orange list; role / session / real failures go to the standard notices
		blocked() {
			const f = this.restart && this.restart.failure
			return f && f.kind === 'blocked' ? f : null
		},
		restartFailure() {
			const f = this.restart && this.restart.failure
			if (!f || f.kind === 'blocked' || f.kind === 'cancelled') return null
			return f.kind === 'error' ? { kind: 'error', text: this.$t(this.D + 'ui_svc_failed', { msg: f.text || '' }) } : { kind: f.kind, text: f.text }
		},
		total() {
			return this.count ? this.count.ok + this.count.notice + this.count.bad : 0
		},
		restarts() {
			return this.processes.reduce((a, p) => a + (p.restarts || 0), 0)
		},
		errors() {
			return this.processes.reduce((a, p) => a + (p.errors_total || 0), 0)
		},
		turns() {
			return this.processes.reduce((a, p) => a + (p.cycles || 0), 0)
		}
	},
	methods: {
		duration: duration,
		// a touch on the restart button while this role cannot restart the service (a disabled button emits no click): its reason blinks
		touchRestart() {
			if (this.canRestart) return
			this.shown = true
			this.$nextTick(() => blinkLocked(this.$el, signedOut()))
		}
	}
};
</script>

<style scoped>
/* the reason hugs its text: the blink rings the words, not the whole width of the card */
.svc-lock-reason { display: inline-flex; width: fit-content; max-width: 100%; padding: 2px 8px; border-radius: 6px; }
.svc-res-wrap { container-type: inline-size; margin-bottom: 12px; }
.svc-res-paused { display: flex; gap: 10px; align-items: flex-start; margin-bottom: 8px; padding: 8px 12px; border: 1px solid rgba(84, 110, 122, 0.55); border-left: 4px solid #78909c; border-radius: 8px; background: rgba(84, 110, 122, 0.14); font-size: 13px; }
.svc-res-paused-ico { color: #78909c; margin-top: 2px; }
.svc-res {
	display: grid;
	grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
	gap: 8px;
}
/* The tiles are always 7 (the data-n stays so the grid rules below can tell); the columns follow the width of the strip itself, not the window, so no
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
.svc-res-safe { border-color: rgba(126, 87, 194, 0.55); background: rgba(126, 87, 194, 0.1); }
.svc-res-safe-warn { border-color: rgba(251, 140, 0, 0.6); }
.svc-res-safe-bad { border-color: rgba(229, 57, 53, 0.6); }
.svc-res-pend {
	margin-bottom: 8px;
	padding: 8px 12px;
	border: 1px solid rgba(251, 140, 0, 0.6);
	border-radius: 8px;
	background: rgba(251, 140, 0, 0.1);
	font-size: 13px;
}
.svc-res-pend-head {
	display: flex;
	align-items: center;
	gap: 6px;
	width: 100%;
	padding: 0;
	border: 0;
	background: none;
	color: var(--wf-warn, #fb8c00);
	font: inherit;
	text-align: left;
	cursor: pointer;
}
.svc-res-pend-head:focus-visible { outline: 2px solid var(--wf-info, #1e88e5); outline-offset: 2px; }
.svc-res-pend-ico, .svc-res-pend-chev { color: inherit !important; }
.svc-res-pend-chev { margin-left: auto; transition: transform 0.15s; }
.svc-res-pend-head[aria-expanded="true"] .svc-res-pend-chev { transform: rotate(180deg); }
@media (prefers-reduced-motion: reduce) { .svc-res-pend-chev { transition: none; } }
.svc-res-blocked {
	margin-bottom: 8px;
	padding: 8px 12px;
	border: 1px solid rgba(251, 140, 0, 0.6);
	border-radius: 8px;
	background: rgba(251, 140, 0, 0.1);
	font-size: 13px;
}
.svc-res-pend-act { margin-top: 8px; }
.svc-res-restart { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; margin-bottom: 8px; }
.svc-res-pend-text { margin-top: 4px; opacity: 0.85; }
.svc-res-pend-list { margin: 6px 0 0; padding-left: 20px; }
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
