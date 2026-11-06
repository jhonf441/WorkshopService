<template>
	<div class="svc-pr" :class="['svc-pr--' + group, 'svc-pr-s-' + key]">
		<!-- the row is ONE button (keyboard: Tab, Enter / Space): the state dot, the name, one line of what it does, the tags -->
		<button type="button" class="svc-pr-head" :aria-expanded="open ? 'true' : 'false'" :aria-controls="'svc-pr-' + p.id" @click="open = !open">
			<span class="svc-pr-dot" aria-hidden="true" />
			<span class="svc-pr-ttl">{{ title }}<span class="svc-pr-sr"> - {{ p.state.text }}</span></span>
			<span class="svc-pr-what">
				{{ what }}
				<span v-if="beat" class="svc-pr-beat">{{ beat }}</span>
			</span>
			<span class="svc-pr-tags">
				<span v-if="group === 'safety'" class="svc-pr-tag svc-pr-tag--safe">{{ $t(D + 'ui_tag_safety') }}</span>
				<span class="svc-pr-tag" :class="p.external ? 'svc-pr-tag--own' : ''">{{ $t(D + (p.external ? 'ui_tag_own' : 'ui_tag_thread')) }}</span>
				<span v-if="key === 'late' || key === 'bad'" class="svc-pr-tag" :class="'svc-pr-tag--' + key" :title="p.state.detail">{{ p.state.text }}</span>
				<span v-if="paused" class="svc-pr-tag svc-pr-tag--paused"><v-icon x-small class="mr-1" aria-hidden="true">mdi-pause-circle-outline</v-icon>{{ $t(D + 'ui_tag_paused') }}</span>
				<span v-if="p.restarts" class="svc-pr-tag svc-pr-tag--late">{{ $t('plugins.WorkshopService.servicePage.relaunched_n', { n: p.restarts }) }}</span>
			</span>
			<v-icon small class="svc-pr-chev" aria-hidden="true">mdi-chevron-right</v-icon>
		</button>

		<!-- the control of the camera relay: the relay is a process of this service (camera-relay.js); it stays in sight, not inside the button -->
		<relay-card v-if="p.id === 'camera'" class="svc-pr-relay" />

		<div v-if="p.error && p.errorRecent && !open" class="svc-pr-lasterr">{{ p.error_hour }}: {{ p.error }}</div>

		<div v-if="open" :id="'svc-pr-' + p.id" class="svc-pr-detail">
			<dl class="svc-pr-facts">
				<div v-for="d in docs" :key="d.k">
					<dt>{{ d.k }}</dt>
					<dd>{{ d.v }}</dd>
				</div>
				<div v-if="beat">
					<dt>{{ $t(D + 'ui_cadence') }}</dt>
					<dd>{{ beat }}</dd>
				</div>
				<div v-if="effective">
					<dt>{{ $t(D + 'ui_running_now') }}</dt>
					<dd>{{ $t(D + effective) }}</dd>
				</div>
			</dl>

			<div v-if="paused" class="svc-pr-line"><span class="svc-pr-tag svc-pr-tag--paused mr-1">{{ $t(D + 'ui_tag_paused') }}</span>{{ $t(D + 'ui_paused_detail') }}</div>
			<div v-if="restartInfo" class="svc-pr-line">{{ $t(D + restartInfo.key, restartInfo.params) }}</div>
			<session-notice v-if="restartInfo && restartInfo.stuck" kind="down" :text="$t(D + 'ui_restart_stuck')" class="mt-1" />

			<div v-if="p.detail" class="svc-pr-line"><v-icon x-small class="mr-1">mdi-information-outline</v-icon>{{ p.detail }}</div>

			<!-- the buses of a separate service (RS485) and the link to its page -->
			<div v-if="p.buses && p.buses.length" class="svc-pr-line">
				<span v-for="b in p.buses" :key="b.id" class="mr-3" :class="b.open ? 'success--text' : (b.error ? 'warning--text' : 'grey--text')" :title="b.error || ''">
					<v-icon x-small :color="b.open ? 'success' : (b.error ? 'warning' : 'grey')">mdi-serial-port</v-icon>
					{{ b.name }}: {{ b.open ? $t('plugins.WorkshopService.servicePage.open') : (b.error ? $t('plugins.WorkshopService.servicePage.with_a_problem') : $t('plugins.WorkshopService.servicePage.closed')) }}
					<span class="grey--text">{{ $t('plugins.WorkshopService.servicePage.bus_stats', { ok: b.stats.ok, nr: b.stats.without_response, crc: b.stats.crc }) }}</span>
				</span>
			</div>
			<div v-if="p.link" class="svc-pr-line">
				<a v-if="p.link.path" href="#" @click.prevent="$emit('go-path', p.link.path)">{{ $t('plugins.WorkshopService.servicePage.open_the_page') }}</a>
				<a v-else-if="p.link.anchor" href="#" @click.prevent="$emit('go-anchor', p.link.anchor)">{{ $t('plugins.WorkshopService.servicePage.see_details_and_settings') }}</a>
			</div>

			<div v-if="!p.external" class="svc-pr-line svc-pr-metrics">
				<span v-if="p.cpu_pct != null" :title="$t('plugins.WorkshopService.servicePage.cpu_used_by_this_thread')">CPU {{ p.cpu_pct }}%</span>
				<span v-if="p.active_s != null" :title="$t('plugins.WorkshopService.servicePage.since_this_process_last_started')">{{ $t('plugins.WorkshopService.servicePage.active_for_t', { t: duration(p.active_s) }) }}</span>
				<span v-if="p.cycles" :title="$t('plugins.WorkshopService.servicePage.loops_completed_since_the_service_started')">{{ $t('plugins.WorkshopService.servicePage.n_loops', { n: p.cycles }) }}</span>
				<span v-if="p.errors_total" class="warning--text" :title="$t('plugins.WorkshopService.servicePage.errors_since_the_service_started')">{{ $t('plugins.WorkshopService.servicePage.n_errors', { n: p.errors_total }) }}</span>
			</div>

			<!-- heartbeat pace: average interval against the expected one -->
			<div v-if="step" class="svc-pr-pace" :title="$t(D + 'ui_cadence_help')">
				<div class="d-flex text-caption" style="gap:8px">
					<span class="grey--text">{{ $t(D + 'ui_cadence') }}</span>
					<v-spacer />
					<span class="grey--text">{{ $t('plugins.WorkshopService.servicePage.every_t', { t: sec(p.interval_avg) }) }}<template v-if="p.interval_max != null"> &middot; {{ $t('plugins.WorkshopService.servicePage.max_t', { t: sec(p.interval_max) }) }}</template></span>
					<span class="grey--text">{{ $t(D + 'ui_expected', { t: sec(p.expected_s) }) }}</span>
					<b :class="step.color + '--text'">{{ step.pct }} %</b>
				</div>
				<v-progress-linear :value="Math.min(100, step.pct / 2)" height="5" rounded :color="step.color" background-color="grey darken-3" class="mt-1" />
			</div>

			<div v-if="hist && !p.external" class="svc-pr-chart">
				<spark :values="hist.cpu" :title="$t(D + 'ui_cpu_hist')" unit="%" :color="groupColor" />
				<spark :values="hist.interval" :title="$t(D + 'ui_int_hist')" unit="s" :decimals="2" :color="groupColor" />
			</div>

			<div v-if="p.error" class="svc-pr-line" :class="errorRecovered ? 'svc-pr-err-old' : 'svc-pr-err'">
				<b>{{ $t(D + 'ui_last_error') }}</b> &middot; {{ p.error_hour }}: {{ p.error }}<span v-if="errorRecovered"> &middot; {{ $t(D + 'ui_error_recovered') }}</span>
			</div>

			<!-- the control: a locked process only shows its protected note; the others keep the mode switch (auto / always / never) -->
			<div v-if="p.locked" class="svc-pr-ctl">
				<session-notice kind="empty" :text="$t(D + 'ui_locked_note')" />
			</div>
			<div v-else-if="(p.module && !p.external) || canCtl" class="svc-pr-ctl" @click="touchLocked">
				<div v-if="p.module && !p.external" class="svc-lock-group" data-lock-group="mode">
					<div class="d-flex align-center flex-wrap" style="gap:8px">
						<v-icon v-if="!canMode" small class="svc-lock-ico" aria-hidden="true">mdi-lock-outline</v-icon>
						<span class="text-caption grey--text" :title="$t('plugins.WorkshopService.servicePage.mode_help')">{{ $t('plugins.WorkshopService.servicePage.mode_label') }}</span>
						<v-btn-toggle :key="'mode-' + (p.modeTick || 0)" :value="configured" mandatory dense class="svc-mode-buttons" @change="onMode">
							<v-btn v-for="m in ['auto', 'on', 'off']" :key="m" :value="m" x-small :disabled="!canMode">{{ $t('plugins.WorkshopService.servicePage.mode_' + m) }}</v-btn>
						</v-btn-toggle>
						<span class="text-caption grey--text">{{ reason }}</span>
					</div>
					<!-- the reason of THIS group, only after a touch on it (lock-reason-in-parent) -->
					<lock-reason v-if="shown === 'mode'" op="modules.set" need="technician" class="mt-1 svc-lock-reason" />
				</div>
				<template v-if="p.module && !p.external">
					<!-- the truth about this switch: does it apply at once or when the service restarts, and what the service did at launch -->
					<div class="text-caption grey--text mt-1">{{ $t(D + note.key) }}</div>
					<session-notice v-if="pending" kind="down" :text="$t(D + pending.key, { mode: $t('plugins.WorkshopService.servicePage.mode_' + pending.params.mode) })" class="mt-1" />
					<session-notice v-if="failure" :kind="failure.kind" :text="failure.text" class="mt-1" />
				</template>
				<!-- pause / resume / restart of this process (only the processes the service says are pausable): one reason below the group -->
				<div v-if="canCtl" class="svc-pr-actions svc-lock-group mt-3" data-lock-group="actions">
					<div class="d-flex align-center flex-wrap" style="gap:8px">
						<v-btn v-if="!paused" small outlined :loading="busy && p.ctlAction === 'pause'" :disabled="!canPauseOp || busy" @click="$emit('pause')"><v-icon v-if="!canPauseOp" small left aria-hidden="true">mdi-lock-outline</v-icon>{{ $t(D + 'ui_btn_pause') }}</v-btn>
						<v-btn v-else small color="primary" :loading="busy && p.ctlAction === 'resume'" :disabled="!canResumeOp || busy" @click="$emit('resume')"><v-icon v-if="!canResumeOp" small left aria-hidden="true">mdi-lock-outline</v-icon>{{ $t(D + 'ui_btn_resume') }}</v-btn>
						<v-btn small outlined :loading="busy && p.ctlAction === 'restart'" :disabled="!canRestartOp || busy" @click="$emit('restart')"><v-icon v-if="!canRestartOp" small left aria-hidden="true">mdi-lock-outline</v-icon>{{ $t(D + 'ui_btn_restart_proc') }}</v-btn>
					</div>
					<div v-if="p.ctlDone" class="svc-pr-done" role="status"><v-icon small color="success" class="mr-1" aria-hidden="true">mdi-check-circle-outline</v-icon>{{ $t(D + 'ui_done_' + p.ctlDone, { n: sec(p.expected_s || 30) }) }}</div>
					<lock-reason v-if="shown === 'actions'" op="processes.pause" need="technician" class="mt-1 svc-lock-reason" />
					<div class="text-caption grey--text mt-1">{{ $t(D + 'ui_ctl_limits') }}</div>
					<session-notice v-if="ctlFailure" :kind="ctlFailure.kind" :text="ctlFailure.text" class="mt-1" />
				</div>
				<div v-if="p.module && !p.external" class="text-caption grey--text mt-1">{{ $t(D + 'ui_mode_audit') }}</div>
			</div>
		</div>
	</div>
</template>

<script>
'use strict'

import Spark from './Spark.vue'
import RelayCard from './RelayCard.vue'
import SessionNotice from './SessionNotice.vue'
import LockReason from './LockReason.vue'
import { roleMixin } from './role-mixin.js'
import { signedOut } from './workshop-auth.js'
import { blinkLocked } from './lock-attention.js'
import { sec, duration, age, rhythm } from './format.js'
import { groupOf, stateKey, configuredMode, modeNote, pendingNote, effectiveKey, canPause, pauseKey, restartNote } from './processes-groups.js'

import { pluginActive } from './workshop-ids.js'

const D = 'plugins.WorkshopService.procDocs.'
// the plugin whose page or panel each process serves: the "where" line names it only when that plugin is there
const PLUGIN_OF = { status_light: 'lights', consumption: 'consumption', motors: 'motors', jog: 'jog', health: 'health', events: 'activity', jobs: 'activity', camera: 'camera' }
const GROUP_COLOR = { safety: '#b79cf0', machine: '#5aa9ff', data: '#5cc28a', support: '#8fa3ad', ext: '#f0a23c' }

// One process of the service, or one separate service (Vision, RS485, the bridge, the database), as a row of its group: what the backend
// publishes about it (state, heartbeat, pace, CPU, loops, errors, relaunches) and, unfolded, what it does, what it relies on, what stops if
// it fails, who reads it, its history of the last minutes and its control (the mode switch, or the note that it is protected).
export default {
	name: 'ProcessRow',
	components: { Spark, RelayCard, SessionNotice, LockReason },
	mixins: [roleMixin],
	props: {
		p: { type: Object, required: true },
		hist: { type: Object, default: null },
		openInitial: { type: Boolean, default: false }
	},
	data() {
		return {
			shown: '', D, open: this.openInitial }
	},
	computed: {
		group() {
			return groupOf(this.p)
		},
		groupColor() {
			return GROUP_COLOR[this.group]
		},
		key() {
			return stateKey(this.p)
		},
		title() {
			return this.p.title || this.p.id
		},
		// one line of what it does: what the service says, else the first line of its documentation
		what() {
			if (this.p.description) return this.p.description
			const k = D + this.p.id + '_what'
			return this.$te(k) ? this.$t(k) : ''
		},
		beat() {
			const out = []
			if (this.p.expected_s) out.push(this.$t(D + 'ui_expected', { t: sec(this.p.expected_s) }))
			if (this.p.age_ok_s != null) out.push(this.$t('plugins.WorkshopService.servicePage.last_heartbeat_t', { t: age(this.p.age_ok_s) }))
			return out.join(' · ')
		},
		step() {
			return rhythm(this.p)
		},
		docs() {
			const out = []
			if (this.p.external) {
				;['what', 'how', 'depends', 'why'].forEach(s => {
					const k = D + 'ext_' + this.p.id + '_' + s
					if (this.$te(k)) out.push({ k: this.$t(D + 'ext_' + s).replace(/:\s*$/, ''), v: this.$t(k) })
				})
				return out
			}
			const add = (key, suffix) => {
				const k = D + this.p.id + '_' + suffix
				if (suffix === 'where' && PLUGIN_OF[this.p.id] && !pluginActive(this.$store, PLUGIN_OF[this.p.id])) return
				if (this.$te(k)) out.push({ k: this.$t(D + key), v: this.$t(k) })
			}
			add('ui_what', 'what')
			add('ui_why', 'why')
			add('ui_uses', 'uses')
			add('ui_fails', 'fails')
			add('ui_where', 'where')
			// a process with no documentation yet still says what the service says about it
			if (!out.length && this.p.description) out.push({ k: this.$t(D + 'ui_what'), v: this.p.description })
			return out
		},
		configured() {
			return configuredMode(this.p)
		},
		note() {
			return modeNote(this.p)
		},
		pending() {
			return pendingNote(this.p)
		},
		effective() {
			return effectiveKey(this.p)
		},
		// the last failed change of the mode, { kind, text } (the page keeps it per process), shown in the standard notice
		failure() {
			return this.p.modeError || null
		},
		// the last error is old news when a heartbeat arrived after it
		errorRecovered() {
			const ok = this.p.age_ok_s
			const err = this.p.age_error_s
			return typeof ok === 'number' && typeof err === 'number' && ok < err
		},
		canCtl() {
			return canPause(this.p) && !this.p.locked
		},
		paused() {
			return !!pauseKey(this.p)
		},
		restartInfo() {
			return restartNote(this.p)
		},
		busy() {
			return !!this.p.ctlBusy
		},
		// the last failed or refused pause / resume / restart, { kind, text } (the page keeps it per process)
		ctlFailure() {
			return this.p.ctlError || null
		},
		canPauseOp() {
			return this.canDo('processes.pause')
		},
		canResumeOp() {
			return this.canDo('processes.resume')
		},
		canRestartOp() {
			return this.canDo('processes.restart')
		},
		canMode() {
			return this.canDo('modules.set')
		},
		reason() {
			const r = (this.p.module || {}).reason || {};
			const k = 'plugins.WorkshopService.servicePage.why_' + r.code;
			return this.$te(k) ? this.$t(k, { p: (r.plugins || []).join(', ') }) : '';
		}
	},
	methods: {
		sec: sec,
		// only a real change of the switch reaches the service (a switch that settles on its stored value by itself must not call it)
		onMode(v) {
			if (v !== this.configured) this.$emit('mode', v)
		},
		duration: duration,
		age: age,
		// a touch on the controls while this person cannot use them (a disabled button emits no click: the area around it listens): the reason
		// next to them blinks, and the sign-in chip when nobody is signed in; no dialog, no card
		// only the group that was touched shows and blinks its reason (and the sign-in chip when nobody is signed in)
		touchLocked(ev) {
			const el = ev && ev.target && typeof ev.target.closest === 'function' ? ev.target.closest('[data-lock-group]') : null
			const name = el ? el.getAttribute('data-lock-group') : ''
			const locked = name === 'mode' ? !this.canMode : name === 'actions' ? !((this.paused ? this.canResumeOp : this.canPauseOp) && this.canRestartOp) : false
			if (!locked) return
			this.shown = name
			this.$nextTick(() => blinkLocked(el, signedOut()))
		}
	}
};
</script>

<style scoped>
.svc-pr {
	--svc-c: #6e787f;
	border-bottom: 1px solid var(--wf-line);
}
.svc-pr:last-child { border-bottom: 0; }
.svc-pr-s-ok { --svc-c: var(--wf-ok, #43a047); }
.svc-pr-s-late { --svc-c: var(--wf-warn, #fb8c00); }
.svc-pr-s-bad { --svc-c: var(--wf-err, #e53935); }
.svc-pr-s-idle { --svc-c: #6e787f; }
.svc-pr-s-paused { --svc-c: #78909c; background: rgba(84, 110, 122, 0.10); box-shadow: inset 3px 0 0 #78909c; }
.svc-pr-head {
	display: grid;
	grid-template-columns: 14px minmax(140px, 1.1fr) minmax(200px, 2fr) auto 18px;
	gap: 6px 14px;
	align-items: center;
	width: 100%;
	padding: 9px 14px;
	border: 0;
	background: none;
	color: inherit;
	font: inherit;
	text-align: left;
	cursor: pointer;
}
.svc-pr-head:hover { background: var(--wf-soft); }
.svc-pr-head:focus-visible { outline: 2px solid var(--wf-info, #1e88e5); outline-offset: -2px; }
.svc-pr-dot {
	width: 10px;
	height: 10px;
	border-radius: 50%;
	background: var(--svc-c);
	box-shadow: 0 0 0 3px color-mix(in srgb, var(--svc-c) 22%, transparent);
}
.svc-pr-ttl { font-weight: 500; font-size: 14px; min-width: 0; overflow-wrap: anywhere; }
.svc-pr-sr { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; }
.svc-pr-what { font-size: 13px; opacity: 0.75; min-width: 0; }
.svc-pr-beat { display: block; font-size: 12px; opacity: 0.8; }
.svc-pr-tags { display: flex; flex-wrap: wrap; gap: 6px; justify-content: flex-end; }
.svc-pr-tag {
	font-size: 11.5px;
	padding: 1px 8px;
	border-radius: 10px;
	border: 1px solid var(--wf-line);
	white-space: nowrap;
	opacity: 0.85;
}
.svc-pr-tag--safe { color: #7e57c2; border-color: rgba(126, 87, 194, 0.55); background: rgba(126, 87, 194, 0.12); opacity: 1; }
.theme--dark .svc-pr-tag--safe { color: #b79cf0; }
.svc-pr-tag--own { color: var(--wf-ok, #43a047); border-color: rgba(67, 160, 71, 0.5); background: rgba(67, 160, 71, 0.1); opacity: 1; }
.svc-pr-tag--late { color: var(--wf-warn, #fb8c00); border-color: rgba(251, 140, 0, 0.55); background: rgba(251, 140, 0, 0.1); opacity: 1; }
.svc-pr-tag--bad { color: var(--wf-err, #e53935); border-color: rgba(229, 57, 53, 0.55); background: rgba(229, 57, 53, 0.1); opacity: 1; }
.svc-pr-tag--paused { color: #fff; border-color: #546e7a; background: #546e7a; font-weight: 600; opacity: 1; }
.theme--dark .svc-pr-tag--paused { color: #fff; }
.svc-pr-tag--paused .v-icon { color: inherit; }
.svc-pr-done { display: flex; align-items: flex-start; margin-top: 8px; font-size: 13px; color: var(--wf-c-success-text, #2e7d32); }
.theme--dark .svc-pr-done { color: #81c784; }
.svc-pr-chev { transition: transform 0.15s; opacity: 0.7; }
.svc-pr-head[aria-expanded="true"] .svc-pr-chev { transform: rotate(90deg); }
@media (prefers-reduced-motion: reduce) { .svc-pr-chev { transition: none; } }
.svc-pr-relay { margin: 0 14px 8px 38px; }
.svc-pr-lasterr { margin: 0 14px 8px 38px; font-size: 12px; color: var(--wf-warn, #fb8c00); word-break: break-word; }
.svc-pr-detail { padding: 4px 14px 14px 38px; }
.svc-pr-facts {
	display: grid;
	gap: 10px 22px;
	grid-template-columns: repeat(auto-fit, minmax(230px, 1fr));
	margin: 0 0 10px;
}
.svc-pr-facts dt { font-size: 12px; opacity: 0.65; margin-bottom: 1px; }
.svc-pr-facts dd { margin: 0; font-size: 13.5px; line-height: 1.4; word-break: break-word; }
.svc-pr-line { font-size: 12px; margin-top: 6px; word-break: break-word; }
.svc-pr-metrics span { margin-right: 12px; white-space: nowrap; }
.svc-pr-pace { margin-top: 8px; }
.svc-pr-chart {
	display: grid;
	grid-template-columns: repeat(auto-fit, minmax(190px, 1fr));
	gap: 10px;
	margin-top: 8px;
}
.svc-pr-err { color: var(--wf-c-error-text, #ef9a9a); }
.svc-pr-err-old { opacity: 0.75; }
.svc-lock-ico { opacity: 0.7; }
/* the reason of one group hugs its text: the blink rings the words, not the whole width of the card */
.svc-lock-group .svc-lock-reason { display: inline-flex; width: fit-content; max-width: 100%; padding: 2px 8px; border-radius: 6px; }
.svc-pr-ctl { margin-top: 10px; padding-top: 10px; border-top: 1px dashed var(--wf-line); }
@media (max-width: 760px) {
	.svc-pr-head { grid-template-columns: 14px 1fr 18px; }
	.svc-pr-what, .svc-pr-tags { grid-column: 2 / 3; justify-content: flex-start; }
	.svc-pr-detail { padding-left: 14px; }
	.svc-pr-relay, .svc-pr-lasterr { margin-left: 14px; }
}
</style>
