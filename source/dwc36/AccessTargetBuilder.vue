<template>
	<!-- Builds ONE target without typing its format: the plugin, the kind of thing and which one (all of them, or one by its name). The result is shown as a read-only chip
	     (workshop:plugin:type/id) with an example, and is added to the rule with "Add target". A wrong id is said next to the field.
	       <access-target-builder @add="pattern => ..." /> -->
	<div class="access-target-builder" data-part="target-builder">
		<div class="access-target-row">
			<label class="sv-label">{{ $t('plugins.WorkshopService.access.target_plugin') }}<sv-select v-model="plugin" :options="pluginOptions" :aria-label="$t('plugins.WorkshopService.access.target_plugin')" /></label>
			<label class="sv-label">{{ $t('plugins.WorkshopService.access.target_type') }}<sv-select v-model="type" :options="typeOptions" :aria-label="$t('plugins.WorkshopService.access.target_type')" /></label>
			<label class="sv-label">{{ $t('plugins.WorkshopService.access.target_which') }}<sv-select v-model="scope" :options="scopeOptions" :aria-label="$t('plugins.WorkshopService.access.target_which')" /></label>
			<div v-if="scope === 'one' && !picking" class="access-target-idbox" data-part="id-text">
				<div class="access-target-idhead"><span class="sv-label">{{ $t('plugins.WorkshopService.access.target_id') }}</span><help-tip :title="$t('plugins.WorkshopService.access.target_id')" :what="$t('plugins.WorkshopService.access.target_id_help_what')" :how="$t('plugins.WorkshopService.access.target_id_help_how')" /></div>
				<sv-text-field v-model="id" :invalid="!!idProblem" :error="idProblem ? $t('plugins.WorkshopService.access.' + idProblem) : ''" :aria-label="$t('plugins.WorkshopService.access.target_id')" @enter="add" />
			</div>
		</div>
		<access-target-pick v-if="scope === 'one' && picking" v-model="id" :options="options" :label="$t('plugins.WorkshopService.access.target_pick_label', { kind: kindName })" />
		<div v-if="idProblem && picking" class="access-problem access-target-problem" role="alert">{{ $t('plugins.WorkshopService.access.' + idProblem) }}</div>
		<div class="access-target-result">
			<span class="sv-chip-sm" data-part="pattern"><code>{{ pattern }}</code></span>
			<span class="access-target-says" data-part="says">{{ says }}</span>
			<v-btn small outlined class="access-touch" :disabled="!!idProblem" @click="add">{{ $t('plugins.WorkshopService.access.target_add') }}</v-btn>
		</div>
		<div class="wf-help">{{ $t('plugins.WorkshopService.access.target_example') }}</div>
	</div>
</template>

<script>
'use strict'

import SvSelect from './ui/SvSelect.vue'
import HelpTip from './HelpTip.vue'
import AccessTargetPick from './AccessTargetPick.vue'
import SvTextField from './ui/SvTextField.vue'
import { TARGET_ID_RE, TARGET_KINDS, TARGET_RE } from './access-profile-edit.js'
import { describeTarget, targetOptions } from './access-target-lists.js'

export default {
	components: { SvSelect, SvTextField, HelpTip, AccessTargetPick },
	data() {
		return { plugin: TARGET_KINDS[0][0], type: TARGET_KINDS[0][1][0], scope: 'all', id: '', options: null, asked: '' }
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
		// the real things of this kind, when the service has a list of them (a pellet profile, a scene...); null = a text box with its help
		picking() {
			return !!this.options && this.options.length > 0
		},
		kindName() {
			return this.$t('plugins.WorkshopService.access.target_kind_' + this.plugin + '_' + this.type)
		},
		// the target in words, under the technical chip: "Impresión: perfil de pellet «Pellet PETG»"
		says() {
			const names = {}
			names[this.plugin + ':' + this.type] = {}
			;(this.options || []).forEach(o => { names[this.plugin + ':' + this.type][o.id] = o.name })
			return describeTarget(this.pattern, (k, p) => this.$t('plugins.WorkshopService.access.' + k, p), names).text
		},
		idProblem() {
			if (this.scope === 'all') return ''
			if (!this.id.trim()) return this.picking ? 'target_id_pick_empty' : 'target_id_empty'
			return TARGET_ID_RE.test(this.id.trim()) && TARGET_RE.test(this.pattern) ? '' : 'target_id_form'
		}
	},
	watch: {
		// another plugin: its first kind of thing
		plugin(p) {
			const k = TARGET_KINDS.find(x => x[0] === p)
			if (k && k[1].indexOf(this.type) < 0) this.type = k[1][0]
		},
		// "one in particular": ask the service for the things of that kind (once a minute at most); a different kind starts again
		scope() { this.load() },
		type() { this.load() }
	},
	methods: {
		load() {
			this.options = null
			this.id = ''
			if (this.scope !== 'one') return
			const key = this.plugin + ':' + this.type
			this.asked = key
			targetOptions(this.plugin, this.type, (k, p) => this.$t('plugins.WorkshopService.access.' + k, p)).then(rows => {
				if (this.asked === key) this.options = rows
			})
		},
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
.access-target-result { display: flex; flex-wrap: wrap; align-items: center; gap: 8px 12px; margin: 12px 0 4px; }
.access-target-idhead { display: flex; align-items: center; gap: 4px; margin-bottom: 4px; }
.access-target-says { font-size: 13px; }
.access-target-problem { margin-top: 8px; }
.access-target-row .sv-field-error { margin-top: 8px; }
</style>
