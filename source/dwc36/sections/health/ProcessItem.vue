<template>
	<!-- One process (or one separate service) as a row that opens: its state with the cause, what it does, what the person can do
	     and, last, the technical detail (the only place where its id is shown).
	     Props: item (sections/health/view.js), open, marked (the address points at it), stale (the service is stopped or restarting),
	            vision ({ status, data } of the Vision read: only the row of Vision uses it).
	     Events: toggle (open), sign-in. The body is built only while the row is open. -->
	<details :id="'svc-proc-' + item.id" class="sv-item" :open="open" :data-open="open ? '' : null" :data-word="item.word" :data-marked="marked ? '' : null" @toggle="$emit('toggle', $event.target.open)">
		<summary>
			<span class="mdi mdi-chevron-right sv-ico sv-chev" aria-hidden="true" />
			<span class="sv-dot-state" :data-level="look.level" aria-hidden="true" />
			<span class="sv-item-main"><b>{{ title }}</b><small :title="line">{{ line }}</small></span>
			<span class="sv-item-chips" data-part="chips">
				<span v-if="item.safety" class="sv-chip-sm sv-chip-safety" data-chip="safety"><span class="mdi mdi-shield-lock-outline sv-ico sv-ico-s" aria-hidden="true" />{{ t('health.chip_safety') }}</span>
				<span v-if="modeChip" class="sv-chip-sm" data-chip="mode">{{ modeChip }}</span>
				<span v-if="ageChip" class="sv-chip-sm" data-chip="age">{{ ageChip }}</span>
				<span class="sv-state" :data-level="look.level" data-part="state"><span class="mdi sv-ico sv-ico-s" :class="look.icon" aria-hidden="true" />{{ t('health.word_' + item.word) }}</span>
			</span>
		</summary>
		<div v-if="open" class="sv-item-body">
			<h3 class="sv-h3">{{ t('health.blk_state') }}</h3>
			<p data-part="reason">{{ reasonText || t('health.reason_fine') }}</p>
			<dl v-if="facts.length" class="sv-facts sv-facts-grid">
				<template v-for="f in facts"><dt :key="f.id + 'k'">{{ f.name }}</dt><dd :key="f.id + 'v'" :data-fact="f.id"><span class="sv-chip-sm">{{ f.value }}</span></dd></template>
			</dl>
			<p v-if="item.id === 'vision'" class="sv-quiet" data-part="vision">{{ visionLine }}</p>

			<template v-if="docs.length || description">
				<h3 class="sv-h3">{{ t('health.blk_about') }}</h3>
				<p v-if="description && !docs.length">{{ description }}</p>
				<dl v-else class="sv-facts">
					<template v-for="d in docs"><dt :key="d.id + 'k'">{{ d.name }}</dt><dd :key="d.id + 'v'">{{ d.text }}</dd></template>
				</dl>
			</template>

			<h3 class="sv-h3">{{ t('health.blk_do') }}</h3>
			<p v-if="item.kind === 'separate'" data-part="where">{{ t('health.sep_where') }} <a v-if="place" class="wf-btn sv-btn sv-text" :href="nav.href(place)" @click="follow($event, place)">{{ t('health.sep_go_' + item.id) }}</a></p>
			<template v-else>
				<p v-if="pendingStuck" class="sv-field-error" role="alert" data-part="stuck"><span class="mdi mdi-alert-outline sv-ico sv-ico-s" aria-hidden="true" />{{ t('health.restart_stuck') }}
					<a class="wf-btn sv-btn sv-text" :href="nav.href(SERVICE_PLACE)" @click="follow($event, SERVICE_PLACE)">{{ t('health.restart_stuck_go') }}</a></p>
				<p v-else-if="item.restartPending" class="sv-quiet" role="status" data-part="pending"><span class="sv-spin" aria-hidden="true" />{{ t('health.restart_pending') }}</p>
				<p v-if="!item.pausable" class="sv-quiet" data-part="no-controls">{{ t(item.safety ? 'health.no_controls_safety' : 'health.no_controls') }}</p>
				<ul class="sv-rows">
					<template v-if="item.pausable">
						<sv-action-row v-if="item.word === 'paused'" icon="mdi-play-circle-outline" :name="t('health.resume_name')" :desc="t('health.resume_desc')" :action="resume" :permission="perm('processes.resume')" :stale="stale"
							:label="t('health.resume')" @run="resume.run()" @retry="resume.run()" />
						<sv-action-row v-else icon="mdi-pause-circle-outline" :name="t('health.pause_name')" :desc="t('health.pause_desc')" :action="pause" :permission="perm('processes.pause')" :stale="stale"
							:label="t('health.pause')" :arm-label="t('health.pause_arm')" @run="pause.run()" @retry="pause.run()" />
						<sv-action-row icon="mdi-restart" :name="t('health.restart_name')" :desc="t('health.restart_desc')" :action="restart" :permission="perm('processes.restart')" :stale="stale || item.restartPending"
							:label="t('health.restart')" :arm-label="t('health.restart_arm')" @run="restart.run()" @retry="restart.run()" />
					</template>
					<sv-action-row v-if="!item.safety" icon="mdi-tune-variant" :name="t('health.mode_name')" :desc="modeDesc" :action="mode" :permission="perm('modules.set')" :stale="stale" @retry="setMode(item.mode)">
						<template #control="c">
							<span class="sv-seg" role="group" :aria-label="t('health.mode_name')">
								<button v-for="m in MODES" :key="m" type="button" :aria-pressed="item.mode === m ? 'true' : 'false'" :disabled="c.disabled" :data-mode="m" @click="setMode(m)">{{ t('health.mode_' + m) }}</button>
							</span>
						</template>
						<p v-if="waitsRestart" class="sv-row-desc" role="status" data-part="waits">{{ t('health.mode_waits') }}</p>
					</sv-action-row>
				</ul>
				<lock-reason class="sv-lock" :lock="lock" />
			</template>

			<details class="sv-disclose" data-part="tech">
				<summary><span class="mdi mdi-code-braces sv-ico sv-ico-s" aria-hidden="true" />{{ t('health.blk_tech') }}</summary>
				<dl>
					<dt>{{ t('health.tech_id') }}</dt><dd><code class="sv-code">{{ item.id }}</code></dd>
					<template v-for="f in tech"><dt :key="f.id + 'k'">{{ f.name }}</dt><dd :key="f.id + 'v'">{{ f.value }}</dd></template>
				</dl>
			</details>
		</div>
	</details>
</template>

<script>
import { t, tc, te } from '../../core/dwc.js'
import { can } from '../../core/store/session.js'
import { modeAction, processAction } from '../../core/actions/processes.js'
import { durationText } from '../../core/format/duration.js'
import { serviceText } from '../../service-text.js'
import SvActionRow from '../../ui/SvActionRow.vue'
import LockReason from '../../LockReason.vue'
import { MODES, RESTART_STUCK_S, readableId, reasonOf } from './view.js'

const LOOK = {
	fine: { level: 'ok', icon: 'mdi-check-circle-outline' }, resting: { level: 'rest', icon: 'mdi-sleep' }, paused: { level: 'rest', icon: 'mdi-pause-circle-outline' },
	unchecked: { level: 'rest', icon: 'mdi-help-circle-outline' }, unknown: { level: 'warn', icon: 'mdi-alert-outline' }, late: { level: 'warn', icon: 'mdi-alert-outline' },
	errors: { level: 'warn', icon: 'mdi-alert-outline' }, stopped: { level: 'error', icon: 'mdi-close-circle-outline' }
}
// the ids the catalogs know the separate services by (area procDocs, synced with the service)
const DOC_ID = { vision: 'ext_WorkshopVision', rs485: 'ext_WorkshopRS485', bridge: 'ext_bridge', database: 'ext_base' }
const PLACES = { bridge: { s: 'links', t: 'bridge' }, database: { s: 'data', t: 'db' } }
const DOCS = 'plugins.WorkshopService.procDocs.'
const dur = s => durationText(s, (k, p) => t('kit.' + k, p))

export default {
	name: 'ProcessItem',
	components: { SvActionRow, LockReason },
	inject: { nav: { from: 'svNav', default: () => ({ go() {}, href: () => '#' }) } },
	props: {
		item: { type: Object, required: true },
		open: { type: Boolean, default: false },
		marked: { type: Boolean, default: false },
		stale: { type: Boolean, default: false },
		vision: { type: Object, default: null }
	},
	data() {
		return { MODES, SERVICE_PLACE: { s: 'health', t: 'processes', a: 'sv-service' } }
	},
	computed: {
		title() {
			if (this.item.kind === 'separate') return this.item.title ? serviceText(this.item.title) : t('health.sep_' + this.item.id)
			return this.item.title ? serviceText(this.item.title) : readableId(this.item.id)
		},
		description() {
			return this.item.description ? serviceText(this.item.description) : ''
		},
		look() {
			return LOOK[this.item.word] || LOOK.unknown
		},
		reasonText() {
			const r = reasonOf(this.item)
			if (!r) return ''
			if (r.n !== null) return tc('health.' + r.key, r.n)
			const p = r.params || {}
			return t('health.' + r.key, { age: dur(p.ageS), expected: dur(p.expectedS), error: p.error, hour: p.hour })
		},
		// the one line of the closed row: why it needs a look, else what it does
		line() {
			return this.item.level > 0 || this.item.word === 'paused' ? this.reasonText : this.description || this.reasonText
		},
		// the age of the last good cycle ("5 s ago") and the mode (Automatic / Always / Never) as chips on the closed row
		ageChip() {
			const p = this.item.process
			return p && typeof p.age_ok_s === 'number' ? t('health.fact_ago', { t: dur(p.age_ok_s) }) : ''
		},
		modeChip() {
			return this.item.kind === 'process' && !this.item.safety && MODES.indexOf(this.item.mode) >= 0 ? t('health.mode_' + this.item.mode) : ''
		},
		facts() {
			const p = this.item.process
			if (!p) return []
			const out = [{ id: 'state', name: t('health.blk_state'), value: t('health.word_' + this.item.word) }]
			if (this.modeChip) out.push({ id: 'mode', name: t('health.mode_name'), value: this.modeChip })
			if (typeof p.age_ok_s === 'number') out.push({ id: 'beat', name: t('health.fact_beat'), value: t('health.fact_ago', { t: dur(p.age_ok_s) }) })
			if (p.expected_s) out.push({ id: 'cadence', name: t('health.fact_cadence'), value: t('health.fact_every', { t: dur(p.expected_s) }) })
			if (typeof p.active_s === 'number') out.push({ id: 'active', name: t('health.fact_active'), value: dur(p.active_s) })
			if (p.error && this.item.word !== 'errors') out.push({ id: 'error', name: t('health.fact_last_error'), value: (p.error_hour ? p.error_hour + ' · ' : '') + p.error })
			if (p.restarts) out.push({ id: 'restarts', name: t('health.fact_restarts'), value: String(p.restarts) })
			return out
		},
		docs() {
			const base = this.item.kind === 'separate' ? DOC_ID[this.item.id] : this.item.id
			const parts = this.item.kind === 'separate' ? ['what', 'how', 'depends', 'why'] : ['what', 'why', 'fails', 'uses', 'where']
			return parts.filter(k => te(DOCS + base + '_' + k)).map(k => ({ id: k, name: t('health.doc_' + k), text: t(DOCS + base + '_' + k) }))
		},
		tech() {
			const p = this.item.process || {}
			const m = this.item.module || {}
			const out = [{ id: 'kind', name: t('health.tech_kind'), value: t(this.item.kind === 'separate' ? 'health.tech_kind_separate' : 'health.tech_kind_process') }]
			if (m.effective) out.push({ id: 'effective', name: t('health.tech_effective'), value: t('health.effective_' + (['running', 'idle', 'forced'].indexOf(m.effective) >= 0 ? m.effective : 'other')) })
			if (typeof p.cpu_pct === 'number') out.push({ id: 'cpu', name: t('health.tech_cpu'), value: p.cpu_pct + ' %' })
			if (typeof p.interval_avg === 'number') out.push({ id: 'interval', name: t('health.tech_interval'), value: p.interval_avg + ' s' + (typeof p.interval_max === 'number' ? ' (' + t('health.tech_max', { v: p.interval_max }) + ')' : '') })
			return out
		},
		place() {
			return PLACES[this.item.id] || null
		},
		pause() { return processAction('pause', this.item.id) },
		resume() { return processAction('resume', this.item.id) },
		restart() { return processAction('restart', this.item.id) },
		mode() { return modeAction(this.item.id) },
		waitsRestart() {
			return !!(this.item.module && this.item.module.pending_restart)
		},
		modeDesc() {
			return t(this.item.module && this.item.module.live === true ? 'health.mode_desc_live' : 'health.mode_desc')
		},
		// the service still shows the restart as pending after a minute, or the page waited that long for it
		pendingStuck() {
			const e = this.restart.state === 'error' && this.restart.error
			return (this.item.restartPending && this.item.restartS > RESTART_STUCK_S) || !!(e && e.code === 'unverified')
		},
		// ONE sentence for the block
		lock() {
			const ops = (this.item.pausable ? ['processes.restart'] : []).concat(this.item.safety ? [] : ['modules.set'])
			const all = ops.map(op => can(op))
			return all.find(c => c.state === 'session') || all.find(c => c.state === 'role') || null
		},
		visionLine() {
			const v = this.vision
			if (!v || v.status === 'locked') return t('health.vision_unchecked')
			if (v.status === 'error') return t('health.vision_failed', { why: (v.error && v.error.message) || '' })
			const d = v.data
			if (!d) return t('health.vision_reading')
			const n = Object.keys(d.calibs || {}).length
			return t('health.vision_detail', { opencv: d.opencv || '?' }) + ' ' + (n ? tc('health.vision_calibs', n) : t('health.vision_no_calibs'))
		}
	},
	methods: {
		t,
		perm(op) {
			return can(op)
		},
		setMode(m) {
			if (m === this.item.mode && this.mode.state !== 'error') return
			this.mode.run({ process: this.item.id, mode: m })
		},
		follow(e, place) {
			if (e && (e.ctrlKey || e.metaKey || e.shiftKey || e.altKey || e.button > 0)) return
			if (e && typeof e.preventDefault === 'function') e.preventDefault()
			this.nav.go(place)
		}
	}
}
</script>
