<template>
	<!-- One rule of a profile being edited: its name, what it does (capabilities by category and single operations), on which targets and only when.
	     Emits change(rule) with a new copy of the rule, and up, down, remove. Moving a rule only orders the reading: a deny always wins.
	       <access-rule-editor :rule="r" :index="1" :count="2" :ctx="context" :suggestions="[...]" :issues="[...]" @change="r => ..." @up @down @remove /> -->
	<div class="access-rule access-rule-edit" :class="'access-rule--' + rule.decision">
		<div class="access-rule-head">
			<span class="access-rule-n">{{ index }}</span>
			<sv-text-field :value="rule.id" class="access-rule-id-field" :label="$t('plugins.WorkshopService.access.builder_rule_id')" @input="setId" />
			<v-chip small outlined label :color="rule.decision === 'allow' ? 'success' : 'error'">{{ $t('plugins.WorkshopService.access.builder_decision_' + rule.decision) }}</v-chip>
			<v-spacer />
			<v-btn small outlined class="access-touch" :disabled="index <= 1" :aria-label="$t('plugins.WorkshopService.access.builder_rule_up')" @click="$emit('up')"><v-icon small>mdi-arrow-up</v-icon></v-btn>
			<v-btn small outlined class="access-touch" :disabled="index >= count" :aria-label="$t('plugins.WorkshopService.access.builder_rule_down')" @click="$emit('down')"><v-icon small>mdi-arrow-down</v-icon></v-btn>
			<v-btn small outlined class="access-touch" :aria-label="$t('plugins.WorkshopService.access.builder_rule_remove')" @click="$emit('remove')"><v-icon small>mdi-delete-outline</v-icon></v-btn>
			<v-btn v-if="accordion" small text class="access-touch" :aria-expanded="open ? 'true' : 'false'" @click="$emit('toggle')"><v-icon small>{{ open ? 'mdi-chevron-up' : 'mdi-chevron-down' }}</v-icon></v-btn>
		</div>
		<div v-for="(p, i) in issues" :key="'i' + i" class="access-problem" role="alert">{{ $t('plugins.WorkshopService.access.check_' + p.code, p.params) }}</div>
		<div v-if="open" class="access-rule-body">
			<div class="access-h">{{ $t('plugins.WorkshopService.access.builder_what') }}</div>
			<access-rule-caps :groups="groups" :operations="rule.operations" @toggle="e => $emit('change', toggle(e))" />
			<div class="access-rule-line">
				<span class="access-rule-label">{{ $t('plugins.WorkshopService.access.builder_loose_ops') }}</span>
				<access-chip-input :items="looseOps" :suggestions="suggestions" :options="opOptions" :validate="checkEntry" :placeholder="$t('plugins.WorkshopService.access.builder_loose_placeholder')" @add="e => $emit('change', add(e))" @remove="e => $emit('change', toggle(e))" />
			</div>
			<div class="wf-help access-rule-note" data-part="loose-help">{{ $t('plugins.WorkshopService.access.builder_loose_help') }}</div>
			<div class="access-rule-line">
				<span class="access-rule-label">{{ $t('plugins.WorkshopService.access.builder_target_some') }}</span>
				<span class="access-rule-radios" role="radiogroup" :aria-label="$t('plugins.WorkshopService.access.builder_target_some')">
					<access-toggle radio :label="$t('plugins.WorkshopService.access.builder_target_all')" :on="!someSelected" @click="$emit('change', retarget([]))" />
					<access-toggle radio :label="$t('plugins.WorkshopService.access.builder_target_some')" :on="someSelected" @click="someTargets = true" />
				</span>
			</div>
			<div v-if="someSelected" class="access-rule-line">
				<access-target-builder @add="t => $emit('change', retarget(targets.concat([t])))" />
				<access-chip-input :items="targets" no-field :validate="checkTarget" :placeholder="$t('plugins.WorkshopService.access.builder_target_placeholder')" @add="t => $emit('change', retarget(targets.concat([t])))" @remove="t => $emit('change', retarget(targets.filter(x => x !== t)))" />
				<div class="wf-help access-rule-note" data-part="no-table">{{ $t('plugins.WorkshopService.access.builder_target_no_table') }}</div>
			</div>
			<div class="access-h mt-2">{{ $t('plugins.WorkshopService.access.builder_when') }}</div>
			<access-rule-when :when="rule.when || null" @set="(k, v) => $emit('change', when(k, v))" />
		</div>
	</div>
</template>

<script>
'use strict'

import SvTextField from './ui/SvTextField.vue'
import AccessRuleCaps from './AccessRuleCaps.vue'
import AccessRuleWhen from './AccessRuleWhen.vue'
import AccessChipInput from './AccessChipInput.vue'
import AccessToggle from './AccessToggle.vue'
import AccessTargetBuilder from './AccessTargetBuilder.vue'
import { opsSource } from './access-ops-source.js'
import { addEntry, offered, setTargets, setWhen, stopDenied, toggleEntry, undelegable, TARGET_RE, NS_OP_RE, OP_RE, UI_OP_RE } from './access-profile-edit.js'

export default {
	components: { SvTextField, AccessRuleCaps, AccessRuleWhen, AccessChipInput, AccessToggle, AccessTargetBuilder },
	props: {
		rule: { type: Object, required: true },
		index: { type: Number, default: 1 },
		count: { type: Number, default: 1 },
		ctx: { type: Object, required: true },
		suggestions: { type: Array, default: () => [] },
		issues: { type: Array, default: () => [] },
		accordion: { type: Boolean, default: false },
		open: { type: Boolean, default: true }
	},
	data() {
		return { someTargets: false }
	},
	computed: {
		groups() {
			return offered(this.ctx, this.rule.decision)
		},
		// the operations the service has, with their meaning in the language of the page, grouped by what they are about: the valid values of the box of single operations
		opOptions() {
			const ops = opsSource.ops
			return ops.filter(o => o && o.op).map(o => {
				const seg = String(o.op).split('.')[0]
				const key = 'plugins.WorkshopService.apiGroups.' + seg
				const group = this.$te(key) ? this.$t(key) : seg
				return { value: o.op, label: String(o.desc || '').split(/(?<=[.!?])\s/)[0], group }
			})
		},
		looseOps() {
			return (this.rule.operations || []).filter(e => e.indexOf('cap:') !== 0)
		},
		targets() {
			return this.rule.targets || []
		},
		// one radio of the two is on, never both: "some" while there are targets or the person asked to write some
		someSelected() {
			return this.targets.length > 0 || this.someTargets
		}
	},
	methods: {
		setId(v) {
			const r = Object.assign({}, this.rule, { id: String(v || '') })
			this.$emit('change', r)
		},
		toggle(e) {
			return toggleEntry(this.rule, e)
		},
		add(e) {
			return addEntry(this.rule, e)
		},
		retarget(list) {
			if (!list.length) this.someTargets = false
			return setTargets(this.rule, list)
		},
		when(k, v) {
			return setWhen(this.rule, k, v)
		},
		// what is typed in the box of single operations: an operation, a pattern or <ns>:<name> (a capability is picked with its box, not typed);
		// a stop is refused in a deny rule and what nobody can be granted in an allow rule, before the service says so
		checkEntry(t) {
			if (t.indexOf('cap:') === 0 || t.indexOf('tier:') === 0) return 'check_entry'
			if (!(OP_RE.test(t) || UI_OP_RE.test(t) || NS_OP_RE.test(t))) return 'check_entry'
			if (this.rule.decision === 'deny' && stopDenied(t, this.ctx)) return 'check_stop_deny'
			if (this.rule.decision === 'allow' && undelegable(t, this.ctx)) return 'check_undelegable'
			return ''
		},
		checkTarget(t) {
			return t === '*' || TARGET_RE.test(t) ? '' : 'check_target_form'
		}
	}
}
</script>

<style>
.access-rule-edit .access-rule-id-field { max-width: 220px; }
.access-rule-body { margin-top: 8px; }
.access-rule-edit .access-rule-line { margin-top: 8px; }
</style>
