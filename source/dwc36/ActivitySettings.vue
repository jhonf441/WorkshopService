<template>
	<!-- Settings of the recorded activity (audit.settings): the optional read events by category (off by default, with the note about the SD card), their sampling
	     and daily cap, and the four alarms with their thresholds. Every value is one of a closed list. Saving goes through the one before / after dialog.
	       <activity-settings :can-change="true" @close="..." /> -->
	<v-dialog :value="true" max-width="720" width="100%" scrollable persistent content-class="activity-settings">
		<v-card role="dialog" aria-labelledby="activity-settings-title">
			<v-card-title id="activity-settings-title" class="text-subtitle-1">{{ $t('plugins.WorkshopService.access.audit_settings') }}</v-card-title>
			<v-card-text>
				<div v-if="failure" class="wf-help" role="alert">{{ $t('plugins.WorkshopService.access.audit_set_load_error', { detail: failure }) }}</div>
				<div v-else-if="!draft" class="wf-help">{{ $t('plugins.WorkshopService.access.common_loading') }}</div>
				<template v-else>
					<div class="wf-help mb-2">{{ $t('plugins.WorkshopService.access.audit_set_always') }}</div>
					<div class="text-subtitle-2">{{ $t('plugins.WorkshopService.access.audit_set_reads') }}</div>
					<div class="wf-note is-warn mb-2" role="note"><v-icon class="wf-note-icon" aria-hidden="true">mdi-sd</v-icon><span>{{ $t('plugins.WorkshopService.access.audit_set_reads_cost') }}</span></div>
					<div v-for="c in categories" :key="'r' + c.id" class="activity-switch"><sv-toggle v-model="draft.reads[c.id]" :disabled="!canChange" :label="$t('plugins.WorkshopService.access.' + c.key)" /></div>
					<div class="activity-number"><sv-select v-model="draft.read_sample" :items="items('read_sample')" :disabled="!canChange" :label="$t('plugins.WorkshopService.access.audit_set_sample')" /></div>
					<div class="activity-number"><sv-select v-model="draft.read_daily_cap" :items="items('read_daily_cap')" :disabled="!canChange" :label="$t('plugins.WorkshopService.access.audit_set_cap')" /></div>
					<div class="text-subtitle-2 mt-3">{{ $t('plugins.WorkshopService.access.audit_set_alarms') }}</div>
					<div v-for="a in alarms" :key="'a' + a.id" class="activity-switch"><sv-toggle v-model="draft.alarms[a.id]" :disabled="!canChange" :label="$t('plugins.WorkshopService.access.' + a.key)" /></div>
					<div class="activity-number"><sv-select v-model="draft.burst_threshold" :items="items('burst_threshold')" :disabled="!canChange" :label="$t('plugins.WorkshopService.access.audit_set_burst_count')" /></div>
					<div class="activity-number"><sv-select v-model="draft.burst_window_s" :items="items('burst_window_s')" :disabled="!canChange" :label="$t('plugins.WorkshopService.access.audit_set_burst_window')" /></div>
					<div class="activity-number"><sv-select v-model="draft.alarm_quiet_s" :items="items('alarm_quiet_s')" :disabled="!canChange" :label="$t('plugins.WorkshopService.access.audit_set_quiet')" /></div>
					<div v-if="!canChange" class="wf-help mt-2">{{ $t('plugins.WorkshopService.access.state_read_only') }}</div>
					<div v-else-if="!lines.length" class="wf-help mt-2">{{ $t('plugins.WorkshopService.access.audit_set_no_change') }}</div>
					<div v-if="saved" class="text-caption mt-2" role="status">{{ $t('plugins.WorkshopService.access.audit_set_saved') }}</div>
				</template>
			</v-card-text>
			<v-card-actions>
				<v-spacer />
				<v-btn small text class="access-touch" @click="$emit('close')">{{ $t('plugins.WorkshopService.access.common_back') }}</v-btn>
				<v-btn small color="primary" class="access-touch" :disabled="!canChange || !lines.length" @click="review = true">{{ $t('plugins.WorkshopService.access.audit_set_review') }}</v-btn>
			</v-card-actions>
		</v-card>
		<access-change-dialog v-if="review" :value="true" :title="$t('plugins.WorkshopService.access.audit_set_title')" :confirm-label="$t('plugins.WorkshopService.access.audit_set_save')" :busy="saving" :error="error" @input="review = false" @confirm="save()">
			<template #before><ul class="activity-lines"><li v-for="l in lines" :key="'b' + l.id">{{ labelOf(l) }}: {{ valueOf(l, l.from) }}</li></ul></template>
			<template #after><ul class="activity-lines"><li v-for="l in lines" :key="'a' + l.id">{{ labelOf(l) }}: {{ valueOf(l, l.to) }}</li></ul></template>
			<template #summary><div v-if="turnsOn" class="wf-note is-warn" role="note"><v-icon class="wf-note-icon" aria-hidden="true">mdi-sd</v-icon><span>{{ $t('plugins.WorkshopService.access.audit_set_reads_on_note') }}</span></div></template>
		</access-change-dialog>
	</v-dialog>
</template>

<script>
'use strict'

import SvSelect from './ui/SvSelect.vue'
import AccessChangeDialog from './AccessChangeDialog.vue'
import { accessApi } from './access-api.js'
import SvToggle from './ui/SvToggle.vue'
import { choicesFor, settingsDraft, settingsLines, settingsPatch, turnsOnReads } from './access-audit-view.js'

const AREA = 'plugins.WorkshopService.access.'
// the label and the way each number is written (every key written out)
const NUMBERS = {
	read_sample: { label: 'audit_set_sample', text: 'audit_set_one_of', scale: 1 },
	read_daily_cap: { label: 'audit_set_cap', text: 'audit_set_per_day', scale: 1 },
	burst_threshold: { label: 'audit_set_burst_count', text: 'audit_set_times', scale: 1 },
	burst_window_s: { label: 'audit_set_burst_window', text: 'audit_set_seconds', scale: 1 },
	alarm_quiet_s: { label: 'audit_set_quiet', text: 'audit_set_minutes', scale: 60 }
}
const CATEGORIES = [{ id: 'camera', key: 'audit_set_reads_camera' }, { id: 'audit', key: 'audit_set_reads_audit' }, { id: 'config', key: 'audit_set_reads_config' }]
const ALARMS = [
	{ id: 'access_damaged', key: 'audit_set_alarm_damaged' }, { id: 'denial_burst', key: 'audit_set_alarm_burst' },
	{ id: 'sensitive_change', key: 'audit_set_alarm_change' }, { id: 'chain_broken', key: 'audit_set_alarm_chain' }
]

export default {
	components: { SvSelect, AccessChangeDialog, SvToggle },
	props: { canChange: { type: Boolean, default: true } },
	data() {
		return { before: null, draft: null, failure: '', review: false, saving: false, error: '', saved: false, categories: CATEGORIES, alarms: ALARMS }
	},
	computed: {
		lines() {
			return this.draft ? settingsLines(this.before, this.draft) : []
		},
		turnsOn() {
			return !!this.draft && turnsOnReads(this.before, this.draft)
		}
	},
	created() {
		this.load()
	},
	methods: {
		items(key) {
			const n = NUMBERS[key]
			return choicesFor(key, this.before && this.before[key]).map(v => ({ value: v, text: this.$tc(AREA + n.text, v / n.scale, { n: v / n.scale }) }))
		},
		labelOf(line) {
			if (line.group === 'number') return this.$t(AREA + NUMBERS[line.name].label)
			const list = line.group === 'reads' ? CATEGORIES : ALARMS
			return this.$t(AREA + list.find(x => x.id === line.name).key)
		},
		valueOf(line, v) {
			if (line.group !== 'number') return this.$t(AREA + (v === 'on' ? 'audit_set_on' : 'audit_set_off'))
			return this.$tc(AREA + NUMBERS[line.name].text, v / NUMBERS[line.name].scale, { n: v / NUMBERS[line.name].scale })
		},
		take(settings) {
			this.before = settings
			this.draft = settingsDraft(settings)
		},
		async load() {
			this.failure = ''
			try {
				this.take(((await accessApi.auditSettings()) || {}).settings)
			} catch (e) {
				this.failure = (e && e.message) || String(e)
			}
		},
		async save() {
			const patch = settingsPatch(this.before, this.draft)
			if (!Object.keys(patch).length) return
			this.saving = true
			this.error = ''
			try {
				this.take(((await accessApi.auditSettings(patch)) || {}).settings)
				this.review = false
				this.saved = true
			} catch (e) {
				this.error = this.$t(AREA + 'audit_set_error', { detail: (e && e.message) || String(e) })
			}
			this.saving = false
		}
	}
}
</script>

<style>
.activity-number { max-width: 320px; margin: 8px 0; }
.activity-lines { list-style: none; padding: 0; margin: 4px 0; }
</style>
