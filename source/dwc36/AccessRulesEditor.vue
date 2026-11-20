<template>
	<!-- The Builder of a profile being edited: its rules (AccessRuleEditor), the two buttons that add one, the live summary and the fixed notes. The document is
	     the parent's: every edit emits input(doc) with a new copy. Under 900 px (accordion) one rule is open at a time.
	       <access-rules-editor :doc="draft" :ctx="context" :issues="[...]" :suggestions="[...]" :max="50" :accordion="false" @input="d => ..." /> -->
	<div class="access-builder access-builder-edit">
		<div class="access-h">{{ $t('plugins.WorkshopService.access.builder_rules_count', { n: rules.length, max }) }}</div>
		<div class="access-rule-add">
			<v-btn small outlined class="access-touch" :disabled="rules.length >= max" @click="add('allow')"><v-icon left small>mdi-plus</v-icon>{{ $t('plugins.WorkshopService.access.builder_add_allow') }}</v-btn>
			<v-btn small outlined class="access-touch" :disabled="rules.length >= max" @click="add('deny')"><v-icon left small>mdi-plus</v-icon>{{ $t('plugins.WorkshopService.access.builder_add_deny') }}</v-btn>
		</div>
		<div v-if="!rules.length" class="wf-help">{{ $t('plugins.WorkshopService.access.builder_no_rules') }}</div>
		<access-rule-editor
			v-for="(r, i) in rules"
			:key="'r' + i"
			:rule="r"
			:index="i + 1"
			:count="rules.length"
			:ctx="ctx"
			:suggestions="suggestions"
			:issues="issuesOf(r, i)"
			:accordion="accordion"
			:open="!accordion || openAt === i"
			@change="x => $emit('input', setRule(doc, i, x))"
			@up="$emit('input', moveRule(doc, i, -1))"
			@down="$emit('input', moveRule(doc, i, 1))"
			@remove="remove(i)"
			@toggle="openAt = openAt === i ? -1 : i" />
		<div class="wf-help access-summary">{{ $t('plugins.WorkshopService.access.builder_summary', { allow: $tc('plugins.WorkshopService.access.operations_n', summary.allow, { n: summary.allow }), deny: summary.deny }) }}</div>
		<div class="wf-help">{{ $t('plugins.WorkshopService.access.builder_order_note') }}</div>
		<div class="wf-help">{{ $t('plugins.WorkshopService.access.builder_when_unknown') }}</div>
	</div>
</template>

<script>
'use strict'

import AccessRuleEditor from './AccessRuleEditor.vue'
import { addRule, moveRule, removeRule, setRule } from './access-profile-edit.js'
import { ruleSummary } from './access-profile-view.js'

export default {
	components: { AccessRuleEditor },
	props: {
		doc: { type: Object, required: true },
		ctx: { type: Object, required: true },
		issues: { type: Array, default: () => [] },
		suggestions: { type: Array, default: () => [] },
		max: { type: Number, default: 50 },
		accordion: { type: Boolean, default: false }
	},
	data() {
		return { openAt: 0 }
	},
	computed: {
		rules() {
			return this.doc.rules || []
		},
		summary() {
			return ruleSummary(this.doc)
		}
	},
	methods: {
		setRule,
		moveRule,
		// the mistakes that name this rule (by its id, or by its place when it has none yet)
		issuesOf(rule, i) {
			return this.issues.filter(p => p.rule && (p.rule === rule.id || p.rule === String(i + 1)))
		},
		add(decision) {
			const d = addRule(this.doc, decision)
			this.openAt = d.rules.length - 1
			this.$emit('input', d)
		},
		remove(i) {
			this.openAt = 0
			this.$emit('input', removeRule(this.doc, i))
		}
	}
}
</script>

<style>
.access-rule-add { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 8px; }
</style>
