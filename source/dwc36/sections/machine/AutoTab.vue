<template>
	<!-- Machine > Automations: everything the machine does by itself, in cards by purpose. Each row shows its REAL value (also when it is
	     locked: then it is a state) and its control, with a four-line help; each card has ONE lock sentence at its foot.
	     The rows of "when a job ends" and "live job" are the ones of the home (the same action objects).
	     Prop: active (this tab is in view). -->
	<div class="sv-machine-auto">
		<p class="sv-lead">{{ t('machine.lead') }}</p>

		<section class="sv-card" aria-labelledby="sv-ma-finish" data-card="finish">
			<div class="sv-card-head"><h2 id="sv-ma-finish"><span class="mdi mdi-flag-checkered sv-ico" aria-hidden="true" />{{ t('machine.finish_title') }}</h2></div>
			<ul class="sv-rows">
				<sv-action-row icon="mdi-power" :name="t('home.after_job_name')" :desc="armed === null ? t('home.after_job_unknown') : t('home.after_job_desc')" :action="afterJob" :permission="perm('power.after_job')" :stale="stale" @retry="toggleAfterJob">
					<template #control="c">
						<sv-switch :checked="armed === true" :word="c.armed ? t('home.arm_again') : t(armed === null ? 'home.word_unknown' : armed ? 'home.word_armed' : 'home.word_not_armed')" :label="t('home.after_job_name')"
							:state="c.state" :disabled="c.disabled || armed === null" @toggle="toggleAfterJob" @hold="on => held(c, on)" @escape="c.cancel" />
					</template>
					<template #help><sv-help v-bind="help('poweroff')" /></template>
				</sv-action-row>
				<sv-action-row icon="mdi-timer-outline" :name="t('machine.idle_name')" :desc="t('machine.idle_desc')" :action="moveIdle" :permission="perm('movement.lock')" :stale="stale" @retry="moveIdle.run({ idle_s: lastIdle })">
					<template #control="c">
						<span class="sv-seg" role="group" :aria-label="t('machine.idle_label')">
							<button v-for="s in idles" :key="s" type="button" :aria-pressed="move.idle_s === s ? 'true' : 'false'" :disabled="c.disabled" :data-idle="s" @click="setIdle(s)">{{ idleText(s) }}</button>
						</span>
					</template>
					<template #help><sv-help v-bind="help('idle')" /></template>
				</sv-action-row>
			</ul>
			<sv-reason :lock="lockOf(['power.after_job', 'movement.lock'])" @sign-in="signIn" />
		</section>

		<section class="sv-card" aria-labelledby="sv-ma-move" data-card="movement">
			<div class="sv-card-head"><h2 id="sv-ma-move"><span class="mdi mdi-steering sv-ico" aria-hidden="true" />{{ t('machine.move_title') }}</h2></div>
			<ul class="sv-rows">
				<sv-action-row icon="mdi-steering" :name="t('machine.move_name')" :desc="t('machine.move_desc')" :action="moveMode" :permission="perm('movement.lock')" :stale="stale"
					:label="move.mode === 'protected' ? t('machine.move_to_duet') : move.mode === 'duet' ? t('machine.move_to_protected') : ''" :arm-label="t('machine.move_arm')" @run="changeMode" @retry="changeMode">
					<span class="sv-value"><span class="mdi sv-ico" :class="move.mode === 'protected' ? 'mdi-check-circle-outline' : 'mdi-alert-outline'" aria-hidden="true" />{{ t(move.mode === 'protected' ? 'machine.move_is_protected' : move.mode === 'duet' ? 'machine.move_is_duet' : 'machine.word_unknown') }}</span>
					<template #help><sv-help v-bind="help('motion')" /></template>
				</sv-action-row>
			</ul>
			<details class="sv-fold">
				<summary><span class="mdi mdi-chevron-right sv-ico sv-chev" aria-hidden="true" /><span class="sv-fold-name">{{ t('machine.advanced') }}</span><span class="sv-fold-sum">{{ t('machine.release_sum') }}</span></summary>
				<div class="sv-fold-body"><ul class="sv-rows">
					<sv-action-row icon="mdi-timer-sand" :name="t('machine.release_name')" :desc="t('machine.release_desc')" :action="moveRelease" :permission="perm('movement.lock')" :stale="stale" @retry="moveRelease.run({ release_s: lastRelease })">
						<template #control="c">
							<span class="sv-seg" role="group" :aria-label="t('machine.release_name')">
								<button v-for="s in releases" :key="s" type="button" :aria-pressed="move.release_s === s ? 'true' : 'false'" :disabled="c.disabled || move.mode !== 'protected'" :data-release="s" @click="setRelease(s)">{{ secs(s) }}</button>
							</span>
						</template>
					</sv-action-row>
				</ul></div>
			</details>
			<sv-reason :lock="lockOf(['movement.lock'])" @sign-in="signIn" />
		</section>

		<section class="sv-card" aria-labelledby="sv-ma-laser" data-card="laser">
			<div class="sv-card-head"><h2 id="sv-ma-laser"><span class="mdi mdi-laser-pointer sv-ico" aria-hidden="true" />{{ t('machine.laser_title') }}</h2></div>
			<ul class="sv-rows">
				<sv-action-row icon="mdi-weather-windy" :name="t('home.air_name')" :desc="t('home.air_desc')" :action="airAuto" :permission="perm('air.auto')" :stale="stale" @retry="toggleAir">
					<template #control="c">
						<sv-switch :checked="air === true" :word="t(air === null ? 'home.word_unknown' : air ? 'home.word_on' : 'home.word_off')" :label="t('home.air_name')" :state="c.state" :disabled="c.disabled || air === null" @toggle="toggleAir" />
					</template>
					<template #help><sv-help v-bind="help('air')" /></template>
				</sv-action-row>
				<sv-action-row icon="mdi-timer-outline" :name="t('machine.delay_name')" :desc="t('machine.delay_desc')" :action="airDelay" :permission="perm('air.delay')" :stale="stale" @retry="saveDelay(lastDelay)">
					<template #control="c">
						<span class="sv-seg" role="group" :aria-label="t('machine.delay_name')">
							<button v-for="s in delays" :key="s" type="button" :aria-pressed="delay === s ? 'true' : 'false'" :disabled="c.disabled" :data-delay="s" @click="saveDelay(s)">{{ secs(s) }}</button>
						</span>
						<span class="sv-field sv-field-short"><input v-model="other" type="text" inputmode="decimal" maxlength="5" :disabled="c.disabled" :placeholder="t('machine.delay_other')" :aria-label="t('machine.delay_other')" :aria-invalid="otherBad ? 'true' : null" @keydown.enter.prevent="saveOther"></span>
						<button type="button" class="sv-btn" :class="{ 'sv-save-hot': hasUnsaved }" :disabled="c.disabled || !other" @click="saveOther">{{ t('machine.delay_save') }}</button><sv-unsaved-mark :show="hasUnsaved" />
					</template>
					<span v-if="otherBad" class="sv-field-error" role="alert"><span class="mdi mdi-alert-outline sv-ico sv-ico-s" aria-hidden="true" />{{ t('machine.delay_invalid') }}</span>
					<template #help><sv-help v-bind="help('delay')" /></template>
				</sv-action-row>
			</ul>
			<sv-reason :lock="lockOf(['air.auto', 'air.delay'])" @sign-in="signIn" />
		</section>

		<guard-card />

		<section class="sv-card" aria-labelledby="sv-ma-own" data-card="service">
			<div class="sv-card-head"><h2 id="sv-ma-own"><span class="mdi mdi-robot-outline sv-ico" aria-hidden="true" />{{ t('machine.own_title') }}</h2></div>
			<ul class="sv-rows">
				<sv-action-row icon="mdi-led-strip-variant" :name="t('machine.lights_name')" :desc="t('machine.lights_desc')">
					<span class="sv-value"><span class="mdi sv-ico" :class="lightsAuto ? 'mdi-check-circle-outline' : 'mdi-minus-circle-outline'" aria-hidden="true" />{{ t(lightsAuto ? 'machine.lights_auto' : 'machine.lights_manual') }}</span>
					<button v-if="lightsPage" type="button" class="sv-btn sv-text" @click="openLights">{{ t('machine.lights_open') }}</button>
					<template #help><sv-help v-bind="help('lights')" /></template>
				</sv-action-row>
				<sv-action-row icon="mdi-view-grid-outline" :name="t('machine.zones_name')" :desc="zonesDesc" :action="zonesSet" :permission="perm('bedzones.set')" :stale="stale" :error-text="conflict ? t('machine.zones_conflict') : ''" @retry="keepMine">
					<template #control="c">
						<sv-switch :checked="zones ? zones.enabled : false" :word="t(!zones ? 'machine.word_unknown' : zones.enabled ? 'machine.word_zones_on' : 'machine.word_zones_off')" :label="t('machine.zones_name')"
							:state="c.state" :disabled="c.disabled || !zones" @toggle="toggleZones" />
					</template>
					<p v-if="zones && zones.problems" class="sv-row-desc" data-part="zones-problems">{{ t('machine.zones_problems') }}</p>
					<div v-if="conflict" class="sv-conflict" data-part="conflict">
						<button type="button" class="sv-btn" data-act="see-current" @click="seeCurrent">{{ t('machine.zones_see') }}</button>
					</div>
					<template #help><sv-help v-bind="help('zones')" /></template>
				</sv-action-row>
				<sv-action-row icon="mdi-video-outline" :name="t('machine.relay_name')" :desc="t('machine.relay_desc')" :action="relayAction" :permission="perm(relayRunning ? 'camera.stop' : 'camera.start')" :stale="stale" @retry="toggleRelay">
					<template #control="c">
						<sv-switch :checked="relayRunning === true" :word="relayWord(c)" :label="t('machine.relay_name')" :state="c.state" :disabled="c.disabled || relayRunning === null || relayState === 'nocam'" @toggle="toggleRelay" @hold="on => held(c, on)" @escape="c.cancel" />
					</template>
					<p class="sv-row-desc">{{ t('machine.relay_note') }}</p>
					<template #help><sv-help v-bind="help('relay')" /></template>
				</sv-action-row>
			</ul>
			<sv-reason :lock="lockOf(['bedzones.set', 'camera.stop'])" @sign-in="signIn" />
		</section>

		<section class="sv-card" aria-labelledby="sv-ma-live" data-card="live">
			<div class="sv-card-head"><h2 id="sv-ma-live"><span class="mdi mdi-lan-connect sv-ico" aria-hidden="true" />{{ t('machine.live_title') }}</h2></div>
			<ul class="sv-rows">
				<sv-action-row icon="mdi-stop-circle-outline" :name="t('home.close_name')" :desc="jobOpen ? t('home.close_desc') : t('home.close_none')" :action="closeJob" :permission="perm('job.close')" :stale="stale"
					:label="jobOpen ? t('home.close_label') : ''" :arm-label="t('home.close_arm')" @run="closeJob.run()" @retry="closeJob.run()">
					<template #help><sv-help v-bind="help('live')" /></template>
				</sv-action-row>
			</ul>
			<sv-reason :lock="lockOf(['job.close'])" @sign-in="signIn" />
		</section>
	</div>
</template>

<script>
import { goPath, pathExists } from '../../core/dwc.js'
import { get, liveJob, powerOffOnFinish, processes } from '../../core/live/published.js'
import { want } from '../../core/store/session.js'
import { afterJob, airAuto, closeJob } from '../../core/actions/today.js'
import { airDelay, moveIdle, moveMode, moveRelease, movementSettings, relayStart, relayStop, zonesSet } from '../../core/actions/machine.js'
import { bedZones, cameraRelay } from '../../core/resources.js'
import { statesOf } from '../../core/live/process-state.js'
import SvActionRow from '../../ui/SvActionRow.vue'
import SvHelp from '../../ui/SvHelp.vue'
import SvReason from '../../ui/SvReason.vue'
import SvSwitch from '../../ui/SvSwitch.vue'
import GuardCard from './GuardCard.vue'
import { delayChoices, idleChoices, parseDelay, relayState, secondsParts, zonesArgs, zonesInfo } from './view.js'
import { rowsMixin } from '../../core/rows-mixin.js'
import SvUnsavedMark from '../../ui/SvUnsavedMark.vue'
import { unsavedMixin } from '../../ui/unsaved-mixin.js'
import { saveWithAction } from '../../ui/unsaved-guard.js'

const OPS = ['power.after_job', 'movement.lock', 'air.auto', 'air.delay', 'guard.set', 'bedzones.set', 'camera.stop', 'camera.start', 'job.close', 'camera.status', 'bedzones.get', 'guard.status']
const RELEASES = [10, 20, 30, 60]
const LIGHTS_PAGE = '/Plugins/Lights'

export default {
	name: 'AutoTab',
	components: { GuardCard, SvActionRow, SvHelp, SvReason, SvSwitch, SvUnsavedMark },
	mixins: [rowsMixin, unsavedMixin],
	props: { active: { type: Boolean, default: false } },
	data() {
		return { afterJob, airAuto, closeJob, moveIdle, moveMode, moveRelease, airDelay, zonesSet, other: '', otherTried: false, lastIdle: 0, lastRelease: 0, lastDelay: 0, wantZones: null }
	},
	computed: {
		armed() {
			return powerOffOnFinish()
		},
		air() {
			const v = get('airAssistAuto')
			return typeof v === 'boolean' ? v : null
		},
		delay() {
			const v = get('airAssistDelay')
			return typeof v === 'number' ? v : v === undefined || v === null ? null : Number(v)
		},
		move() {
			return movementSettings()
		},
		idles() {
			return idleChoices(this.move.idle_s)
		},
		releases() {
			const r = this.move.release_s
			return typeof r === 'number' && RELEASES.indexOf(r) < 0 ? RELEASES.concat([r]).sort((a, b) => a - b) : RELEASES
		},
		delays() {
			return delayChoices(this.delay)
		},
		otherBad() {
			return (this.other !== '' || this.otherTried) && parseDelay(this.other) === null
		},
		jobOpen() {
			const j = liveJob()
			return !!(j && j.active)
		},
		lightsAuto() {
			const v = get('statusLightAuto')
			return v === undefined || v === null ? true : !!v
		},
		lightsPage() {
			return pathExists(LIGHTS_PAGE)
		},
		zones() {
			return zonesInfo(bedZones.data)
		},
		zonesDesc() {
			return this.zones && this.zones.zones ? this.tc('machine.zones_desc_n', this.zones.zones, { n: this.zones.zones }) : this.t('machine.zones_desc')
		},
		conflict() {
			const e = zonesSet.state === 'error' && zonesSet.error
			return !!e && e.kind === 'conflict'
		},
		relayWordOfProcess() {
			const s = statesOf(processes()).find(x => x.id === 'camera')
			return s ? s.word : ''
		},
		// the relay as the service reports it (camera.status, operator and above) else as its process shows in the published data
		relayState() {
			return relayState(cameraRelay.data, this.relayWordOfProcess)
		},
		relayRunning() {
			const s = this.relayState
			return s === 'unknown' ? null : s === 'running'
		},
		relayAction() {
			return this.relayRunning ? relayStop : relayStart
		}
	},
	watch: {
		active: { immediate: true, handler(on) { if (on) this.show(); else this.hide() } }
	},
	methods: {
		show() {
			want(OPS)
			bedZones.show()
			cameraRelay.show()
		},
		hide() {
			bedZones.hide()
			cameraRelay.hide()
		},
		secs(s) {
			const p = secondsParts(s)
			return this.t('machine.unit_' + p.unit, { n: p.n })
		},
		idleText(s) {
			return s === 0 ? this.t('machine.idle_never') : this.secs(s)
		},
		toggleAfterJob() {
			if (this.armed === null) return
			this.afterJob.run({ armed: !this.armed })
		},
		toggleAir() {
			if (this.air === null) return
			this.airAuto.run({ on: !this.air })
		},
		setIdle(s) {
			if (s === this.move.idle_s) return
			this.lastIdle = s
			this.moveIdle.run({ idle_s: s })
		},
		setRelease(s) {
			if (s === this.move.release_s) return
			this.lastRelease = s
			this.moveRelease.run({ release_s: s })
		},
		changeMode() {
			if (!this.move.mode) return
			this.moveMode.run({ mode: this.move.mode === 'protected' ? 'duet' : 'protected' })
		},
		saveDelay(s) {
			this.lastDelay = s
			if (s === this.delay) return
			this.airDelay.run({ seconds: s })
		},
		// unsaved changes (unsaved-mixin.js): the delay typed in the free box and not saved yet (the buttons and switches of this tab act at once: nothing to guard there)
		unsavedPair() {
			return [this.other, '']
		},
		saveBeforeLeaving() {
			if (parseDelay(this.other) === null) return false
			return saveWithAction(this.airDelay, () => this.saveOther())
		},
		discardUnsaved() {
			this.other = ''
		},
		saveOther() {
			this.otherTried = true
			const n = parseDelay(this.other)
			if (n === null) return
			this.other = ''
			this.otherTried = false
			this.saveDelay(n)
		},
		openLights() {
			goPath(LIGHTS_PAGE)
		},
		toggleZones() {
			if (!this.zones) return
			this.wantZones = !this.zones.enabled
			const args = zonesArgs(bedZones.data, this.wantZones)
			if (args) this.zonesSet.run(args)
		},
		// somebody saved the zones while this person looked: read what is there now and drop the refusal
		seeCurrent() {
			this.zonesSet.reset()
			bedZones.reload()
		},
		// keep what this person asked, on top of what the other person saved (its revision is the one the service sent back)
		keepMine() {
			const e = this.zonesSet.error
			const current = e && e.extra && e.extra.current
			const args = current && current.config ? zonesArgs(current, this.wantZones) : zonesArgs(bedZones.data, this.wantZones)
			if (args) this.zonesSet.run(args)
		},
		toggleRelay() {
			if (this.relayRunning === null) return
			this.relayAction.run({})
		},
		relayWord(c) {
			if (c.armed) return this.t('machine.relay_arm')
			if (this.relayState === 'nocam') return this.t('machine.word_nocam')
			return this.t(this.relayRunning === null ? 'machine.word_unknown' : this.relayRunning ? 'machine.word_relay_on' : 'machine.word_relay_off')
		}
	}
}
</script>
