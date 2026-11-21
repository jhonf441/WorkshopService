<template>
	<!-- The Builder of a profile being edited: its rules (AccessRuleEditor), the two buttons that add one, the live summary and the fixed notes. The document
	     is the parent's: every edit emits input(doc) with a new copy. Under 900 px (accordion) one rule is open at a time.
	     A rule is added only when the ones already there are complete (the buttons say why they are off, as text under them), and the new one is brought into
	     view, marked for a moment and its name field gets the focus (the screen reader hears "Rule N added").
	       <access-rules-editor :doc="draft" :ctx="context" :issues="[...]" :suggestions="[...]" :max="50" :accordion="false" @input="d => ..." /> -->
	<div ref="top" class="access-builder access-builder-edit">
		<div class="access-h access-rules-title" data-part="rules-count">
			{{ $t('plugins.WorkshopService.access.builder_rules_count', { n: rules.length, max }) }}
			<help-tip :title="$t('plugins.WorkshopService.access.builder_rules_help_title')" :what="$t('plugins.WorkshopService.access.builder_rules_help_what')" :why="$t('plugins.WorkshopService.access.builder_rules_help_why')" />
		</div>
		<div class="access-rule-add">
			<v-btn small outlined class="access-touch access-add access-add--allow" data-decision="allow" :aria-disabled="blocked ? 'true' : 'false'" :class="{ 'is-blocked': blocked }" :aria-describedby="blocked ? 'access-add-why' : null" @click="add('allow')"><v-icon left small>mdi-plus</v-icon>{{ $t('plugins.WorkshopService.access.builder_add_allow') }}</v-btn>
			<v-btn small outlined class="access-touch access-add access-add--deny" data-decision="deny" :aria-disabled="blocked ? 'true' : 'false'" :class="{ 'is-blocked': blocked }" :aria-describedby="blocked ? 'access-add-why' : null" @click="add('deny')"><v-icon left small>mdi-plus</v-icon>{{ $t('plugins.WorkshopService.access.builder_add_deny') }}</v-btn>
			<span v-if="farNote" class="sv-chip-sm" role="status" data-part="far-note">{{ farNote }}</span>
		</div>
		<div v-if="blocked" id="access-add-why" class="wf-help access-add-why" :class="{ 'is-attention': nudge }" data-part="add-reason">{{ $t('plugins.WorkshopService.access.' + blocked.key, blocked.params) }}</div>
		<span class="sv-vh" role="status" aria-live="polite" data-part="said">{{ said }}</span>
		<div v-if="!rules.length" class="wf-help">{{ $t('plugins.WorkshopService.access.builder_no_rules') }}</div>
		<access-rule-editor
			v-for="(r, i) in rules"
			ref="ruleEls"
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
import HelpTip from './HelpTip.vue'
import { addRule, removeRule, setRule } from './access-profile-edit.js'
import { ruleSummary } from './access-profile-view.js'
import { revealMixin } from './reveal-mixin.js'
import { revealResult } from './reveal.js'
import { addBlock, FLASH_MS } from './access-rule-focus.js'

export default {
	components: { AccessRuleEditor, HelpTip },
	mixins: [revealMixin],
	props: {
		doc: { type: Object, required: true },
		ctx: { type: Object, required: true },
		issues: { type: Array, default: () => [] },
		suggestions: { type: Array, default: () => [] },
		max: { type: Number, default: 50 },
		accordion: { type: Boolean, default: false }
	},
	data() {
		return { openAt: 0, nudge: false }
	},
	computed: {
		rules() {
			return this.doc.rules || []
		},
		summary() {
			return ruleSummary(this.doc)
		},
		// why a rule cannot be added now ({ key, params }) or null: the buttons are off while one rule is empty or wrong, and at the limit
		blocked() {
			return addBlock(this.rules, this.max, this.issuesOf)
		}
	},
	beforeDestroy() {
		clearTimeout(this.nudgeTimer)
	},
	methods: {
		setRule,
		// the mistakes that name this rule (by its id, or by its place when it has none yet)
		issuesOf(rule, i) {
			return this.issues.filter(p => p.rule && (p.rule === rule.id || p.rule === String(i + 1)))
		},
		add(decision) {
			if (this.blocked) return this.attend() // aria-disabled: the button still gets the touch, it says why it does nothing
			const d = addRule(this.doc, decision)
			const at = d.rules.length - 1
			this.openAt = at
			this.$emit('input', d)
			this.$nextTick(() => this.reveal(at))
		},
		// the reason under the buttons blinks (the same mark as a locked control elsewhere) and is brought into view if it is not
		attend() {
			this.nudge = false
			this.$nextTick(() => {
				this.nudge = true
				clearTimeout(this.nudgeTimer)
				this.nudgeTimer = setTimeout(() => { this.nudge = false }, FLASH_MS)
				const top = this.$refs.top
				const node = top && top.querySelector && top.querySelector('[data-part="add-reason"]')
				revealResult(node, { highlight: false })
			})
		},
		// the new rule: into view (only when less than 320 px of it is visible), marked for 1.8 s, the focus in its name and the sentence for the screen reader
		reveal(at) {
			const list = this.$refs.ruleEls
			const comp = Array.isArray(list) ? list[at] : list
			this.showResult(comp && comp.$refs && comp.$refs.box, { focus: '.access-rule-id-field input', said: this.$t('plugins.WorkshopService.access.builder_rule_added', { n: at + 1 }) })
		},
		remove(i) {
			this.openAt = 0
			this.$emit('input', removeRule(this.doc, i))
		}
	}
}
</script>

<style>
.access-rules-title { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; }
.access-rule-add { display: flex; flex-wrap: wrap; gap: 8px 12px; margin-bottom: 8px; }
.access-add--allow { color: var(--wf-c-success-text) !important; border-color: var(--wf-c-success) !important; }
.access-add--deny { color: var(--wf-c-error-text) !important; border-color: var(--wf-c-error) !important; }
.access-add.is-blocked { opacity: 0.55; cursor: not-allowed; }
.access-add-why { margin: 0 0 12px; padding: 6px 10px; border-left: 3px solid var(--wf-c-error); }
</style>
