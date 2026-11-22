<template>
	<!-- Home: one verdict, the ONE list of what needs a look, what the machine is doing now, and the everyday actions.
	     Everything it shows is published by the service (plus one read with a session: the steps of the start-up). The verdict, the chip of
	     the header and the counts of the navigation come from the same model (model.js). Prop: active (this section is the one in view). -->
	<div class="sv-home" :class="{ 'sv-stale': !m.state.running }">
		<sv-verdict :level="m.verdict.level" :title="tc('home.' + m.verdict.key, m.verdict.n)" :facts="facts" :old="dataOld" />

		<section class="sv-card" aria-labelledby="sv-home-attn">
			<div class="sv-card-head"><h2 id="sv-home-attn"><span class="mdi mdi-bell-outline sv-ico" aria-hidden="true" />{{ t('home.attn_title') }}</h2></div>
			<p v-if="!m.state.running" class="sv-quiet">{{ t('home.stopped_note') }}</p>
			<p v-else-if="!m.rows.length && !m.readinessFailed" class="sv-quiet">{{ t('home.attn_none') }}</p>
			<ul v-else class="sv-attn">
				<li v-for="r in m.rows" :key="r.id" :data-level="r.level" :data-row="r.id">
					<span class="sv-level"><span class="mdi sv-ico sv-ico-s" :class="r.level === 'error' ? 'mdi-close-circle-outline' : 'mdi-alert-outline'" aria-hidden="true" />{{ t(r.level === 'error' ? 'home.level_error' : 'home.level_warn') }}</span>
					<span class="sv-attn-text">{{ rowText(r) }}</span>
					<a v-if="r.to" class="wf-btn sv-btn sv-text" :href="nav.href(r.to)" @click="follow($event, r.to)">{{ t('home.go_' + r.to.s + (r.to.t ? '_' + r.to.t : '')) }}</a>
				</li>
			</ul>
			<p v-if="m.state.running && visitor" class="sv-quiet sv-home-note">{{ t('home.attn_visitor') }}</p>
			<p v-if="m.readinessFailed" class="sv-quiet sv-home-note" role="status">{{ t('home.setup_unknown') }} <button type="button" class="wf-btn sv-btn sv-text" @click="readiness.reload()">{{ t('kit.retry') }}</button></p>
		</section>

		<div class="sv-cols">
			<section class="sv-card" aria-labelledby="sv-home-now">
				<div class="sv-card-head"><h2 id="sv-home-now"><span class="mdi mdi-clock-outline sv-ico" aria-hidden="true" />{{ t('home.now_title') }}</h2></div>
				<dl class="sv-facts">
					<template v-for="f in now"><dt :key="f.id + '-k'">{{ f.name }}</dt><dd :key="f.id + '-v'" :data-fact="f.id">{{ f.value }}</dd></template>
				</dl>
			</section>

			<section class="sv-card" aria-labelledby="sv-home-act">
				<div class="sv-card-head"><h2 id="sv-home-act"><span class="mdi mdi-gesture-tap-button sv-ico" aria-hidden="true" />{{ t('home.act_title') }}</h2></div>
				<ul class="sv-rows">
					<sv-action-row icon="mdi-power" :name="t('home.after_job_name')" :desc="armed === null ? t('home.after_job_unknown') : t('home.after_job_desc')" :action="afterJob" :permission="perm('power.after_job')" :stale="stale" @retry="toggleAfterJob">
						<template #control="c">
							<sv-switch :checked="armed === true" :word="c.armed ? t('home.arm_again') : t(armed === null ? 'home.word_unknown' : armed ? 'home.word_armed' : 'home.word_not_armed')" :label="t('home.after_job_name')"
								:state="c.state" :disabled="c.disabled || armed === null" @toggle="toggleAfterJob" @hold="on => held(c, on)" @escape="c.cancel" />
						</template>
					</sv-action-row>
					<sv-action-row icon="mdi-timer-outline" :name="t('home.timer_name')" :desc="timerDesc" :action="timerSet ? timerCancel : timer" :permission="perm(timerSet ? 'power.timer_cancel' : 'power.timer')" :stale="stale"
						:label="timerSet ? t('home.timer_cancel') : t('home.timer_schedule')" :arm-label="t('home.timer_arm')" @run="runTimer" @retry="runTimer">
						<p v-if="timerNote" class="sv-row-desc" role="status">{{ timerNote }}</p>
						<template v-if="!timerSet && perm('power.timer').state === 'ok'">
							<p v-if="otherBad" class="sv-field-error" role="alert"><span class="mdi mdi-alert-outline sv-ico sv-ico-s" aria-hidden="true" />{{ t('home.timer_invalid') }}</p>
						</template>
						<template v-if="!timerSet && perm('power.timer').state === 'ok'" #ctl-before>
							<span class="sv-seg" role="group" :aria-label="t('home.timer_pick')" data-part="timer-pick">
								<button v-for="n in options" :key="n" type="button" :aria-pressed="pick === String(n) ? 'true' : 'false'" :disabled="stale" @click="pick = String(n)">{{ minutesLabel(n) }}</button>
								<button type="button" :aria-pressed="pick === 'other' ? 'true' : 'false'" :disabled="stale" data-pick="other" @click="pick = 'other'">{{ t('home.timer_other') }}</button>
							</span>
							<label v-if="pick === 'other'" class="sv-field sv-field-short"><span class="sv-vh">{{ t('home.timer_field') }}</span>
								<input v-model="other" type="text" inputmode="numeric" maxlength="3" :placeholder="t('home.timer_field')" :aria-label="t('home.timer_field')" :aria-invalid="otherBad ? 'true' : null" :disabled="stale">
							</label>
						</template>
					</sv-action-row>
					<sv-action-row icon="mdi-stop-circle-outline" :name="t('home.close_name')" :desc="jobOpen ? t('home.close_desc') : t('home.close_none')" :action="closeJob" :permission="perm('job.close')" :stale="stale"
						:label="jobOpen ? t('home.close_label') : ''" :arm-label="t('home.close_arm')" @run="closeJob.run()" @retry="closeJob.run()" />
					<sv-action-row icon="mdi-weather-windy" :name="t('home.air_name')" :desc="t('home.air_desc')" :action="airAuto" :permission="perm('air.auto')" :stale="stale" @retry="toggleAir">
						<template #control="c">
							<sv-switch :checked="air === true" :word="t(air === null ? 'home.word_unknown' : air ? 'home.word_on' : 'home.word_off')" :label="t('home.air_name')" :state="c.state" :disabled="c.disabled || air === null" @toggle="toggleAir" />
						</template>
					</sv-action-row>
				</ul>
				<lock-reason class="sv-lock" :lock="blockLock" />
				<p class="sv-quiet sv-home-note"><a class="wf-btn sv-btn sv-text" :href="nav.href({ s: 'machine', t: 'auto' })" @click="follow($event, { s: 'machine', t: 'auto' })">{{ t('home.more_in_machine') }}</a></p>
			</section>
		</div>
	</div>
</template>

<script>
import { t, tc, locale, machineMode, machineStatus } from '../../core/dwc.js'
import { clock } from '../../core/clock.js'
import { get, liveJob, motion, powerOffOnFinish, receivedAt, serviceProcess, serviceVersion, shutdownTimer } from '../../core/live/published.js'
import { can, session, signIn } from '../../core/store/session.js'
import { readiness } from '../../core/resources.js'
import { afterJob, airAuto, closeJob, timer, timerCancel } from '../../core/actions/today.js'
import { ageSeconds, durationText } from '../../core/format/duration.js'
import { time as clockTime, toMs } from '../../core/format/dates.js'
import { serviceText } from '../../service-text.js'
import SvActionRow from '../../ui/SvActionRow.vue'
import LockReason from '../../LockReason.vue'
import SvSwitch from '../../ui/SvSwitch.vue'
import SvVerdict from '../../ui/SvVerdict.vue'
import { homeModel } from './model.js'
import { minutesLeft, movementKey, timerMinutes } from './view.js'

const OPS = ['power.after_job', 'power.timer', 'job.close', 'air.auto']
const AGE_SHOWN_S = 45
const AGE_OLD_S = 120
const STATUS = ['idle', 'processing', 'paused', 'pausing', 'resuming', 'busy', 'off', 'halted', 'simulating', 'cancelling', 'starting', 'updating', 'changingTool', 'disconnected']

export default {
	name: 'HomeSection',
	components: { SvActionRow, LockReason, SvSwitch, SvVerdict },
	inject: { nav: { from: 'svNav', default: () => ({ go() {}, href: () => '#' }) } },
	props: { active: { type: Boolean, default: false } },
	data() {
		return { afterJob, airAuto, closeJob, timer, timerCancel, readiness, options: [15, 30, 60, 120], pick: '30', other: '', tried: false, timerNote: '' }
	},
	computed: {
		m() {
			return homeModel()
		},
		visitor() {
			return session.state !== 'active' && session.state !== 'resolving'
		},
		stale() {
			return !this.m.state.running || this.m.state.restarting      // while the service restarts nothing is written
		},
		ageS() {
			return ageSeconds(receivedAt('servicesInternal'), clock.now)
		},
		dataOld() {
			return this.stale || (this.ageS !== null && this.ageS > AGE_OLD_S)
		},
		facts() {
			const out = []
			const dur = s => durationText(s, (k, p) => t('kit.' + k, p))
			const p = serviceProcess()
			if (serviceVersion()) out.push(t('home.fact_version', { v: serviceVersion() }))
			if (get('serviceStarted')) out.push(t('home.fact_since', { when: String(get('serviceStarted')).slice(0, 16) }))
			if (this.m.state.running && p && typeof p.age_s === 'number') out.push(t('home.fact_uptime', { t: dur(p.age_s) }))
			if (this.ageS !== null && (this.ageS > AGE_SHOWN_S || this.stale)) out.push(t('home.fact_age', { t: dur(this.ageS) }))
			return out
		},
		now() {
			const mo = motion() || {}
			const job = liveJob() || {}
			const status = machineStatus()
			const who = session.name ? t('shell.session_who', { name: session.name, role: this.roleName(session.roleName || session.role) }) : t(session.unknown ? 'shell.session_unknown' : this.visitor ? 'home.now_nobody' : 'shell.session_open')
			const owner = mo.owner && (mo.owner.name || mo.owner.origin) ? ' · ' + [mo.owner.name, mo.owner.origin].filter(Boolean).join(', ') : ''
			const jobName = (mo.job && mo.job.name) || (job.active ? job.name || t('home.now_job_live') : '')
			return [
				{ id: 'machine', name: t('home.now_machine'), value: [status ? t(STATUS.indexOf(status) >= 0 ? 'home.status_' + status : 'home.status_other', { status }) : t('home.word_unknown'), machineMode()].filter(Boolean).join(' · ') },
				{ id: 'movement', name: t('home.now_movement'), value: mo.state ? t('home.' + movementKey(mo.state)) + owner : t('home.word_unknown') },
				{ id: 'job', name: t('home.now_job'), value: jobName ? jobName + (job.active && job.since ? ' · ' + t('home.now_since', { time: clockTime(toMs(job.since), locale()).slice(0, 5) }) : '') : t('home.now_no_job') },
				{ id: 'programs', name: t('home.now_programs'), value: tc('home.now_programs_n', (mo.bridge && mo.bridge.clients) || 0) },
				{ id: 'who', name: t('home.now_who'), value: who }
			]
		},
		armed() {
			return powerOffOnFinish()
		},
		air() {
			const v = get('airAssistAuto')
			return typeof v === 'boolean' ? v : null
		},
		jobOpen() {
			const j = liveJob()
			return !!(j && j.active)
		},
		timerSet() {
			return shutdownTimer()
		},
		otherBad() {
			return this.pick === 'other' && (this.other !== '' || this.tried) && timerMinutes(this.other) === null
		},
		timerDesc() {
			const ti = this.timerSet
			if (!ti) return t('home.timer_desc')
			const mo = motion()
			const base = t('home.timer_scheduled', { time: ti.until, n: minutesLeft(ti.missing_s) })
			return mo && mo.job && mo.job.kind ? base + ' ' + t('home.timer_with_job') : base
		},
		// ONE sentence for the block: the highest cause among its controls (no session before a role that is too low)
		blockLock() {
			const all = OPS.map(op => can(op))
			return all.find(c => c.state === 'session') || all.find(c => c.state === 'role') || null
		}
	},
	watch: {
		active: { immediate: true, handler(on) { if (on) readiness.show(); else readiness.hide() } },
		// the timer ran out while a job was running: the service removed it and armed "power off when the job ends"; said once, here
		timerSet(nowSet, was) {
			// the row changes of action with its datum (schedule <-> cancel): the "done" of the one that just ended is not said under the other
			const ended = nowSet ? this.timer : this.timerCancel
			const other = nowSet ? this.timerCancel : this.timer
			if (other.state === 'done') other.reset()
			if (ended.state === 'done' && !!nowSet !== !!was) ended.reset()
			if (nowSet) { this.timerNote = ''; return }
			if (was && this.active && this.timerCancel.state === 'idle' && this.armed === true) this.timerNote = t('home.timer_became_after_job')
		}
	},
	methods: {
		t,
		tc,
		signIn,
		perm(op) {
			return can(op)
		},
		roleName(role) {
			return ['viewer', 'operator', 'technician', 'admin'].indexOf(role) >= 0 ? t('api.role_' + role) : String(role || '')
		},
		rowText(r) {
			if (r.service) return serviceText(r.service) + (r.params && r.params.until ? ' ' + t('home.attn_until', { time: clockTime(toMs(r.params.until), locale()).slice(0, 5) }) : '')
			return r.n === null ? t('home.' + r.key, r.params) : tc('home.' + r.key, r.n, r.params)
		},
		follow(e, place) {
			if (e && (e.ctrlKey || e.metaKey || e.shiftKey || e.altKey || e.button > 0)) return
			if (e && typeof e.preventDefault === 'function') e.preventDefault()
			this.nav.go(place)
		},
		// keyboard focus holds an armed switch; when the focus leaves, it is disarmed at once
		held(c, on) {
			c.hold(on)
			if (!on) c.cancel()
		},
		toggleAfterJob() {
			if (this.armed === null) return
			this.afterJob.run({ armed: !this.armed })
		},
		toggleAir() {
			if (this.air === null) return
			this.airAuto.run({ on: !this.air })
		},
		minutesLabel(n) {
			return n % 60 === 0 ? t('home.timer_hours', { n: n / 60 }) : t('home.timer_min', { n })
		},
		runTimer() {
			if (this.timerSet) return this.timerCancel.run()
			const minutes = this.pick === 'other' ? timerMinutes(this.other) : Number(this.pick)
			this.tried = true
			if (minutes === null) return      // nothing valid typed: the field says what it takes, nothing is sent
			this.timer.run({ minutes })
		}
	}
}
</script>
