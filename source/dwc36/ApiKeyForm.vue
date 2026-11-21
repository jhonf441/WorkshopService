<template>
	<!-- The fields of the dialog to create or edit a key (ApiKeys owns the form, the dialog and the calls). Props: form, operations (the API description), catalog
	     (roles.list capabilities), preview (what keys.preview allows), previewError, errorForm. Emits `preset` (the starting point chosen). -->
	<div>
		<v-text-field v-model="form.name" :label="$t('plugins.WorkshopService.keys.service_name')" dense outlined counter="40" :rules="[v => !!v || '']" />
		<v-select
			v-if="!form.id" v-model="form.preset" :items="presetItems" :label="$t('plugins.WorkshopService.keys.starting_point')"
			dense outlined hide-details class="mb-3" :menu-props="menuProps" :title="presetTitle" @change="$emit('preset', $event)"
		/>
		<div class="text-caption grey--text mb-1">{{ $t('plugins.WorkshopService.keys.classes') }}</div>
		<div class="d-flex flex-wrap mb-2">
			<v-checkbox
				v-for="c in classes" :key="c" v-model="form.kinds" :value="c" dense hide-details class="mr-4 mt-0"
				:label="nameClass(c)"
			/>
		</div>
		<div class="text-caption grey--text mb-2">{{ $t('plugins.WorkshopService.keys.classes_help') }}</div>
		<wf-field id="ws-key-ops" :label="$t('plugins.WorkshopService.keys.extra_operations')">
			<template #help>
				<help-tip :title="$t('plugins.WorkshopService.keys.extra_operations')" :what="$t('plugins.WorkshopService.keys.help_extra_what')" :why="$t('plugins.WorkshopService.keys.patterns_help')" :how="$t('plugins.WorkshopService.keys.help_patterns_how')" />
			</template>
			<v-combobox
				id="ws-key-ops" v-model="form.ops" :items="opItems" item-text="text" item-value="value" multiple chips small-chips deletable-chips
				:aria-label="$t('plugins.WorkshopService.keys.extra_operations')" hide-details dense outlined :menu-props="menuProps" :return-object="false" @change="form.ops = norm(form.ops)"
			>
				<template v-slot:selection="{ item, parent }">
					<v-chip small close :title="descriptionOp(item)" @click:close="parent.selectItem(item)">
						<v-icon v-if="isCap(item)" small left>mdi-shape-outline</v-icon>{{ isCap(item) ? capTitle(item) : item }}
					</v-chip>
				</template>
				<template v-slot:item="{ item }">
					<v-list-item-content>
						<v-list-item-title><code>{{ item.value }}</code> <span class="text-caption grey--text">{{ item.cssClass }}</span></v-list-item-title>
						<v-list-item-subtitle>{{ item.desc }}</v-list-item-subtitle>
					</v-list-item-content>
				</template>
			</v-combobox>
		</wf-field>
		<wf-field id="ws-key-deny" :label="$t('plugins.WorkshopService.keys.refused_operations')" class="mt-2">
			<template #help>
				<help-tip :title="$t('plugins.WorkshopService.keys.refused_operations')" :what="$t('plugins.WorkshopService.keys.help_refused_what')" :why="$t('plugins.WorkshopService.keys.patterns_help')" :how="$t('plugins.WorkshopService.keys.help_patterns_how')" />
			</template>
			<v-combobox
				id="ws-key-deny" v-model="form.deny" :items="opItems" item-text="text" item-value="value" multiple chips small-chips deletable-chips
				:aria-label="$t('plugins.WorkshopService.keys.refused_operations')" hide-details dense outlined :menu-props="menuProps" :return-object="false" @change="form.deny = norm(form.deny)"
			>
				<template v-slot:selection="{ item, parent }">
					<v-chip small close :title="descriptionOp(item)" @click:close="parent.selectItem(item)">
						<v-icon v-if="isCap(item)" small left>mdi-shape-outline</v-icon>{{ isCap(item) ? capTitle(item) : item }}
					</v-chip>
				</template>
				<template v-slot:item="{ item }">
					<v-list-item-content>
						<v-list-item-title><code>{{ item.value }}</code> <span class="text-caption grey--text">{{ item.cssClass }}</span></v-list-item-title>
						<v-list-item-subtitle>{{ item.desc }}</v-list-item-subtitle>
					</v-list-item-content>
				</template>
			</v-combobox>
		</wf-field>
		<wf-field id="ws-key-cap" :label="$t('plugins.WorkshopService.keys.cap_title')" class="mt-2">
			<template #help>
				<help-tip :title="$t('plugins.WorkshopService.keys.cap_title')" :what="$t('plugins.WorkshopService.keys.cap_help_what')" :why="$t('plugins.WorkshopService.keys.cap_help_why')" :how="$t('plugins.WorkshopService.keys.cap_help_how')" />
			</template>
			<div v-if="!capItems.length" class="text-caption grey--text">{{ $t('plugins.WorkshopService.keys.cap_catalog_missing') }}</div>
			<div v-else class="d-flex align-center flex-wrap">
				<v-autocomplete
					id="ws-key-cap" v-model="capPick" :items="capItems" item-text="text" item-value="value" :placeholder="$t('plugins.WorkshopService.keys.cap_pick')"
					:aria-label="$t('plugins.WorkshopService.keys.cap_title')" clearable hide-details dense outlined class="flex-grow-1 mr-2" :menu-props="capMenuProps"
				>
					<template v-slot:item="{ item }">
						<v-list-item-content v-if="item.header" class="text-overline">{{ item.header }}</v-list-item-content>
						<v-list-item-content v-else>
							<v-list-item-title>{{ item.text }} <span class="text-caption grey--text">{{ item.meta }}</span></v-list-item-title>
							<v-list-item-subtitle>{{ item.value }}</v-list-item-subtitle>
						</v-list-item-content>
					</template>
				</v-autocomplete>
				<v-btn small color="primary" class="mr-1" :disabled="!capPick || !capGrantable(capPick)" @click="addCap('ops')">{{ $t('plugins.WorkshopService.keys.cap_allow') }}</v-btn>
				<v-btn small color="error" outlined :disabled="!capPick" @click="addCap('deny')">{{ $t('plugins.WorkshopService.keys.cap_refuse') }}</v-btn>
			</div>
			<div v-if="capPick && !capGrantable(capPick)" class="text-caption warning--text mt-1">{{ $t('plugins.WorkshopService.keys.cap_not_for_keys') }}</div>
		</wf-field>
		<wf-field id="ws-key-days" :label="$t('plugins.WorkshopService.keys.valid_days')" :message="$t('plugins.WorkshopService.keys.' + (form.id ? 'valid_days_help_edit' : 'valid_days_help'))" class="mt-2" style="max-width:280px">
			<sv-text-field id="ws-key-days" v-model="form.days" type="number" :min="form.id ? 0 : 1" max="3650" step="1" inputmode="numeric" :invalid="!!daysError" :error="daysError" :aria-label="$t('plugins.WorkshopService.keys.valid_days')" />
		</wf-field>
		<v-alert v-if="form.id && form.strict === false" dense text type="warning" class="mt-3 mb-0">{{ $t('plugins.WorkshopService.keys.cap_legacy_hint') }}</v-alert>
		<v-alert v-if="previewError" dense text type="error" class="mt-3 mb-0">{{ previewError }}</v-alert>
		<v-alert v-else dense text type="info" class="mt-3 mb-0">
			{{ $tc('plugins.WorkshopService.keys.preview', viewPreview.length, { n: viewPreview.length }) }}
			<div class="text-caption" style="max-height:110px;overflow:auto">{{ viewPreview.join(', ') || '-' }}</div>
		</v-alert>
		<v-alert dense text type="warning" class="mt-2 mb-0">{{ $t('plugins.WorkshopService.keys.never_admin') }}</v-alert>
		<v-alert v-if="errorForm" dense text type="error" class="mt-2 mb-0">{{ errorForm }}</v-alert>
	</div>
</template>

<script>
'use strict'

import SvTextField from './ui/SvTextField.vue'
import { CAP_PREFIX } from './key-names.js'
import { keyNamesMixin, normPatterns, daysProblem } from './api-key-names-mixin.js'
import HelpTip from './HelpTip.vue'
import WfField from './WfField.vue'

const CLASES = ['read', 'write', 'motion', 'stop', 'power']
const PRESETS = ['read', 'lights_air', 'notify', 'control', 'full', 'custom']
const CAT_ORDER = ['machine', 'jobs', 'lights', 'energy', 'activity', 'camera', 'security', 'config', 'system']

export default {
	name: 'ApiKeyForm',
	components: { SvTextField, HelpTip, WfField },
	mixins: [keyNamesMixin],
	props: {
		form: { type: Object, required: true },
		operations: { type: Array, default: () => [] },
		catalog: { type: Array, default: () => [] },
		preview: { type: Array, default: () => [] },
		previewError: { type: String, default: '' },
		errorForm: { type: String, default: '' }
	},
	data() {
		return { capPick: null }
	},
	computed: {
		classes() { return CLASES },
		menuProps() { return { maxWidth: 600, contentClass: 'ws-keys-menu' } },
		capMenuProps() { return this.menuProps },
		presetTitle() {
			const it = this.presetItems.find(i => i.value === this.form.preset)
			return it ? it.text : ''
		},
		presetItems() {
			return PRESETS.map(p => ({ value: p, text: this.$t('plugins.WorkshopService.keys.preset_' + p) }))
		},
		viewPreview() { return this.preview },
		daysError() { return daysProblem(this.form.days, !!this.form.id) ? this.$t('plugins.WorkshopService.keys.days_invalid') : '' },
		// the capabilities of roles.list (title, category, class, risk, delegable) grouped by category, to pick from
		capItems() {
			const out = []
			for (const cat of CAT_ORDER) {
				const list = this.catalog.filter(c => c.category === cat)
				if (!list.length) continue
				out.push({ header: this.$t('plugins.WorkshopService.keys.cap_group_' + cat) })
				for (const c of list) out.push({ text: c.title || c.id, value: c.id, meta: this.$t('plugins.WorkshopService.keys.cap_risk') + ' ' + c.risk + '/4' })
			}
			return out
		},
		// every operation of the service (except administration, never given to a key) to pick from
		opItems() {
			return this.operations.filter(o => o.kind !== 'admin').map(o => ({ text: o.op, value: o.op, cssClass: this.nameClass(o.kind), desc: o.desc || '' }))
		}
	},
	methods: {
		norm: normPatterns,
		addCap(field) {
			if (!this.capPick) return
			const e = CAP_PREFIX + this.capPick
			if (!this.form[field].includes(e)) this.form[field] = [...this.form[field], e]
			this.capPick = null
		}
	}
}
</script>
