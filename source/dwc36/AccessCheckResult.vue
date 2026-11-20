<template>
	<!-- The answer of "What this person can do" (access.check), already arranged by access-people-view.js checkOutcome: allowed or denied, the sentence of its
	     cause (it says what to do), who decided, and the other rules with why they did not match.
	       <access-check-result :outcome="checkOutcome(answer)" :role="'operator'" /> -->
	<div class="access-check-result" role="status">
		<div class="access-result-head">
			<span class="access-rule-label">{{ $t('plugins.WorkshopService.access.check_result') }}</span>
			<v-chip small label :color="chipColor">{{ $t('plugins.WorkshopService.access.check_' + (outcome.allowed ? 'allowed' : 'denied')) }}</v-chip>
			<strong class="access-result-op">{{ outcome.operation }}</strong>
			<span class="wf-help">{{ outcome.target }}</span>
		</div>
		<div v-if="outcome.sentence.key" class="access-result-reason">{{ sentenceText(outcome.sentence, role) }}</div>
		<div v-if="outcome.sentence.extra" class="wf-help">{{ $t(area + outcome.sentence.extra) }}</div>
		<div v-if="outcome.deciding" class="access-result-decided"><access-term-help term="rule" />
			{{ $t('plugins.WorkshopService.access.check_decided_by', { profile: profileText(outcome.deciding.profile), rule: ruleText(outcome.deciding.rule, outcome.deciding.profile) }) }}
			<v-chip x-small outlined label>{{ $t(area + outcome.deciding.source) }}</v-chip>
			<code v-if="profileCode(outcome.deciding.profile)" class="access-id">{{ outcome.deciding.profile }} / {{ outcome.deciding.rule }}</code>
		</div>
		<div v-if="outcome.conditionNote" class="wf-help">{{ $t('plugins.WorkshopService.access.builder_when_unknown') }}</div>
		<div v-if="outcome.others.length" class="access-others">
			<div class="access-rule-label">{{ $t('plugins.WorkshopService.access.check_others') }}</div>
			<ul class="access-others-list">
				<li v-for="(o, i) in shownOthers" :key="i" class="access-other">
					<strong><profile-name :id="o.profile" /></strong> / {{ ruleText(o.rule, o.profile) }}
					<span class="wf-help">({{ $t('plugins.WorkshopService.access.check_rule_' + (o.deny ? 'deny' : 'allow')) }}, {{ $t(area + o.source) }})</span>
					<span v-if="o.matched">{{ $t('plugins.WorkshopService.access.check_matched') }}</span>
					<span v-else>{{ $t('plugins.WorkshopService.access.reason_not_matched', { why: whyText(o) }) }}</span>
				</li>
			</ul>
			<v-btn v-if="limit < outcome.others.length" small outlined class="access-touch" @click="all = !all">{{ all ? $t('plugins.WorkshopService.access.check_others_hide') : $tc('plugins.WorkshopService.access.check_others_show', outcome.others.length, { n: outcome.others.length }) }}</v-btn>
		</div>
	</div>
</template>

<script>
'use strict'

import { OTHERS_COLLAPSED } from './access-people-view.js'
import ProfileName from './ProfileName.vue'
import AccessTermHelp from './AccessTermHelp.vue'
import { accessSentenceMixin } from './access-sentence-mixin.js'

const AREA = 'plugins.WorkshopService.access.'

export default {
	components: { AccessTermHelp, ProfileName },
	mixins: [accessSentenceMixin],
	props: {
		outcome: { type: Object, required: true },
		role: { type: String, default: '' }
	},
	data() {
		return { all: false, area: AREA, limit: OTHERS_COLLAPSED }
	},
	computed: {
		// allowed: success; refused with no rule at all: neutral (nobody denied it); any other refusal: error
		chipColor() {
			if (this.outcome.allowed) return 'success'
			return this.outcome.sentence.cause === 'no_rule' ? '' : 'error'
		},
		shownOthers() {
			return this.all ? this.outcome.others : this.outcome.others.slice(0, this.limit)
		}
	},
	methods: {
		whyText(o) {
			return o.why.map(k => this.$t(AREA + k)).join(', ')
		}
	}
}
</script>

<style>
.access-check-result { margin-top: 12px; padding: 10px 12px; border: 1px solid var(--wf-line); border-radius: 8px; }
.access-result-head { display: flex; align-items: center; flex-wrap: wrap; gap: 4px 10px; margin-bottom: 6px; }
.access-others-list { list-style: none; margin: 4px 0 8px; padding: 0; font-size: 13px; }
.access-other { padding: 3px 0; }
</style>
