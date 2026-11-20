<template>
	<!-- (legacy layer: the Access screens of the root use it) The "?" next to a technical word of Access: it opens the card "How access works" and marks that word. Prop: term (one of TERMS of access-how.js). -->
	<button type="button" class="sv-btn sv-text sv-term-help" :aria-label="t('access_help.term_ask', { name: t('access_help.term_' + term + '_name') })" @click="ask">
		<span class="mdi mdi-help-circle-outline sv-ico sv-ico-s" aria-hidden="true" />
	</button>
</template>

<script>
import { t } from './core/dwc.js'
import { showTerm } from './core/store/access-how.js'

export default {
	name: 'AccessTermHelp',
	props: { term: { type: String, required: true } },
	methods: {
		t,
		ask() { showTerm(this.term) }
	}
}
</script>
