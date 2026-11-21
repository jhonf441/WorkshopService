<template>
	<!-- Protections: the guard that watches the safety processes (fire, servo, laser ...). Its switch, what it does when one falls, what it
	     watches (fire and servo first) and, under "Advanced", its tolerances. Turning it off or lowering the action is a level 4 dialog of the
	     page: the service asks nothing here, so the page does. A technician sees all of it as state. -->
	<section class="sv-card" aria-labelledby="sv-mg-title" data-card="guard">
		<div class="sv-card-head">
			<h2 id="sv-mg-title"><span class="mdi mdi-shield-check-outline sv-ico" aria-hidden="true" />{{ t('machine.guard_title') }}</h2>
			<span v-if="rows.length" class="sv-chip" :data-level="sum.down ? 'error' : null">{{ chipText }}</span>
		</div>
		<ul class="sv-rows">
			<sv-action-row icon="mdi-shield-check-outline" :name="t('machine.guard_name')" :desc="t('machine.guard_desc')" :action="guardEnable" :permission="perm('guard.set')" :stale="stale" @retry="toggleGuard">
				<template #control="c">
					<sv-switch :checked="enabled === true" :word="t(enabled === null ? 'machine.word_unknown' : enabled ? 'machine.word_guard_on' : 'machine.word_guard_off')" :label="t('machine.guard_name')"
						:state="c.state" :disabled="c.disabled || enabled === null" @toggle="toggleGuard" @hold="on => held(c, on)" @escape="c.cancel" />
				</template>
				<template #help><sv-help v-bind="help('guard')" /></template>
			</sv-action-row>
			<sv-action-row icon="mdi-alert-outline" :name="t('machine.guard_action_name')" :desc="t('machine.guard_action_desc')" :action="guardAction" :permission="perm('guard.set')" :stale="stale"
				:label="action === 'pause' ? t('machine.guard_to_notify') : action === 'notify' ? t('machine.guard_to_pause') : ''" @run="changeAction" @retry="changeAction">
				<span class="sv-value"><span class="mdi sv-ico" :class="action === 'pause' ? 'mdi-pause-circle-outline' : 'mdi-bell-outline'" aria-hidden="true" />{{ t(action === 'pause' ? 'machine.guard_does_pause' : action === 'notify' ? 'machine.guard_does_notify' : 'machine.word_unknown') }}</span>
				<p class="sv-row-desc" data-part="phone">
					<span class="sv-state" :data-level="phone === true ? 'ok' : 'rest'"><span class="mdi mdi-cellphone-message sv-ico sv-ico-s" aria-hidden="true" />{{ t(phone === null ? 'machine.guard_phone_unknown' : phone ? 'machine.guard_phone_on' : 'machine.guard_phone_off') }}</span>
					<button v-if="phonePage" type="button" class="sv-btn sv-text" data-act="phone" @click="openPhone">{{ t('machine.guard_phone_setting') }}</button>
				</p>
				<p v-if="action === 'notify' && phone === false" class="sv-field-error" role="status" data-part="phone-hint"><span class="mdi mdi-alert-outline sv-ico sv-ico-s" aria-hidden="true" />{{ t('machine.guard_phone_hint') }}</p>
				<template #help><sv-help v-bind="help('guard_action')" /></template>
			</sv-action-row>
		</ul>
		<sv-reason :lock="lock" @sign-in="signIn" />

		<details class="sv-fold" data-part="watches">
			<summary>
				<span class="mdi mdi-chevron-right sv-ico sv-chev" aria-hidden="true" />
				<span class="sv-fold-name">{{ t('machine.watches_title') }}</span>
				<span class="sv-fold-sum">{{ watchesSummary }}</span>
			</summary>
			<div class="sv-fold-body">
				<p v-if="!rows.length" class="sv-quiet" role="status">{{ t('machine.watches_none') }}</p>
				<table v-else class="sv-table">
					<thead><tr><th>{{ t('machine.watches_protects') }}</th><th>{{ t('machine.watches_process') }}</th><th>{{ t('machine.watches_source') }}</th><th>{{ t('machine.watches_state') }}</th></tr></thead>
					<tbody>
						<tr v-for="r in rows" :key="r.id" :data-watch="r.id">
							<td :data-label="t('machine.watches_protects')">{{ protects(r) }}</td>
							<td :data-label="t('machine.watches_process')">{{ title(r) }}</td>
							<td :data-label="t('machine.watches_source')" data-part="source">{{ r.plugin ? t('machine.watches_source_plugin', { name: PLUGIN_NAMES[r.plugin] }) : t('machine.watches_source_service') }}</td>
							<td :data-label="t('machine.watches_state')"><span class="sv-word" :data-level="r.level"><span class="mdi sv-ico sv-ico-s" :class="ICONS[r.word]" aria-hidden="true" />{{ r.why ? serviceText(r.why) : t(r.away ? 'machine.watch_away' : 'machine.watch_' + r.word) }}</span></td>
						</tr>
					</tbody>
				</table>
				<p v-if="rows.length" class="sv-hint" data-part="watches-help">{{ t('machine.watches_help') }}</p>
			</div>
		</details>

		<details class="sv-fold" data-part="tune" @toggle="e => onTune(e.target.open)">
			<summary>
				<span class="mdi mdi-chevron-right sv-ico sv-chev" aria-hidden="true" />
				<span class="sv-fold-name">{{ t('machine.tune_title') }}</span>
				<span class="sv-fold-sum">{{ t('machine.tune_sum') }}</span>
			</summary>
			<div class="sv-fold-body">
				<p v-if="!settings" class="sv-quiet" role="status">{{ t(lock ? 'machine.tune_locked' : 'machine.tune_reading') }}</p>
				<form v-else class="sv-form sv-tune" @submit.prevent="saveTune">
					<label v-for="f in FIELDS" :key="f.id" class="sv-field-line">
						<span>{{ t('machine.tune_' + f.id) }}</span>
						<span class="sv-field"><input v-model="draft[f.id]" type="text" inputmode="decimal" :disabled="stale || perm('guard.set').state !== 'ok'" :aria-invalid="problem(f) ? 'true' : null" :aria-label="t('machine.tune_' + f.id)"></span>
						<small class="sv-quiet">{{ t('machine.tune_range', { min: f.min, max: f.max }) }}</small>
						<span v-if="problem(f)" class="sv-field-error" role="alert"><span class="mdi mdi-alert-outline sv-ico sv-ico-s" aria-hidden="true" />{{ t('machine.tune_invalid', { min: f.min, max: f.max }) }}</span>
					</label>
					<div class="sv-fbar"><button type="submit" class="sv-btn sv-main" :class="{ 'sv-save-hot': hasUnsaved }" :disabled="stale || perm('guard.set').state !== 'ok' || guardTune.busy()">{{ t('machine.tune_save') }}</button><sv-unsaved-mark :show="hasUnsaved" /><span class="sv-quiet">{{ t('data.settings_nothing') }}</span></div>
					<div v-if="guardTune.state === 'done'" class="sv-row-out" data-kind="done" role="status"><span class="mdi mdi-check-circle-outline sv-ico sv-ico-s" aria-hidden="true" />{{ t('machine.tune_done') }}</div>
					<div v-else-if="guardTune.state === 'error' && guardTune.error" class="sv-row-out" data-kind="error" role="alert"><span class="mdi mdi-close-circle-outline sv-ico sv-ico-s" aria-hidden="true" />{{ guardTune.error.message }}</div>
				</form>
			</div>
		</details>

		<sv-confirm-dialog :confirm="guardEnable.confirm" :title="t('machine.guard_off_title')" :text="t('machine.guard_off_text')" :object="{ name: t('machine.guard_name'), context: t('machine.guard_context', { n: sum.total }) }"
			:effects="offEffects" :verb="t('machine.guard_off_verb')" @accept="guardEnable.accept()" @cancel="guardEnable.cancel()" />
		<sv-confirm-dialog :confirm="guardAction.confirm" :title="t('machine.guard_notify_title')" :text="t('machine.guard_notify_text')" :object="{ name: t('machine.guard_name'), context: t('machine.guard_context', { n: sum.total }) }"
			:effects="[t('machine.guard_notify_e1'), t('machine.guard_notify_e2')]" :verb="t('machine.guard_notify_verb')" @accept="guardAction.accept()" @cancel="guardAction.cancel()" />
		<sv-confirm-dialog :confirm="guardTune.confirm" :title="t('machine.tune_confirm_title')" :text="t('machine.tune_confirm_text')" :object="{ name: t('machine.guard_name') }"
			:verb="t('machine.tune_save')" @accept="guardTune.accept()" @cancel="guardTune.cancel()" />
	</section>
</template>

<script>
import { get } from '../../core/live/published.js'
import { goPath, pathExists, pluginOn } from '../../core/dwc.js'
import { guardAction, guardEnable, guardTune } from '../../core/actions/machine.js'
import { guardSettings } from '../../core/resources.js'
import { serviceText } from '../../service-text.js'
import SvActionRow from '../../ui/SvActionRow.vue'
import SvConfirmDialog from '../../ui/SvConfirmDialog.vue'
import SvHelp from '../../ui/SvHelp.vue'
import SvReason from '../../ui/SvReason.vue'
import SvSwitch from '../../ui/SvSwitch.vue'
import { guardLead, guardRows, guardSummary } from './view.js'
import { rowsMixin } from '../../core/rows-mixin.js'
import SvUnsavedMark from '../../ui/SvUnsavedMark.vue'
import { unsavedMixin } from '../../ui/unsaved-mixin.js'
import { saveWithAction } from '../../ui/unsaved-guard.js'

const ICONS = { fine: 'mdi-check-circle-outline', resting: 'mdi-sleep', down: 'mdi-close-circle-outline' }
const FIELDS = Object.freeze([
	{ id: 'external_tolerance_s', min: 10, max: 600 }, { id: 'grace_s', min: 10, max: 900 },
	{ id: 'renotify_s', min: 60, max: 86400 }, { id: 'tolerance_factor', min: 1.5, max: 20 }
])

const PHONE_PATH = '/Plugins/Activity'
// the two protections that live in a plugin: the list itself is fixed in the service (protection_guard.py WATCHES)
const WATCH_PLUGINS = { vision: 'WorkshopVision', rs485: 'WorkshopRS485' }
const PLUGIN_NAMES = { WorkshopVision: 'Vision', WorkshopRS485: 'RS485' }

export default {
	name: 'GuardCard',
	components: { SvActionRow, SvConfirmDialog, SvHelp, SvReason, SvSwitch, SvUnsavedMark },
	mixins: [rowsMixin, unsavedMixin],
	data() {
		return { guardAction, guardEnable, guardTune, PLUGIN_NAMES, ICONS, FIELDS, draft: {}, tried: false }
	},
	computed: {
		// the phone notices are one switch of their own (Activity page); the guard only uses them: say where they stand (null = not known)
		phone() {
			const n = get('notifications')
			return n && n.config && typeof n.config.active === 'boolean' ? n.config.active : null
		},
		phonePage() {
			return pathExists(PHONE_PATH)
		},
		g() {
			return get('guardStatus') || null
		},
		enabled() {
			return this.g && typeof this.g.enabled === 'boolean' ? this.g.enabled : null
		},
		action() {
			return this.g && (this.g.action === 'pause' || this.g.action === 'notify') ? this.g.action : ''
		},
		// the watched protections; one that belongs to a plugin that is stopped or disabled is not expected: it rests (the service decides the same)
		rows() {
			return guardRows(this.g).map(r => {
				const plugin = WATCH_PLUGINS[r.id] || ''
				const away = !!plugin && !r.why && !pluginOn(plugin)
				return Object.assign({}, r, { plugin, away, word: away ? 'resting' : r.word, level: away ? 'rest' : r.level })
			})
		},
		sum() {
			return guardSummary(this.rows)
		},
		lock() {
			return this.lockOf(['guard.set'])
		},
		settings() {
			const d = guardSettings.data
			return d && d.settings ? d.settings : null
		},
		chipText() {
			return this.sum.down ? this.tc('machine.guard_chip_down', this.sum.down) : this.tc('machine.guard_chip_fine', this.sum.fine + this.sum.resting)
		},
		watchesSummary() {
			if (!this.rows.length) return this.t('machine.watches_none')
			return this.t('machine.watches_sum', { lead: guardLead(this.rows).map(p => this.t('machine.protects_' + p)).join(', '), n: Math.max(0, this.rows.length - 2) })
		},
		offEffects() {
			return ['fire', 'servo', 'laser', 'home'].map(k => this.t('machine.guard_off_e_' + k))
		}
	},
	watch: {
		settings: { immediate: true, handler(s) { if (s) this.fill(s) } }
	},
	methods: {
		serviceText,
		openPhone() {
			goPath(PHONE_PATH)
		},
		title(r) {
			return r.title ? serviceText(r.title) : r.id
		},
		protects(r) {
			const k = 'machine.protects_' + r.protects
			return this.t(k) === k ? r.protects || r.id : this.t(k)
		},
		toggleGuard() {
			if (this.enabled === null) return
			this.guardEnable.run({ enabled: !this.enabled })
		},
		changeAction() {
			if (!this.action) return
			this.guardAction.run({ action: this.action === 'pause' ? 'notify' : 'pause' })
		},
		onTune(open) {
			if (open) guardSettings.show()
		},
		// unsaved changes (unsaved-mixin.js): the four values typed against the ones the service holds
		unsavedPair() {
			const s = this.settings
			if (!s || !Object.keys(this.draft).length) return [null, null]
			const own = {}
			const saved = {}
			FIELDS.forEach(f => { own[f.id] = String(this.draft[f.id]).trim(); saved[f.id] = String(s[f.id]) })
			return [own, saved]
		},
		saveBeforeLeaving() {
			if (FIELDS.some(f => this.number(f) === null)) return false
			return saveWithAction(this.guardTune, () => this.saveTune())
		},
		discardUnsaved() {
			if (this.settings) this.fill(this.settings)
		},
		fill(s) {
			const d = {}
			FIELDS.forEach(f => { d[f.id] = String(s[f.id]) })
			this.draft = d
		},
		number(f) {
			const s = String(this.draft[f.id] === undefined ? '' : this.draft[f.id]).trim().replace(',', '.')
			if (!/^\d+(\.\d+)?$/.test(s)) return null
			const n = Number(s)
			return n >= f.min && n <= f.max ? n : null
		},
		problem(f) {
			return (this.tried || String(this.draft[f.id]) !== String(this.settings && this.settings[f.id])) && this.number(f) === null
		},
		saveTune() {
			this.tried = true
			if (FIELDS.some(f => this.number(f) === null)) return
			const args = {}
			FIELDS.forEach(f => { args[f.id] = this.number(f) })
			this.guardTune.run(args)
		}
	}
}
</script>
