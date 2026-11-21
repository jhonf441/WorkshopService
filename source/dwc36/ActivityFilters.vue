<template>
	<!-- The filters of the recorded activity. The range, "only refusals", "only refused or failed" and "detail" are always in reach (tappable chips); the rest
	     folds under "More filters". The value is one object, the screen owns it:
	       <activity-filters :value="f" :users="[...]" :groups="[...]" @input="f = $event" @clear="..." /> -->
	<div class="activity-filters">
		<div class="access-filters activity-main">
			<range-picker :value="value.range" @input="set('range', $event)" />
			<button v-for="c in chips" :key="c.id" type="button" class="sv-btn activity-chip" :class="{ 'sv-on': value[c.id] }" :aria-pressed="value[c.id] ? 'true' : 'false'" @click="set(c.id, !value[c.id])">{{ $t('plugins.WorkshopService.access.' + c.key) }}</button>
			<button type="button" class="sv-btn" :aria-expanded="open ? 'true' : 'false'" @click="open = !open"><span class="mdi mdi-filter-variant sv-ico sv-ico-s" aria-hidden="true" />{{ $t('plugins.WorkshopService.access.audit_f_more') }}</button>
		</div>
		<div v-if="active.length" class="activity-active" role="group" data-part="active-filters" :aria-label="$t('plugins.WorkshopService.access.audit_f_active')">
			<span class="sv-label">{{ $t('plugins.WorkshopService.access.audit_f_active') }}</span>
			<span v-for="c in active" :key="c.id" class="sv-chip-sm activity-active-chip" :data-filter="c.id">{{ c.text }}<button type="button" class="sv-btn sv-text activity-active-x" :aria-label="$t('plugins.WorkshopService.access.audit_f_remove_one', { what: c.text })" :title="$t('plugins.WorkshopService.access.audit_f_remove_one', { what: c.text })" @click="removeOne(c.id)"><span class="mdi mdi-close sv-ico sv-ico-s" aria-hidden="true" /></button></span>
			<button type="button" class="sv-btn sv-text" data-act="clear-filters" @click="$emit('clear')">{{ $t('plugins.WorkshopService.access.audit_f_clear') }}</button>
			<span v-if="origin" class="wf-help" data-part="filter-origin">{{ origin }}</span>
		</div>
		<p class="wf-help mt-1" data-part="filters-help">{{ $t('plugins.WorkshopService.access.audit_f_denied_help') }}</p>
		<!-- one grid: every field the same height, the label always above -->
		<div v-if="open" class="activity-more" data-part="more">
			<div class="activity-field"><label class="sv-label" for="af-user">{{ $t('plugins.WorkshopService.access.audit_f_person') }}</label><sv-select id="af-user" :value="value.user" :items="users" clearable @input="set('user', $event || '')" /></div>
			<div class="activity-field"><label class="sv-label" for="af-group">{{ $t('plugins.WorkshopService.access.audit_f_group') }}</label><sv-select id="af-group" :value="value.group" :items="groups" clearable @input="set('group', $event || '')" /></div>
			<div class="activity-field" data-part="op-field"><span class="activity-label"><label class="sv-label" for="af-op">{{ $t('plugins.WorkshopService.access.audit_f_operation') }}</label><help-tip :title="$t('plugins.WorkshopService.access.audit_f_operation')" :what="$t('plugins.WorkshopService.access.audit_f_op_help_what')" :how="$t('plugins.WorkshopService.access.audit_f_op_help_how')" /></span><sv-combo id="af-op" :value="value.op" :options="opOptions" allow-free :placeholder="$t('plugins.WorkshopService.access.audit_f_op_placeholder')" :aria-label="$t('plugins.WorkshopService.access.audit_f_operation')" :none-text="$t('plugins.WorkshopService.access.audit_f_none')" :clear-label="$t('plugins.WorkshopService.access.audit_f_any')" @input="set('op', $event || '')" /></div>
			<div class="activity-field"><span class="activity-label"><label class="sv-label" for="af-target">{{ $t('plugins.WorkshopService.access.audit_f_target') }}</label><help-tip :title="$t('plugins.WorkshopService.access.audit_f_target')" :what="$t('plugins.WorkshopService.access.audit_f_target_help_what')" :how="$t('plugins.WorkshopService.access.audit_f_target_help_how')" /></span><sv-combo id="af-target" :value="value.target" :options="targetOptions" allow-free :placeholder="$t('plugins.WorkshopService.access.audit_f_target_placeholder')" :aria-label="$t('plugins.WorkshopService.access.audit_f_target')" :none-text="$t('plugins.WorkshopService.access.audit_f_none')" :clear-label="$t('plugins.WorkshopService.access.audit_f_any')" @input="set('target', $event || '')" /></div>
			<div class="activity-field"><label class="sv-label" for="af-result">{{ $t('plugins.WorkshopService.access.audit_f_result') }}</label><sv-select id="af-result" :value="value.result" :items="results" clearable @input="set('result', $event || '')" /></div>
			<div class="activity-field activity-clear"><button type="button" class="sv-btn sv-text" @click="$emit('clear')">{{ $t('plugins.WorkshopService.access.audit_f_clear') }}</button></div>
		</div>
	</div>
</template>

<script>
'use strict'

import SvCombo from './ui/SvCombo.vue'
import HelpTip from './HelpTip.vue'
import { describeTarget } from './access-target-lists.js'
import SvSelect from './ui/SvSelect.vue'
import RangePicker from './RangePicker.vue'
import { RESULTS } from './access-audit-view.js'

export default {
	components: { SvCombo, HelpTip, SvSelect, RangePicker },
	props: {
		value: { type: Object, required: true },
		users: { type: Array, default: () => [] },
		groups: { type: Array, default: () => [] },
		startOpen: { type: Boolean, default: false },
		operations: { type: Array, default: () => [] }, // the API description ({ op, desc }): what the operation box offers
		seenOps: { type: Array, default: () => [] }, // operations that appear in the record (also the ones the description does not know any more)
		seenTargets: { type: Array, default: () => [] }, // targets that appear in the record
		origin: { type: String, default: '' } // where the filters on screen came from, when a button put them there
	},
	data() {
		return {
			open: this.startOpen,
			chips: [{ id: 'denied', key: 'audit_f_denied_only' }, { id: 'errors', key: 'audit_f_errors' }, { id: 'detail', key: 'audit_f_detail' }]
		}
	},
	computed: {
		results() {
			return RESULTS.map(r => ({ value: r, text: this.$t('plugins.WorkshopService.access.audit_f_result_' + r) }))
		},
		// the real operations with their meaning (first sentence of the description) grouped by area, then the ones only the record knows
		opOptions() {
			const out = []
			const known = {}
			this.operations.filter(o => o && o.op).forEach(o => {
				known[o.op] = true
				const seg = String(o.op).split('.')[0]
				const key = 'plugins.WorkshopService.apiGroups.' + seg
				out.push({ value: o.op, label: String(o.desc || '').split(/(?<=[.!?])\s/)[0] || o.op, hint: o.op, group: this.$te(key) ? this.$t(key) : seg })
			})
			this.seenOps.filter(op => op && !known[op]).forEach(op => out.push({ value: op, label: op, hint: op, group: this.$t('plugins.WorkshopService.access.audit_f_in_record') }))
			return out.sort((a, b) => (a.group + a.value).localeCompare(b.group + b.value))
		},
		// the targets that appear in the record of the period, with a sentence ("Cámara: todas las cámaras") and the technical pattern small
		targetOptions() {
			return this.seenTargets.map(t => ({ value: t, label: this.say(t), hint: t })).sort((a, b) => a.label.localeCompare(b.label))
		},
		// what is filtering now (a quiet range and the "detail" chip show themselves); each one can be taken off
		active() {
			const v = this.value
			const out = []
			const t = k => this.$t('plugins.WorkshopService.access.' + k)
			if (v.user) out.push({ id: 'user', text: t('audit_f_person') + ': ' + v.user })
			if (v.group) out.push({ id: 'group', text: t('audit_f_group') + ': ' + v.group })
			if (v.op) out.push({ id: 'op', text: t('audit_f_operation') + ': ' + (this.opLabel(v.op) || v.op) })
			if (v.target) out.push({ id: 'target', text: t('audit_f_target') + ': ' + this.say(v.target) })
			if (v.result) out.push({ id: 'result', text: t('audit_f_result') + ': ' + t('audit_f_result_' + v.result) })
			if (v.denied) out.push({ id: 'denied', text: t('audit_f_denied_only') })
			if (v.errors) out.push({ id: 'errors', text: t('audit_f_errors') })
			return out
		}
	},
	methods: {
		say(t) {
			return describeTarget(t, (k, p) => this.$t('plugins.WorkshopService.access.' + k, p), {}).text
		},
		opLabel(op) {
			const o = this.opOptions.find(x => x.value === op)
			return o && o.label !== op ? o.label + ' (' + op + ')' : ''
		},
		removeOne(id) {
			this.$emit('input', Object.assign({}, this.value, { [id]: id === 'denied' || id === 'errors' ? false : '' }))
		},
		set(key, v) {
			this.$emit('input', Object.assign({}, this.value, { [key]: v }))
		}
	}
}
</script>

<style>
.activity-more { display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap: 12px 16px; align-items: start; margin: 12px 0 24px; }
.activity-field { display: flex; flex-direction: column; min-width: 0; }
.activity-field .sv-label { margin: 0 0 4px; }
.activity-field .v-input__control, .activity-field .v-input__slot { min-height: 44px !important; height: 44px; }
.activity-field .v-select__selections, .activity-field .v-text-field__slot input { min-height: 40px !important; padding: 0; }
.activity-clear { align-self: end; align-items: flex-start; }
.activity-label { display: flex; align-items: center; justify-content: space-between; gap: 4px; min-height: 28px; }
.activity-field .sv-combo-input { min-height: 44px; }
.activity-active { display: flex; align-items: center; flex-wrap: wrap; gap: 8px 12px; margin: 12px 0 0; }
.activity-active-chip { display: inline-flex; align-items: center; gap: 4px; }
.activity-active-x { min-width: 44px; min-height: 44px; padding: 0; }
.activity-main { align-items: center; }
</style>
