<template>
	<session-notice v-if="text" variant="section" :kind="noticeKind" :text="text" :action="showRetry ? 'retry' : ''" class="error-notice" @retry="$emit('retry')" />
</template>

<script>
'use strict'

// A failed call of the API as a person reads it: a note of the cause (ESTANDAR 2.2, N2). A missing session is a calm blue note with the
// standard reason and NO button (the page has its sign-in chip); a role refusal is the quiet role note; a real failure is the red one
// with "Retry". Nothing here retries by itself: a page that fails says so.
// The text and the kind come from friendly-error.js.
//
//   <error-notice :error="error" retry @retry="load()" />      error: ApiError | Error | string | null (null = nothing shown)

import SessionNotice from './SessionNotice.vue'
import { ts } from './shared-t.js'
import { errorKind, errorText } from './friendly-error.js'

export default {
	components: { SessionNotice },
	props: {
		error: { type: [Error, Object, String], default: null },
		retry: { type: Boolean, default: false }
	},
	computed: {
		kind() {
			return errorKind(this.error)
		},
		noticeKind() {
			if (this.kind === 'login') return 'session'
			if (this.kind === 'role') return 'role'
			return this.kind === 'unavailable' ? 'down' : 'error'
		},
		showRetry() {
			return this.retry && (this.noticeKind === 'error' || this.noticeKind === 'down')
		},
		text() {
			if (!this.error) return ''
			if (this.kind === 'login') return ts('notice_session_reason')
			if (typeof this.error === 'string') return this.error
			return errorText(this.error, ts)
		}
	}
}
</script>
