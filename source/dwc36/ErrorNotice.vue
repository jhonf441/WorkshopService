<template>
	<session-notice v-if="shown" variant="section" :kind="noticeKind" :text="text" :needed="needed" :action="what" :act="showRetry ? 'retry' : ''" class="error-notice" @retry="$emit('retry')" />
</template>

<script>
'use strict'

// A failed call of the API as a person reads it: a thin wrapper of <session-notice variant="section"> (the one component). A missing session is a calm
// blue note with the standard reason and NO button (the page has its sign-in chip); a role refusal is the quiet role note that NAMES the action, the role it
// needs and the one the person has; a real failure is the red one with "Retry". Nothing here retries by itself: a page that fails says so.
// The sentence of a refusal is computed here from the error, never stored: it follows the role and the language. The kind comes from friendly-error.js.
//
//   <error-notice :error="error" action="Saving the zones" retry @retry="load()" />      error: ApiError | Error | string | null (null = nothing shown)
//   action: what the person was doing (translated); an error that carries its own `action` (print-errors.js fileError) wins.

import SessionNotice from './SessionNotice.vue'
import { ts } from './shared-t.js'
import { errorKind, errorText } from './friendly-error.js'

export default {
	components: { SessionNotice },
	props: {
		error: { type: [Error, Object, String], default: null },
		action: { type: String, default: '' },
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
		// a 403 of the mode or the camera is not about the role: it keeps its own sentence
		ownSentence() {
			const r = this.error && this.error.reason
			return this.kind === 'role' && !!r && r !== 'role'
		},
		needed() {
			const body = this.error && this.error.body && this.error.body.error
			return (body && body.needed_role) || 'technician'
		},
		what() {
			return (this.error && this.error.action) || this.action
		},
		showRetry() {
			return this.retry && (this.noticeKind === 'error' || this.noticeKind === 'down')
		},
		shown() {
			return !!this.error && (this.kind === 'login' || this.kind === 'role' || !!this.text)
		},
		text() {
			if (!this.error) return ''
			// a missing session or a role refusal has no stored text: <session-notice> says it by the state of the moment (no session, ended, PIN locked, role)
			if (this.kind === 'login' || (this.kind === 'role' && !this.ownSentence)) return ''
			if (typeof this.error === 'string') return this.error
			return errorText(this.error, ts)
		}
	}
}
</script>
