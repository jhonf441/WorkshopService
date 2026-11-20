<template>
	<!-- Builds ONE target without typing its format: the plugin, the kind of thing and which one (all of them, or one by its name). The result is shown as a read-only chip
	     (workshop:plugin:type/id) with an example, and is added to the rule with "Add target". A wrong id is said next to the field.
	       <access-target-builder @add="pattern => ..." /> -->
	<div class="access-target-builder" data-part="target-builder">
		<div class="access-target-row">
			<label class="sv-label">{{ $t('plugins.WorkshopService.access.target_plugin') }}<sv-select v-model="plugin" :options="pluginOptions" :aria-label="$t('plugins.WorkshopService.access.target_plugin')" /></label>
			<label class="sv-label">{{ $t('plugins.WorkshopService.access.target_type') }}<sv-select v-model="type" :options="typeOptions" :aria-label="$t('plugins.WorkshopService.access.target_type')" /></label>
			<label class="sv-label">{{ $t('plugins.WorkshopService.access.target_which') }}<sv-select v-model="scope" :options="scopeOptions" :aria-label="$t('plugins.WorkshopService.access.target_which')" /></label>
			<label v-if="scope === 'one'" class="sv-label">{{ $t('plugins.WorkshopService.access.target_id') }}<sv-text-field v-model="id" :invalid="!!idProblem" :aria-label="$t('plugins.WorkshopService.access.target_id')" @enter="add" /></label>
		</div>
		<div class="access-target-result">
			<span class="sv-chip-sm" data-part="pattern"><code>{{ pattern }}</code></span>
			<v-btn small outlined class="access-touch" :disabled="!!idProblem" @click="add">{{ $t('plugins.WorkshopService.access.target_add') }}</v-btn>
		</div>
		<div v-if="idProblem" class="access-problem" role="alert">{{ $t('plugins.WorkshopService.access.' + idProblem) }}</div>
		<div class="wf-help">{{ $t('plugins.WorkshopService.access.target_example') }}</div>
	</div>
</template>

<script>
'use strict'

import SvSelect from './ui/SvSelect.vue'
import SvTextField from './ui/SvTextField.vue'
import { TARGET_ID_RE, TARGET_KINDS, TARGET_RE } from './access-profile-edit.js'

export default {
	components: { SvSelect, SvTextField },
	data() {
		return { plugin: TARGET_KINDS[0][0], type: TARGET_KINDS[0][1][0], scope: 'all', id: '' }
	},
	computed: {
		pluginOptions() {
			return TARGET_KINDS.map(k => ({ value: k[0], label: this.$t('plugins.WorkshopService.access.target_plugin_' + k[0]) }))
		},
		typeOptions() {
			const k = TARGET_KINDS.find(x => x[0] === this.plugin)
			return (k ? k[1] : []).map(t => ({ value: t, label: this.$t('plugins.WorkshopService.access.target_kind_' + this.plugin + '_' + t) }))
		},
		scopeOptions() {
			return [{ value: 'all', label: this.$t('plugins.WorkshopService.access.target_all') }, { value: 'one', label: this.$t('plugins.WorkshopService.access.target_one') }]
		},
		pattern() {
			return 'workshop:' + this.plugin + ':' + this.type + '/' + (this.scope === 'all' ? '*' : this.id.trim() || '...')
		},
		idProblem() {
			if (this.scope === 'all') return ''
			if (!this.id.trim()) return 'target_id_empty'
			return TARGET_ID_RE.test(this.id.trim()) && TARGET_RE.test(this.pattern) ? '' : 'target_id_form'
		}
	},
	watch: {
		// another plugin: its first kind of thing
		plugin(p) {
			const k = TARGET_KINDS.find(x => x[0] === p)
			if (k && k[1].indexOf(this.type) < 0) this.type = k[1][0]
		}
	},
	methods: {
		add() {
			if (this.idProblem) return
			this.$emit('add', this.pattern)
			this.id = ''
		}
	}
}
</script>

<style>
.access-target-row { display: flex; flex-wrap: wrap; align-items: flex-end; gap: 8px 12px; }
.access-target-row .sv-label { display: flex; flex-direction: column; gap: 4px; }
.access-target-result { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; margin: 8px 0 4px; }
</style>
