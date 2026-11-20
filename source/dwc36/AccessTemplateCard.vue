<template>
	<!-- One ready-made template: name, the quiet chip "Proposal", what it is for, which areas it reaches, what it does NOT allow, the fixed line about stopping, the unfold
	     "See exactly what it allows" (area by area, names of the capabilities as the service gave them, never an id) and two actions. The card changes nothing: the buttons
	     only ask the tab (events `copy` and `give`). `locked-copy` / `locked-give` switch the buttons off; the ONE reason is drawn by the section, not here.
	       <access-template-card :template="t" :titles="{ id: title }" :locked-copy="false" :locked-give="false" @copy="..." @give="..." /> -->
	<v-card class="access-template-card sv-card-fill" outlined>
		<v-card-title class="text-subtitle-1 access-template-head">
			<span>{{ $t(key('name')) }}</span>
			<v-spacer />
			<v-chip small outlined label class="access-template-chip"><v-icon left small aria-hidden="true">mdi-clipboard-text-outline</v-icon>{{ $t('plugins.WorkshopService.access.templates_proposal') }}</v-chip>
		</v-card-title>
		<v-card-text>
			<div class="mb-2">{{ $t(key('use')) }}</div>
			<div class="wf-help mb-1"><span class="access-rule-label">{{ $t('plugins.WorkshopService.access.templates_use_label') }}</span> {{ $t('plugins.WorkshopService.access.templates_use_' + template.use) }}</div>
			<div class="wf-help mb-1"><span class="access-rule-label">{{ $t('plugins.WorkshopService.access.templates_can_label') }}</span> {{ reached }}</div>
			<div class="wf-help mb-1"><span class="access-rule-label">{{ $t('plugins.WorkshopService.access.templates_not_label') }}</span> {{ $t(key('not')) }}</div>
			<div class="wf-help mb-2"><v-icon small class="mr-1" aria-hidden="true">mdi-hand-back-left-outline</v-icon>{{ $t('plugins.WorkshopService.access.templates_fixed_stop') }}</div>
			<v-btn small text class="access-touch" :aria-expanded="open ? 'true' : 'false'" @click="open = !open"><v-icon left small>{{ open ? 'mdi-chevron-up' : 'mdi-chevron-down' }}</v-icon>{{ $t('plugins.WorkshopService.access.templates_' + (open ? 'hide' : 'show')) }}</v-btn>
			<div v-if="open" class="access-template-detail">
				<div v-if="!lines.length" class="wf-help">{{ $t('plugins.WorkshopService.access.templates_titles_missing') }}</div>
				<div v-for="l in lines" :key="l.area" class="mb-2">
					<div class="font-weight-medium"><v-icon small class="mr-1" aria-hidden="true">{{ l.icon }}</v-icon>{{ $t('plugins.WorkshopService.access.area_' + l.area) }}</div>
					<ul class="access-template-caps">
						<li v-for="i in l.items" :key="i.key">{{ i.title }}<span v-if="i.note" class="wf-help"> ({{ $t('plugins.WorkshopService.access.templates_note_' + i.note) }})</span></li>
					</ul>
				</div>
				<div v-if="lines.length && lines.missing" class="wf-help">{{ $t('plugins.WorkshopService.access.templates_titles_missing') }}</div>
			</div>
		</v-card-text>
		<v-card-actions class="access-template-actions sv-card-actions">
			<v-btn small outlined class="access-touch" :disabled="lockedCopy" @click="$emit('copy', template)"><v-icon left small>mdi-content-copy</v-icon>{{ $t('plugins.WorkshopService.access.templates_copy') }}</v-btn>
			<v-btn small color="primary" class="access-touch" :disabled="lockedGive" @click="$emit('give', template)"><v-icon left small>mdi-account-plus-outline</v-icon>{{ $t('plugins.WorkshopService.access.templates_give') }}</v-btn>
		</v-card-actions>
	</v-card>
</template>

<script>
'use strict'

import { areaLines, summaryAreas } from './access-template-view.js'

export default {
	name: 'AccessTemplateCard',
	props: {
		template: { type: Object, required: true },
		titles: { type: Object, default: () => ({}) },
		lockedCopy: { type: Boolean, default: false },
		lockedGive: { type: Boolean, default: false }
	},
	data() {
		return { open: false }
	},
	computed: {
		lines() {
			return areaLines(this.template, this.titles)
		},
		reached() {
			return summaryAreas(this.template).map(a => this.$t('plugins.WorkshopService.access.area_short_' + a)).join(', ')
		}
	},
	methods: {
		key(part) {
			return 'plugins.WorkshopService.access.templates_' + this.template.id + '_' + part
		}
	}
}
</script>

<style>
.access-template-head { flex-wrap: wrap; gap: 4px 8px; }
.access-template-caps { margin: 2px 0 0; padding-left: 20px; }
</style>
