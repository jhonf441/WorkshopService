<template>
	<!-- The guide of a section is the family's ONE fold (since 2026-11-21): this is <help-fold> with the props this piece always had. The link says "What it is and how to use it";
	     a `title` that is not the old "How it works" becomes the heading inside the fold. New code uses <help-fold> directly.
	       <help-guide :what="..." :why="..." :if-missing="..." :how="..." />      <help-guide><ol>...</ol></help-guide> -->
	<help-fold :title="heading" :what="what" :why="why" :if-missing="ifMissing" :how="how"><slot /></help-fold>
</template>

<script>
'use strict'

import { ts } from './shared-t.js'
import HelpFold from './HelpFold.vue'

export default {
	components: { HelpFold },
	props: {
		title: { type: String, default: '' },
		what: { type: String, default: '' },
		why: { type: String, default: '' },
		ifMissing: { type: String, default: '' },
		how: { type: String, default: '' }
	},
	computed: {
		// the old standard title is the link now: only a title that names something else is kept
		heading() {
			return this.title && this.title !== ts('help_guide_title') ? this.title : ''
		}
	}
}
</script>
