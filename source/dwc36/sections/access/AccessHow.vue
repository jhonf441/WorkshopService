<template>
	<!-- The card "How access works" at the top of Access: a diagram of who decides, in order (five nodes with their number INSIDE, joined by arrows), four short rules under it, a grid of
	     the eight words (touch one: its sentence and example open, one at a time) and a small example. Open the first time, it remembers when it was closed; a "?" anywhere opens it
	     on that word. -->
	<details class="sv-card sv-how" data-card="how" :open="isOpen" @toggle="onToggle">
		<summary class="sv-how-title"><span class="mdi mdi-information-outline sv-ico" aria-hidden="true" />{{ t('access_help.title') }}</summary>
		<p class="sv-quiet">{{ t('access_help.intro') }}</p>
		<ol class="sv-how-flow" :aria-label="t('access_help.scheme_label')" data-part="scheme">
			<li v-for="(s, i) in STEPS" :key="s" class="sv-how-node" :data-step="s">
				<span class="sv-how-n" aria-hidden="true">{{ i + 1 }}</span>
				<span class="mdi sv-ico" :class="STEP_ICONS[s]" aria-hidden="true" />
				<b>{{ t('access_help.step_' + s) }}</b>
				<span>{{ t('access_help.step_' + s + '_note') }}</span>
			</li>
		</ol>
		<ul class="sv-how-rules" data-part="rules">
			<li v-for="r in RULES" :key="r"><span class="mdi mdi-check-bold sv-ico sv-ico-s" aria-hidden="true" /><span>{{ t('access_help.rule_' + r) }}</span></li>
		</ul>
		<div class="sv-how-example" data-part="example">
			<p><span class="sv-chip-sm" data-kind="label">{{ t('access_help.ex_label') }}</span> <span class="sv-quiet">{{ t('access_help.ex_intro') }}</span></p>
			<ol class="sv-how-flow sv-how-ex" data-part="example-chips">
				<li v-for="s in STEPS" :key="s" :data-step="s"><span class="sv-chip-sm" :data-kind="s === 'ceiling' ? 'ceiling' : null">{{ t('access_help.ex_' + (s === 'profiles' ? 'profile' : s)) }}</span></li>
			</ol>
			<p data-part="example-result"><b>{{ t('access_help.step_result') }}:</b> {{ t('access_help.ex_result_full') }}</p>
		</div>
		<div class="sv-how-terms" role="group" :aria-label="t('access_help.terms_label')" data-part="terms">
			<button v-for="id in TERMS" :id="'sv-how-' + id" :key="id" type="button" class="wf-btn sv-btn sv-how-term" :aria-expanded="open === id ? 'true' : 'false'" :aria-controls="'sv-how-d-' + id" @click="open = open === id ? '' : id"><span class="mdi sv-ico" :class="TERM_ICONS[id]" aria-hidden="true" />{{ t('access_help.term_' + id + '_name') }}</button>
		</div>
		<div v-if="open" :id="'sv-how-d-' + open" class="sv-note" data-level="info" role="region" :aria-label="t('access_help.term_' + open + '_name')" data-part="detail"><div>
			<p>{{ t('access_help.term_' + open + '_def') }}</p>
			<p><i>{{ t('access_help.example') }} {{ t('access_help.term_' + open + '_example') }}</i></p>
		</div></div>
	</details>
</template>

<script>
import { t } from '../../core/dwc.js'
import { TERMS, STEPS, STEP_ICONS, TERM_ICONS, RULES, how } from '../../core/store/access-how.js'

const KEY = 'sv-access-how-closed'

function closedBefore() {
	try { return window.localStorage.getItem(KEY) === '1' } catch (e) { return false }
}

export default {
	name: 'AccessHow',
	data() {
		return { TERMS, STEPS, STEP_ICONS, TERM_ICONS, RULES, isOpen: !closedBefore(), open: '', how }
	},
	watch: {
		// a "?" asked: the card opens and the word opens with its sentence and example
		'how.n'() {
			if (!this.how.want) return
			this.isOpen = true
			this.open = this.how.term
			this.$nextTick(() => {
				const el = this.how.term && document.getElementById('sv-how-' + this.how.term)
				if (el && el.scrollIntoView) el.scrollIntoView({ block: 'center' })
			})
		}
	},
	methods: {
		t,
		onToggle(e) {
			this.isOpen = e.target.open
			try { window.localStorage.setItem(KEY, this.isOpen ? '0' : '1') } catch (err) { /* private window: the card just opens again next time */ }
		}
	}
}
</script>
