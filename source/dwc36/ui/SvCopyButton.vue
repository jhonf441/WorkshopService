<template>
	<!-- THE copy button of the page: the same icon and the same word everywhere ("Copy"; "Copied" for a moment after). It keeps its size when the word
	     changes. Props: kind (what is copied, a short id for the page: it goes to data-copy), label (what is copied, for the screen reader: "Copy: the request"),
	     done (it was copied a moment ago). Event: copy. -->
	<button type="button" class="sv-btn sv-text sv-copy" :data-copy="kind || null" :aria-label="kt('copy') + (label ? ': ' + label : '')" @click="$emit('copy')">
		<span class="mdi sv-ico sv-ico-s" :class="done ? 'mdi-check' : 'mdi-content-copy'" aria-hidden="true" />
		<span class="sv-btn-stack" :data-alt="done ? kt('copy') : kt('copied')">{{ done ? kt('copied') : kt('copy') }}</span>
	</button>
</template>

<script>
import { svTextMixin } from './sv-text.js'

export default {
	name: 'SvCopyButton',
	mixins: [svTextMixin],
	props: {
		kind: { type: String, default: '' },
		label: { type: String, default: '' },
		done: { type: Boolean, default: false }
	}
}
</script>
