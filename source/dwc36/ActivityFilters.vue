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
		<p class="wf-help mt-1" data-part="filters-help">{{ $t('plugins.WorkshopService.access.audit_f_denied_help') }}</p>
		<!-- one grid: every field the same height, the label always above -->
		<div v-if="open" class="activity-more" data-part="more">
			<div class="activity-field"><label class="sv-label" for="af-user">{{ $t('plugins.WorkshopService.access.audit_f_person') }}</label><sv-select id="af-user" :value="value.user" :items="users" clearable @input="set('user', $event || '')" /></div>
			<div class="activity-field"><label class="sv-label" for="af-group">{{ $t('plugins.WorkshopService.access.audit_f_group') }}</label><sv-select id="af-group" :value="value.group" :items="groups" clearable @input="set('group', $event || '')" /></div>
			<div class="activity-field"><label class="sv-label" for="af-op">{{ $t('plugins.WorkshopService.access.audit_f_operation') }}</label><sv-text-field id="af-op" :value="value.op" @input="set('op', $event || '')" /></div>
			<div class="activity-field"><label class="sv-label" for="af-target">{{ $t('plugins.WorkshopService.access.audit_f_target') }}</label><sv-text-field id="af-target" :value="value.target" placeholder="workshop:camera:camera/cam2" @input="set('target', $event || '')" /></div>
			<div class="activity-field"><label class="sv-label" for="af-result">{{ $t('plugins.WorkshopService.access.audit_f_result') }}</label><sv-select id="af-result" :value="value.result" :items="results" clearable @input="set('result', $event || '')" /></div>
			<div class="activity-field activity-clear"><button type="button" class="sv-btn sv-text" @click="$emit('clear')">{{ $t('plugins.WorkshopService.access.audit_f_clear') }}</button></div>
		</div>
	</div>
</template>

<script>
'use strict'

import SvTextField from './ui/SvTextField.vue'
import SvSelect from './ui/SvSelect.vue'
import RangePicker from './RangePicker.vue'
import { RESULTS } from './access-audit-view.js'

export default {
	components: { SvTextField, SvSelect, RangePicker },
	props: {
		value: { type: Object, required: true },
		users: { type: Array, default: () => [] },
		groups: { type: Array, default: () => [] },
		startOpen: { type: Boolean, default: false }
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
		}
	},
	methods: {
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
.activity-main { align-items: center; }
</style>
