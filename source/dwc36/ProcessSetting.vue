<template>
	<!-- The setting a process OWNS, in sight under its row (like the relay card of the camera): the automatic air of the interceptor, the status
	     lights of status_light (read only: the Lights page owns them), the bed zones on / off. One "?" with what / why / without it / how, the
	     control disabled for a role that may not (lock + ONE reason after a touch, lock-reason-in-parent), a notice when a save fails. -->
	<div v-if="kind" class="svc-ps" :class="'svc-ps--' + kind" :data-setting="kind" @click="touchLocked">
		<!-- the automatic air with the laser (air.auto / air.delay, operator) -->
		<div v-if="kind === 'air'" class="svc-lock-group" data-lock-group="air">
			<div class="svc-ps-row">
				<v-icon small class="svc-ps-ico" aria-hidden="true">mdi-weather-windy</v-icon>
				<v-icon v-if="!canAir" small class="svc-lock-ico" aria-hidden="true">mdi-lock-outline</v-icon>
				<v-switch :input-value="air.auto" dense hide-details class="mt-0 pt-0 svc-ps-switch" :disabled="!canAir || busy" :loading="busy" :label="$t(S + 'automatic_air_with_the_laser')" @change="setAirAuto" />
				<v-chip x-small label dark :color="air.on ? 'success' : 'grey'">{{ air.on ? $t(S + 'air_on') : $t(S + 'air_off') }}</v-chip>
				<help-tip :title="$t(S + 'automatic_air_with_the_laser')" :what="$t(D + 'set_air_what')" :why="$t(D + 'set_air_why')" :if-missing="$t(D + 'set_air_missing')" :how="$t(D + 'set_air_how')" />
			</div>
			<div class="svc-ps-sub text-caption grey--text">
				{{ $t(S + 'air_rule') }}<span v-if="!air.auto"> {{ $t(S + 'used_when_automatic_mode_is_on') }}</span>
				<div class="d-flex align-center flex-wrap mt-1" style="gap:4px">
					<span>{{ $t(S + 'air_off_after') }}</span>
					<v-chip-group :value="air.delay" mandatory active-class="primary--text" @change="setDelay">
						<v-chip v-for="t in air.options" :key="t" :value="t" small outlined filter :disabled="!canAir || busy">{{ t }} s</v-chip>
					</v-chip-group>
				</div>
			</div>
			<lock-reason v-if="shown === 'air'" op="air.auto" need="operator" class="mt-1 svc-lock-reason" />
			<session-notice v-if="failure" :kind="failure.kind" :text="failure.text" class="mt-1" />
		</div>

		<!-- the status lights: read only, the Lights and status page is the owner (request 2026-10-09) -->
		<div v-else-if="kind === 'lights'" class="svc-ps-row">
			<v-icon small class="svc-ps-ico" aria-hidden="true">mdi-led-strip-variant</v-icon>
			<span class="svc-ps-text">{{ $t(S + 'status_lights_x', { x: lights.auto ? $t(S + 'automatic_f') : $t(S + 'off_lighting_uses_those_leds') }) }}</span>
			<v-chip x-small label :color="lights.auto ? 'success' : 'grey'">{{ lights.auto ? $t(S + 'auto_state_on') : $t(S + 'auto_state_off') }}</v-chip>
			<!-- the link only exists with the plugin installed and active: stopped, the route does not exist -->
			<a v-if="lights.active" href="#" class="text-body-2" @click.prevent="$emit('go-path', '/Plugins/Lights')">{{ $t(S + 'open_lights_and_status') }}</a>
			<span v-else class="text-caption grey--text">{{ $t(D + 'set_lights_no_plugin') }}</span>
			<help-tip :title="$t(D + 'set_lights_title')" :what="$t(D + 'set_lights_what')" :why="$t(D + 'set_lights_why')" :if-missing="$t(D + 'set_lights_missing')" :how="$t(D + 'set_lights_how')" />
		</div>

		<!-- the bed zones on / off: `enabled` of the configuration (bedzones.get / bedzones.set, technician); the zones themselves are drawn in 3D printing -->
		<div v-else-if="kind === 'bed_zones'" class="svc-lock-group" data-lock-group="zones">
			<div class="svc-ps-row">
				<v-icon small class="svc-ps-ico" aria-hidden="true">mdi-view-grid-outline</v-icon>
				<v-icon v-if="!canZones" small class="svc-lock-ico" aria-hidden="true">mdi-lock-outline</v-icon>
				<v-switch :input-value="zonesOn" dense hide-details class="mt-0 pt-0 svc-ps-switch" :disabled="!canZones || busy || !zones" :loading="busy" :label="$t(D + 'set_zones_label')" @change="setZones" />
				<v-chip x-small label :color="zonesOn ? 'success' : 'grey'">{{ zonesChip }}</v-chip>
				<help-tip :title="$t(D + 'set_zones_label')" :what="$t(D + 'set_zones_what')" :why="$t(D + 'set_zones_why')" :if-missing="$t(D + 'set_zones_missing')" :how="$t(D + 'set_zones_how')" />
			</div>
			<div v-if="zones && zones.problems" class="svc-ps-sub text-caption warning--text">{{ $t(D + 'set_zones_problems') }}</div>
			<div v-else-if="zonesError" class="svc-ps-sub text-caption grey--text">{{ zonesError }}</div>
			<lock-reason v-if="shown === 'zones'" op="bedzones.set" need="technician" class="mt-1 svc-lock-reason" />
			<session-notice v-if="failure" :kind="failure.kind === 'conflict' ? 'down' : failure.kind" :text="failure.kind === 'conflict' ? $t(D + 'set_zones_conflict') : failure.text" class="mt-1" />
		</div>
	</div>
</template>

<script>
'use strict'

import HelpTip from './HelpTip.vue'
import SessionNotice from './SessionNotice.vue'
import LockReason from './LockReason.vue'
import { roleMixin } from './role-mixin.js'
import { api } from './workshop-api.js'
import { signedOut } from './workshop-auth.js'
import { blinkLocked } from './lock-attention.js'
import { rowSetting, airView, lightsView, zonesView, zonesToggle, saveFailure } from './process-settings.js'

const D = 'plugins.WorkshopService.procDocs.'
const S = 'plugins.WorkshopService.servicePage.'

export default {
	name: 'ProcessSetting',
	components: { HelpTip, SessionNotice, LockReason },
	mixins: [roleMixin],
	// what this person saw: the reason after a touch, a failed save and the zones read with their session (read again for the next person)
	sessionData: ['shown', 'failure', 'zones', 'zonesError'],
	props: {
		p: { type: Object, required: true },
		// what the page reads from the plugin data for the rows: { data: {airAssist, airAssistAuto, airAssistDelay, statusLightAuto}, lightsActive }
		settings: { type: Object, default: null }
	},
	data() {
		return { D, S, shown: '', failure: null, busy: false, zones: null, zonesError: '' }
	},
	computed: {
		kind() {
			return rowSetting(this.p)
		},
		air() {
			return airView(this.settings && this.settings.data)
		},
		lights() {
			return lightsView(this.settings && this.settings.data, this.settings && this.settings.lightsActive)
		},
		canAir() {
			return this.canDo('air.auto') && this.canDo('air.delay')
		},
		canZones() {
			return this.canDo('bedzones.set')
		},
		zonesOn() {
			return !!(this.zones && this.zones.enabled)
		},
		zonesChip() {
			if (!this.zones) return this.$t(D + 'set_zones_reading')
			const state = this.$t(D + (this.zones.enabled ? 'set_zones_on' : 'set_zones_off'))
			return this.zones.zones ? state + ' · ' + this.$t(D + 'set_zones_n', { n: this.zones.zones }) : state
		}
	},
	mounted() {
		if (this.kind === 'bed_zones') this.readZones()
	},
	methods: {
		// the mixin tells us when the person changes: the zones are read again for the one who is here now
		onSessionChange() {
			if (this.kind === 'bed_zones') this.readZones()
		},
		async readZones() {
			try {
				const r = await api('bedzones.get', {}, { quiet: true, noLogin: true })
				this._zonesRaw = r
				this.zones = zonesView(r)
				this.zonesError = this.zones ? '' : this.$t(D + 'set_zones_unreadable')
			} catch (e) {
				this._zonesRaw = null
				this.zones = null
				this.zonesError = e && e.code === 'login_required' ? '' : String((e && e.message) || e)
			}
		},
		// only a real change of the switch reaches the service (a switch that settles on its stored value by itself must not call it)
		setAirAuto(v) {
			if (!!v === this.air.auto) return
			return this.save(() => api('air.auto', { on: !!v }))
		},
		setDelay(v) {
			if (typeof v !== 'number' || v === this.air.delay) return
			return this.save(() => api('air.delay', { seconds: v }))
		},
		async setZones(v) {
			if (!this._zonesRaw || !!v === this.zonesOn) return
			const args = zonesToggle(this._zonesRaw, !!v)
			await this.save(() => api('bedzones.set', args))
			// what the service holds now (also after a conflict: somebody else saved in between)
			await this.readZones()
		},
		// one save through api(): the answer is fine, a refusal keeps its code (role, session, conflict) for the notice; a cancel is no change
		async save(fn) {
			this.busy = true
			this.failure = null
			try {
				this.failure = saveFailure(await fn(), null)
			} catch (e) {
				this.failure = saveFailure('', e)
			} finally {
				this.busy = false
			}
		},
		// a touch on a control this person cannot use (a disabled control emits no click: the group around it listens): its reason blinks, and
		// the sign-in chip of the bar when nobody is signed in; no dialog, no card
		touchLocked(ev) {
			const el = ev && ev.target && typeof ev.target.closest === 'function' ? ev.target.closest('[data-lock-group]') : null
			const name = el ? el.getAttribute('data-lock-group') : ''
			const locked = name === 'air' ? !this.canAir : name === 'zones' ? !this.canZones : false
			if (!locked) return
			this.shown = name
			this.$nextTick(() => blinkLocked(el, signedOut()))
		}
	}
}
</script>

<style scoped>
.svc-ps { margin: 0 14px 8px 38px; padding: 6px 0 2px; font-size: 13px; }
.svc-ps-row { display: flex; align-items: center; flex-wrap: wrap; gap: 4px 10px; }
.svc-ps-ico { opacity: 0.8; }
.svc-ps-text { flex: 1 1 14rem; min-width: 0; }
.svc-ps-switch { flex: 1 1 12rem; }
.svc-ps-sub { margin-left: 30px; margin-top: 2px; }
.svc-lock-ico { opacity: 0.7; }
.svc-lock-group .svc-lock-reason { display: inline-flex; width: fit-content; max-width: 100%; padding: 2px 8px; border-radius: 6px; }
@media (max-width: 760px) {
	.svc-ps { margin-left: 14px; }
}
</style>
