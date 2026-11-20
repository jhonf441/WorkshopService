<template>
	<!-- The document of a profile as text. It is editable on every screen (Format, Validate, Copy); it is read only only when the profile cannot be saved
	     (damaged file or no permission). What is typed here is kept when the person goes to the Builder and back. The service's own sentences judge the document.
	       <access-json-editor :text="..." :readonly="false" :line="0" @input="t => ..." @format @validate /> -->
	<div class="access-json">
		<div class="access-json-bar">
			<v-chip v-if="readonly" small outlined label>{{ $t('plugins.WorkshopService.access.common_read_only') }}</v-chip>
			<v-spacer />
			<v-btn v-if="!readonly" small outlined class="access-touch" @click="$emit('format')">{{ $t('plugins.WorkshopService.access.json_format') }}</v-btn>
			<v-btn v-if="!readonly" small outlined class="access-touch" @click="$emit('validate')">{{ $t('plugins.WorkshopService.access.json_validate') }}</v-btn>
			<v-btn small outlined class="access-touch" @click="copy"><v-icon left small>mdi-content-copy</v-icon>{{ copied ? $t('plugins.WorkshopService.access.common_copied') : $t('plugins.WorkshopService.access.common_copy') }}</v-btn>
		</div>
		<div v-if="line" class="access-problem" role="alert">{{ $t('plugins.WorkshopService.access.json_error_line', { line }) }}</div>
		<textarea class="access-json-text access-json-input" spellcheck="false" :readonly="readonly" :value="text" :aria-label="$t('plugins.WorkshopService.access.builder_mode_json')" @input="e => $emit('input', e.target.value)" />
	</div>
</template>

<script>
'use strict'

export default {
	props: {
		text: { type: String, default: '' },
		readonly: { type: Boolean, default: false },
		line: { type: Number, default: 0 }
	},
	data() {
		return { copied: false }
	},
	methods: {
		copy() {
			try {
				const c = typeof navigator !== 'undefined' && navigator.clipboard
				if (c) c.writeText(this.text).then(() => { this.copied = true }, () => {})
			} catch (e) { /* no clipboard: the text can still be selected */ }
		}
	}
}
</script>

<style>
.access-json-input { width: 100%; min-height: 320px; resize: vertical; background: transparent; color: inherit; white-space: pre; }
</style>
