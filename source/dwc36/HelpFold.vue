<template>
	<!-- THE help of the family (DESIGN.md 7b, project decision 2026-11-21): ONE closed fold, "What it is and how to use it", a link with a "?" icon. It opens in place and
	     stays open (nothing lives only in a tooltip), Esc closes it and gives the focus back to its summary. The four rows (what / what for / without it / how), a list of
	     named blocks (`items`: what a section collects from its rows) or free content in the slot. A SHORT text (one or two sentences) is not folded: use <help-line>.
	       <help-fold :what="..." :why="..." :if-missing="..." :how="..." />      (texts already translated, from the plugin i18n)
	       <help-fold :items="[{ title, what, why, ifMissing, how }]" />         one block per thing of the section
	       <help-fold><ol>...</ol></help-fold>                                    free steps
	     The look is design/family.css (section FASE3); the same DOM as workshopHelpFoldEl (JS plugins). -->
	<details class="wf-help-fold" @keydown.esc.stop="close">
		<summary><v-icon :size="16" class="wf-help-fold-icon" aria-hidden="true">mdi-help-circle-outline</v-icon><span>{{ ts('help_fold_title') }}</span></summary>
		<div class="wf-help-fold-body">
			<div v-if="title" class="help-tip-title">{{ title }}</div>
			<dl v-if="rows.length" class="help-tip-list">
				<template v-for="r in rows"><dt :key="'t' + r.k">{{ r.label }}</dt><dd :key="'d' + r.k">{{ r.text }}</dd></template>
			</dl>
			<div v-for="(it, i) in blocks" :key="'i' + i" class="wf-help-fold-item">
				<div v-if="it.title" class="help-tip-title">{{ it.title }}</div>
				<dl class="help-tip-list">
					<template v-for="r in it.rows"><dt :key="'t' + r.k">{{ r.label }}</dt><dd :key="'d' + r.k">{{ r.text }}</dd></template>
				</dl>
			</div>
			<slot />
		</div>
	</details>
</template>

<script>
'use strict'

import { ts } from './shared-t.js'
import { helpRows } from './help-rows.js'

export default {
	props: {
		title: { type: String, default: '' }, // the name of the thing it explains (a heading inside the fold); the link always says the standard words
		what: { type: String, default: '' },
		why: { type: String, default: '' },
		ifMissing: { type: String, default: '' },
		how: { type: String, default: '' },
		items: { type: Array, default: () => [] } // [{ title, what, why, ifMissing, how }]: one block per thing
	},
	computed: {
		rows() {
			return helpRows(this, ts)
		},
		blocks() {
			return this.items.filter(Boolean).map(it => ({ title: it.title || '', rows: helpRows(it, ts) })).filter(b => b.rows.length)
		}
	},
	methods: {
		ts,
		// Escape closes it and the focus goes back to its one trigger (the summary): the same control opens and closes
		close() {
			if (!this.$el || !this.$el.open) return
			this.$el.open = false
			const s = this.$el.querySelector('summary')
			if (s && s.focus) s.focus()
		}
	}
}
</script>
