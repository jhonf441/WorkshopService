<template>
	<!-- The one component that draws the state of a screen of the access section (loading, empty, error, no permission, damaged file, read only, users
	     off, stale, broken chain; access-state.js has the table). The screen only says which state; with no state the slot (the screen itself) is drawn.
	       <access-state :state="state" :detail="message" @retry="load()"><the screen /></access-state> -->
	<div class="access-state">
		<session-notice v-if="info" :kind="info.kind" :variant="info.variant" :title="title" :text="text" :act="info.retry ? 'retry' : ''" @retry="$emit('retry')" />
		<slot v-if="!info || info.variant !== 'cover'" />
	</div>
</template>

<script>
'use strict'

import SessionNotice from './SessionNotice.vue'
import { stateOf } from './access-state.js'

const AREA = 'plugins.WorkshopService.access.'

export default {
	components: { SessionNotice },
	props: {
		state: { type: String, default: '' },
		detail: { type: String, default: '' },
		params: { type: Object, default: () => ({}) }
	},
	computed: {
		info() {
			return stateOf(this.state)
		},
		title() {
			return this.info && this.info.title ? this.$t(AREA + this.info.title) : ''
		},
		text() {
			return this.info ? this.$t(AREA + this.info.text, Object.assign({ detail: this.detail }, this.params)) : ''
		}
	}
}
</script>
