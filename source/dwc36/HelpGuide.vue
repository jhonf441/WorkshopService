<template>
	<!-- H3, the guide of a section ("How it works", AYUDAS.md P3): ONE closed fold per section with the four fixed rows (what / what for / without it /
	     how), or free steps in the slot (an <ol>). The look is design/family.css (.wf-guide, .help-tip-list); the same DOM as workshopGuideEl (JS).
	       <help-guide :what="..." :why="..." :if-missing="..." :how="..." />      <help-guide title="..."><ol>...</ol></help-guide> -->
	<details class="wf-guide">
		<summary>{{ heading }}</summary>
		<dl v-if="rows.length" class="help-tip-list">
			<template v-for="r in rows"><dt :key="'t' + r.k">{{ r.label }}</dt><dd :key="'d' + r.k">{{ r.text }}</dd></template>
		</dl>
		<slot />
	</details>
</template>

<script>
'use strict'

import { ts } from './shared-t.js'

export default {
	props: {
		title: { type: String, default: '' },
		what: { type: String, default: '' },
		why: { type: String, default: '' },
		ifMissing: { type: String, default: '' },
		how: { type: String, default: '' }
	},
	computed: {
		heading() {
			return this.title || ts('help_guide_title')
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
