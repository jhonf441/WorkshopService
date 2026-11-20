<template>
	<!-- The key shown ONCE after it is created (ApiKeys owns it and forgets it in every change of person). Props: value (open), keyNew, exampleCurl, copied.
	     Emits input, copy (text, id, event) and done ("I copied it"). -->
	<v-dialog :value="value" @input="v => $emit('input', v)" max-width="640" width="100%" persistent content-class="ws-keys-dialog">
		<v-card>
			<v-card-title class="text-subtitle-1">{{ $t('plugins.WorkshopService.keys.your_key') }}</v-card-title>
			<v-card-text>
				<v-alert dense text type="warning">{{ $t('plugins.WorkshopService.keys.shown_once') }}</v-alert>
				<div class="d-flex align-center">
					<code class="d-block pa-2 flex-grow-1" style="word-break:break-all">{{ keyNew }}</code>
					<v-btn icon small class="ml-1" @click="$emit('copy', keyNew, 'key', $event)"><v-icon small>{{ copied === 'key' ? 'mdi-check' : 'mdi-content-copy' }}</v-icon></v-btn>
				</div>
				<div class="text-caption grey--text mt-3 mb-1">{{ $t('plugins.WorkshopService.keys.example') }}</div>
				<div class="d-flex align-start">
					<code class="d-block pa-2 flex-grow-1" style="white-space:pre-wrap;word-break:break-all">{{ exampleCurl }}</code>
					<v-btn icon small class="ml-1" @click="$emit('copy', exampleCurl, 'curl', $event)"><v-icon small>{{ copied === 'curl' ? 'mdi-check' : 'mdi-content-copy' }}</v-icon></v-btn>
				</div>
			</v-card-text>
			<v-card-actions>
				<v-spacer />
				<v-btn color="primary" @click="$emit('done')">{{ $t('plugins.WorkshopService.keys.i_copied_it') }}</v-btn>
			</v-card-actions>
		</v-card>
	</v-dialog>
</template>

<script>
'use strict'

export default {
	name: 'ApiKeyShown',
	props: {
		value: { type: Boolean, default: false },
		keyNew: { type: String, default: '' },
		exampleCurl: { type: String, default: '' },
		copied: { type: String, default: '' }
	}
}
</script>
