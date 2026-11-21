<template>
	<!-- The mark "Unsaved changes" next to the title of an editor (words and an icon, never colour alone). Prop: show. Mounted by every editor that uses unsaved-mixin.js. -->
	<span v-if="show" class="sv-unsaved" role="status" data-part="unsaved-mark"><span class="mdi mdi-circle-edit-outline sv-ico sv-ico-s" aria-hidden="true" />{{ kt('unsaved_mark') }}</span>
</template>

<script>
import { svTextMixin } from './sv-text.js'

export default {
	name: 'SvUnsavedMark',
	mixins: [svTextMixin],
	props: { show: { type: Boolean, default: false } }
}
</script>
