<template>
	<!-- The SHORT help of the family (DESIGN.md 7b): one or two sentences shown in line, gray, under what they explain; no link, no fold. A longer explanation
	     is <help-fold> ("What it is and how to use it"). The text is already translated; the slot adds markup when a sentence needs a <code>.
	       <help-line :text="..." />      <help-line>Sentence with <code>x</code>.</help-line> -->
	<p class="wf-help wf-help-line"><template v-if="text">{{ text }}</template><slot /></p>
</template>

<script>
'use strict'

export default {
	props: {
		text: { type: String, default: '' }
	}
}
</script>
