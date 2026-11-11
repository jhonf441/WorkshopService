<template>
	<!-- The document of a profile as text, read only (step 1; editing comes with the editor). Copy puts it on the clipboard when the browser allows it. -->
	<div class="access-json">
		<div class="access-json-bar">
			<v-chip small outlined label>{{ $t('plugins.WorkshopService.access.common_read_only') }}</v-chip>
			<v-spacer />
			<v-btn small outlined class="access-touch" @click="copy"><v-icon left small>mdi-content-copy</v-icon>{{ copied ? $t('plugins.WorkshopService.access.common_copied') : $t('plugins.WorkshopService.access.common_copy') }}</v-btn>
		</div>
		<pre class="access-json-text" tabindex="0">{{ text }}</pre>
	</div>
</template>

<script>
'use strict'

import { jsonText } from './access-profile-view.js'

export default {
	props: { doc: { type: Object, default: null } },
	data() {
		return { copied: false }
	},
	computed: {
		text() {
			return jsonText(this.doc)
		}
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
.access-json-bar { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; }
.access-json-text { margin: 0; padding: 10px 12px; max-height: 480px; overflow: auto; border: 1px solid var(--wf-line); border-radius: 8px; font-family: monospace; font-size: 12px; line-height: 1.45; white-space: pre; }
</style>
