<template>
	<!-- One capability of an area: its title (the service's, translated), its state, the reason in a sentence and what to do. The button only asks the tab to
	     open the profile or the person (event `go`); nothing is changed here.
	       <access-can-line :line="line" :role="'operator'" @go="..." /> -->
	<li class="can-line" :class="'is-' + line.state">
		<div class="can-line-head">
			<span class="can-line-title">{{ line.title }}</span>
			<access-can-state :state="line.state" />
		</div>
		<div v-if="line.sentence" class="can-line-reason">{{ sentenceText(line.sentence, role) }}</div>
		<div v-else-if="line.error" class="can-line-reason">{{ line.error }}</div>
		<div v-if="line.hint" class="wf-help can-line-todo">{{ $t('plugins.WorkshopService.access.' + line.hint) }}</div>
		<v-btn v-if="line.go" small outlined class="access-touch mt-1" @click="$emit('go', line.go)">{{ $t('plugins.WorkshopService.access.who_go_' + (line.go.tab === 'profiles' ? 'profile' : 'person')) }}</v-btn>
	</li>
</template>

<script>
'use strict'

import AccessCanState from './AccessCanState.vue'
import { accessSentenceMixin } from './access-sentence-mixin.js'

export default {
	name: 'AccessCanLine',
	components: { AccessCanState },
	mixins: [accessSentenceMixin],
	props: { line: { type: Object, required: true }, role: { type: String, default: '' } }
}
</script>

<style>
.can-line { list-style: none; padding: 8px 0; border-bottom: 1px solid var(--wf-line); }
.can-line-head { display: flex; align-items: center; flex-wrap: wrap; gap: 4px 12px; justify-content: space-between; }
.can-line-title { font-weight: 500; overflow-wrap: anywhere; }
.can-line-reason { margin-top: 4px; font-size: 13px; }
.can-line-todo { margin-top: 2px; }
</style>
