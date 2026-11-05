<template>
	<v-menu :close-on-content-click="false" offset-y left max-width="380" content-class="workshop-theme help-tip-menu">
		<template v-slot:activator="{ on, attrs }">
			<v-btn icon class="help-tip" :aria-label="label" :title="label" v-bind="attrs" v-on="on">
				<v-icon :size="18">mdi-help-circle-outline</v-icon>
			</v-btn>
		</template>
		<v-card class="help-tip-card">
			<v-card-text>
				<div v-if="title" class="help-tip-title">{{ title }}</div>
				<dl v-if="rows.length" class="help-tip-list">
					<template v-for="r in rows"><dt :key="'t' + r.k">{{ r.label }}</dt><dd :key="'d' + r.k">{{ r.text }}</dd></template>
				</dl>
				<slot />
			</v-card-text>
		</v-card>
	</v-menu>
</template>

<script>
'use strict'

// THE "?" of the family (DESIGN.md section 7b; its look, shared with the JS twin, is design/family.css): a small button next to a field, a title or a card that opens a card with the help of THAT thing, in
// the four lines of the start-up cards: what it is, what it is for, what you lose without it, how to use it. Every plugin uses this one piece, so the
// button looks the same, sits at the end of the row and says the same four things everywhere. Empty lines are not drawn. For a longer text of the whole
// page use the "How it works" fold (wf-more) once, never one fold under every input.
//
//   <help-tip :title="'Cost per kWh'" :what="..." :why="..." :if-missing="..." :how="..." />      (texts already translated, from the plugin i18n)
//   <help-tip title="...">free content in the slot</help-tip>
import { ts } from './shared-t.js'

export default {
	props: {
		title: { type: String, default: '' }, // the name of the thing it explains: it is also the accessible name of the button
		what: { type: String, default: '' },
		why: { type: String, default: '' },
		ifMissing: { type: String, default: '' },
		how: { type: String, default: '' }
	},
	computed: {
		label() {
			return ts('help_tip_open') + (this.title ? ': ' + this.title : '')
		},
		rows() {
			return [
				{ k: 'what', label: ts('help_tip_what'), text: this.what },
				{ k: 'why', label: ts('help_tip_why'), text: this.why },
				{ k: 'miss', label: ts('help_tip_missing'), text: this.ifMissing },
				{ k: 'how', label: ts('help_tip_how'), text: this.how }
			].filter(r => r.text)
		}
	}
}
</script>
