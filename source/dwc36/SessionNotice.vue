<template>
	<!-- A notice by cause (ESTANDAR 2.2): N2 a note on top of a section (variant="section") or N4 a cover that replaces the content of a zone
	     (variant="cover"). The look is design/family.css (.wf-notice / .wf-cover + the cause); nothing here is styled.
	     <session-notice kind="session" variant="cover" />        cover with the "Sign in" button
	     <session-notice kind="role" needed="technician" />       note: "Requires the Technician role. Your role: Operator."
	     <session-notice kind="down" variant="cover" @retry="load()" /> -->
	<div v-if="shown" :class="[variant === 'cover' ? 'wf-cover' : 'wf-notice', (variant === 'cover' ? 'wf-cover--' : 'wf-notice--') + cssKind]" :role="variant === 'cover' ? 'status' : 'note'">
		<v-icon :size="variant === 'cover' ? 32 : 16" :class="variant === 'cover' ? 'wf-cover-icon' : 'wf-notice-icon'" aria-hidden="true">{{ icon }}</v-icon>
		<template v-if="variant === 'cover'">
			<div v-if="heading" class="wf-cover-title">{{ heading }}</div>
			<div v-if="message" class="wf-cover-text">{{ message }}</div>
			<button v-if="act" type="button" class="wf-btn wf-main" @click="run">{{ actLabel }}</button>
		</template>
		<template v-else>
			<div class="wf-notice-body"><div class="wf-notice-text">{{ message }}</div></div>
			<button v-if="act" type="button" class="wf-btn wf-notice-action" @click="run">{{ actLabel }}</button>
		</template>
	</div>
</template>

<script>
'use strict'

import { ts } from './shared-t.js'
import { roleMixin } from './role-mixin.js'
import { askLogin } from './workshop-api.js'
import { workshopRole } from './workshop-auth.js'
import { NOTICE_ICONS, noticeText } from './notice-kind.js'

// Props: kind 'session' | 'role' | 'down' | 'error' | 'empty' ('' draws nothing); variant 'section' | 'cover'; text (else the standard sentence of
// the cause); title (cover); needed (a role id: for kind 'role'); action 'sign-in' | 'retry' | '' (default: cover+session => sign-in,
// cover+down => retry, section => none: the page already has its sign-in chip). Emits `retry`.
export default {
	mixins: [roleMixin],
	props: {
		kind: { type: String, default: '' },
		variant: { type: String, default: 'section' },
		text: { type: String, default: '' },
		title: { type: String, default: '' },
		needed: { type: String, default: 'technician' },
		action: { type: String, default: null }
	},
	computed: {
		shown() {
			return !!this.kind
		},
		// a note of the kind "empty" has no cause color: it is drawn as the quiet one
		cssKind() {
			return this.kind === 'empty' && this.variant !== 'cover' ? 'role' : this.kind
		},
		icon() {
			return NOTICE_ICONS[this.kind] || NOTICE_ICONS.error
		},
		heading() {
			if (this.title) return this.title
			if (this.kind === 'session') return ts('notice_session_cover_title')
			if (this.kind === 'role') return ts('notice_role_cover_title')
			if (this.kind === 'down') return ts('notice_down_cover_title')
			if (this.kind === 'error') return ts('notice_error_cover_title')
			return ''
		},
		message() {
			void this.identityTick
			if (this.text) return this.text
			if (this.kind === 'session' && this.variant === 'cover') return ts('notice_session_cover')
			return noticeText(this.kind, { needed: this.needed, role: workshopRole() }, ts)
		},
		act() {
			if (this.action !== null) return this.action
			if (this.variant !== 'cover') return ''
			return this.kind === 'session' ? 'sign-in' : this.kind === 'down' ? 'retry' : ''
		},
		actLabel() {
			return this.act === 'retry' ? ts('notice_retry') : ts('notice_sign_in')
		}
	},
	methods: {
		async run() {
			if (this.act === 'retry') return this.$emit('retry')
			if (await askLogin()) this.$emit('retry')
		}
	}
}
</script>
