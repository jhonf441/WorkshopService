<template>
	<!-- Machine > Communication: through which channel of the board the Pi sends its codes and its jog moves, and why. Choosing one by hand is
	     rare and risky (administrator): the SERVICE asks for the confirmation (level 4, its own risks) and may refuse ("not now: <reason>").
	     Under it, the 14 channels of the board in one fold. Prop: active. -->
	<div class="sv-machine-comms">
		<section class="sv-card" aria-labelledby="sv-mc-title" data-card="comms">
			<div class="sv-card-head">
				<h2 id="sv-mc-title"><span class="mdi mdi-swap-horizontal sv-ico" aria-hidden="true" />{{ t('machine.comms_title') }}</h2>
				<span v-if="comm" class="sv-chip" :data-level="notices.length ? 'warn' : null">{{ notices.length ? tc('machine.comms_chip_notices', notices.length) : t('machine.comms_chip_ok') }}</span>
			</div>
			<p class="sv-lead">{{ t('machine.comms_lead') }}</p>
			<p v-if="!comm" class="sv-quiet" role="status">{{ t(running ? 'machine.comms_waiting' : 'machine.comms_stopped') }}</p>
			<template v-else>
				<dl class="sv-facts" data-part="facts">
					<dt>{{ t('machine.comms_service') }}</dt><dd data-fact="service">{{ fact(comm.channel_cfg, comm.channel) }}</dd>
					<template v-if="hasJog"><dt>{{ t('machine.comms_jog') }}</dt><dd data-fact="jog">{{ fact(comm.channel_jog_cfg, comm.channel_jog) }}</dd></template>
				</dl>
				<p v-for="(n, i) in notices" :key="i" class="sv-field-error" role="status" data-part="notice"><span class="mdi mdi-alert-outline sv-ico sv-ico-s" aria-hidden="true" />{{ noticeText(n) }}</p>
				<ul class="sv-rows">
					<!-- choosing the channel by hand is behind a padlock: with it on, only the automatic mode is seen -->
					<sv-action-row :icon="advanced ? 'mdi-lock-open-variant-outline' : 'mdi-lock-outline'" :name="t('machine.advanced_name')" :desc="t('machine.advanced_desc')">
						<template #control>
							<span data-part="advanced"><sv-switch :checked="advanced" :word="t(advanced ? 'machine.advanced_on' : 'machine.advanced_off')" :label="t('machine.advanced_name')" @toggle="advanced = !advanced" /></span>
						</template>
					</sv-action-row>
					<sv-action-row v-if="advanced" icon="mdi-swap-horizontal" :name="t('machine.comms_pick_name')" :desc="t('machine.comms_pick_desc')" :action="commsSet" :permission="perm('comms.set')" :stale="stale" @retry="save">
						<template #control="c">
							<div class="sv-pick">
								<div class="sv-pick-line"><span class="sv-label" data-part="label-service">{{ t('machine.comms_service') }}</span>
									<span class="sv-seg" role="group" :aria-label="t('machine.comms_service')"><button v-for="id in choices" :key="id" type="button" :aria-pressed="pickService === id ? 'true' : 'false'" :disabled="c.disabled" :data-pick-service="id" @click="pickService = id">{{ choiceText(id) }}</button></span></div>
								<div v-if="hasJog" class="sv-pick-line"><span class="sv-label" data-part="label-jog">{{ t('machine.comms_jog') }}</span>
									<span class="sv-seg" role="group" :aria-label="t('machine.comms_jog')"><button v-for="id in choices" :key="id" type="button" :aria-pressed="pickJog === id ? 'true' : 'false'" :disabled="c.disabled" :data-pick-jog="id" @click="pickJog = id">{{ choiceText(id) }}</button></span></div>
								<button type="button" class="wf-btn sv-btn wf-main" :class="{ 'sv-save-hot': hasUnsaved }" :disabled="c.disabled || !changed" data-act="save" @click="save">{{ t('machine.comms_save') }}</button><sv-unsaved-mark :show="hasUnsaved" />
							</div>
						</template>
						<p class="sv-note" data-level="warn" role="note" data-part="advanced-warning"><span class="mdi mdi-alert-outline sv-ico" aria-hidden="true" /><span>{{ warning }} {{ t('machine.advanced_warning') }}</span></p>
						<template #help><help-fold v-bind="help('comms')" /></template>
					</sv-action-row>
				</ul>
				<lock-reason class="sv-lock" :lock="lock" />
				<details class="sv-fold" data-part="channels">
					<summary>
						<span class="mdi mdi-chevron-right sv-ico sv-chev" aria-hidden="true" />
						<span class="sv-fold-name">{{ t('machine.channels_title', { n: rows.length }) }}</span>
						<span class="sv-fold-sum">{{ t('machine.channels_sum', counts) }}</span>
					</summary>
					<div class="sv-fold-body">
						<table class="sv-table">
							<thead><tr><th>{{ t('machine.channels_channel') }}</th><th>{{ t('machine.channels_state') }}</th><th>{{ t('machine.channels_use') }}</th></tr></thead>
							<tbody>
								<tr v-for="r in rows" :key="r.id" :data-channel="r.id">
									<td :data-label="t('machine.channels_channel')"><code>{{ r.id }}</code><span v-if="r.service" class="sv-tag">{{ t('machine.comms_service_tag') }}</span><span v-if="hasJog && r.jog" class="sv-tag">{{ t('machine.comms_jog_tag') }}</span></td>
									<td :data-label="t('machine.channels_state')"><span class="sv-word" :data-level="LEVEL[r.state] || 'rest'">{{ t('machine.channel_' + r.state) }}</span></td>
									<td :data-label="t('machine.channels_use')">{{ usage(r) }}</td>
								</tr>
							</tbody>
						</table>
					</div>
				</details>
			</template>
		</section>
		<wf-confirm :confirm="commsSet.confirm" :title="t('machine.comms_confirm_title')" :text="t('machine.comms_confirm_text')" :object="{ name: t('machine.comms_title') }" :verb="t('machine.comms_verb')" danger
			@accept="commsSet.accept()" @cancel="commsSet.cancel()" />
	</div>
</template>

<script>
import { get, serviceRunning } from '../../core/live/published.js'
import { want } from '../../core/store/session.js'
import { commsSet } from '../../core/actions/machine.js'
import { serviceText } from '../../service-text.js'
import SvActionRow from '../../ui/SvActionRow.vue'
import WfConfirm from '../../WfConfirm.vue'
import HelpFold from '../../HelpFold.vue'
import LockReason from '../../LockReason.vue'
import SvSwitch from '../../ui/SvSwitch.vue'
import { channelChoices, channelCounts, channelRows } from './view.js'
import { rowsMixin } from '../../core/rows-mixin.js'
import SvUnsavedMark from '../../ui/SvUnsavedMark.vue'
import { unsavedMixin } from '../../ui/unsaved-mixin.js'
import { saveWithAction } from '../../ui/unsaved-guard.js'

const LEVEL = { free: 'ok', shared: 'warn', busy: 'warn', reserved: 'rest' }
const textOf = v => (v && typeof v === 'object' ? serviceText(v) : String(v || ''))

export default {
	name: 'CommsTab',
	components: { SvActionRow, WfConfirm, HelpFold, LockReason, SvSwitch, SvUnsavedMark },
	mixins: [rowsMixin, unsavedMixin],
	props: { active: { type: Boolean, default: false } },
	data() {
		return { commsSet, LEVEL, pickService: '', pickJog: '', advanced: false }
	},
	computed: {
		comm() {
			return get('communication') || null
		},
		running() {
			return serviceRunning()
		},
		hasJog() {
			return !!(this.comm && this.comm.channel_jog_cfg !== undefined && this.comm.channel_jog_cfg !== null)
		},
		rows() {
			return channelRows(this.comm)
		},
		counts() {
			return channelCounts(this.rows)
		},
		choices() {
			return channelChoices(this.rows, null).concat([this.comm && this.comm.channel_cfg, this.comm && this.comm.channel_jog_cfg].filter(x => x && x !== 'auto' && !this.rows.some(r => r.id === x && r.eligible)))
		},
		notices() {
			return (this.comm && this.comm.notices) || []
		},
		warning() {
			return this.comm && this.comm.warning ? textOf(this.comm.warning) : this.t('machine.comms_warning')
		},
		lock() {
			return this.lockOf(['comms.set'])
		},
		changed() {
			const c = this.comm
			return !!c && (this.pickService !== c.channel_cfg || (this.hasJog && this.pickJog !== c.channel_jog_cfg))
		}
	},
	watch: {
		active: { immediate: true, handler(on) { if (on) want(['comms.set']) } },
		// what the service says now is what the selects show (also after somebody else changed it)
		'comm.channel_cfg': { immediate: true, handler(v) { if (v) this.pickService = v } },
		// a change that went through puts the padlock back
		'commsSet.state'(now) { if (now === 'done') this.advanced = false },
		'comm.channel_jog_cfg': { immediate: true, handler(v) { if (v) this.pickJog = v } }
	},
	methods: {
		// unsaved changes (unsaved-mixin.js): the channels picked against the ones the service has
		unsavedPair() {
			const c = this.comm
			return c ? [{ s: this.pickService, j: this.hasJog ? this.pickJog : null }, { s: c.channel_cfg, j: this.hasJog ? c.channel_jog_cfg : null }] : [null, null]
		},
		saveBeforeLeaving() {
			return saveWithAction(this.commsSet, () => this.save())
		},
		discardUnsaved() {
			if (this.comm) { this.pickService = this.comm.channel_cfg; this.pickJog = this.comm.channel_jog_cfg }
		},
		fact(cfg, inUse) {
			return cfg === 'auto' ? this.t('machine.comms_fact_auto', { channel: inUse }) : this.t('machine.comms_fact_fixed', { channel: inUse })
		},
		choiceText(id) {
			return id === 'auto' ? this.t('machine.comms_auto') : id
		},
		noticeText(n) {
			return textOf(n)
		},
		usage(r) {
			const u = textOf(r.usage)
			const why = !r.eligible && r.reason ? textOf(r.reason) : ''
			return why ? u + ' · ' + why : u
		},
		save() {
			const c = this.comm
			if (!c || !this.changed) return
			const args = {}
			if (this.pickService !== c.channel_cfg) args.plugin_channel = this.pickService
			if (this.hasJog && this.pickJog !== c.channel_jog_cfg) args.jog_channel = this.pickJog
			this.commsSet.run(args)
		}
	}
}
</script>
