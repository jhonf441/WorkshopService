<template>
	<!-- What happened to the write, next to its control: ONE line, a gray icon whose SHAPE says the state (hourglass, magnifier, check, cross, triangle) and
	     the WORD of the state ("Sending", "Checking", "Done", "Refused", "Not confirmed"), then the sentence in the normal color. The live region stays in the
	     page when empty so a screen reader hears what arrives (it is 0 px high then). Not confirmed offers Retry; a closed session offers Sign in when the page listens.
	     Two refusals that are not a failure of the write have their own face (no code, no ErrorNotice needed next to it):
	       cause 'refusal'  the session or the role does not allow it: lock icon, "Not allowed", the sentence of the permission (text / error.message), else "Requires the {role} role"
	                        (error.body.error.needed_role), else the default one. No Retry (it would be refused again). A closed session keeps its Sign in.
	       cause 'busy'     another write holds the machine (onBusy: 'refuse' of createAction): hourglass, "Busy right now", the reason; Retry stays. Read politely, not as an alert.
	     The cause comes from the error (causeOf of workshop-action.js: login_required / forbidden / busy) or from the prop when the page knows better.
	       action  the object of createAction (workshop-action.js), or  state + error + text  by hand
	       text    the sentence of a refusal when the page says it better than the service      retry   draw the Retry button (default true)      cause  '' | 'refusal' | 'busy' -->
	<div class="wf-result" :class="{ 'is-empty': !kind }" :data-outcome="kind || 'none'" :data-cause="why || null" :role="alertNow ? 'alert' : 'status'" :aria-live="alertNow ? 'assertive' : 'polite'">
		<template v-if="kind">
			<span class="mdi wf-result-ico" :class="icon" aria-hidden="true" />
			<span class="wf-result-word">{{ word }}</span>
			<span v-if="sentence" class="wf-result-text">{{ sentence }}<code v-if="code" class="wf-result-code">{{ code }}</code></span>
			<button v-if="showRetry" type="button" class="wf-btn" @click="$emit('retry')">{{ ts('wf_retry') }}</button>
			<button v-if="signIn" type="button" class="wf-btn wf-main" @click="$emit('sign-in')">{{ ts('wf_sign_in') }}</button>
		</template>
	</div>
</template>

<script>
import { ts } from './shared-t.js'
import { outcomeOf, causeOf } from './workshop-action.js'

const ICONS = { sending: 'mdi-timer-sand', verifying: 'mdi-magnify', done: 'mdi-check-circle-outline', refused: 'mdi-close-circle-outline', unverified: 'mdi-alert-outline' }
const CAUSE_ICONS = { refusal: 'mdi-lock-outline', busy: 'mdi-timer-sand' }

export default {
	name: 'WfResult',
	props: {
		action: { type: Object, default: null },
		state: { type: String, default: '' },
		error: { type: Object, default: null },
		text: { type: String, default: '' },
		retry: { type: Boolean, default: true },
		cause: { type: String, default: '', validator: v => v === '' || v === 'refusal' || v === 'busy' }
	},
	computed: {
		st() {
			return this.action ? this.action.state : this.state
		},
		err() {
			return this.action ? this.action.error : this.error
		},
		kind() {
			const k = outcomeOf(this.st, this.err)
			return k === 'none' ? '' : k
		},
		// why a refused write is not a plain failure: 'refusal' | 'busy' | ''
		why() {
			return this.kind === 'refused' ? this.cause || causeOf(this.err) : ''
		},
		alertNow() {
			return this.kind === 'refused' && this.why !== 'busy'
		},
		// a refusal because the session ended is not a failure of the write: it says so and offers the way in
		closed() {
			return this.kind === 'refused' && !!this.err && this.err.code === 'login_required'
		},
		signIn() {
			return this.closed && !!(this.$listeners && this.$listeners['sign-in'])
		},
		showRetry() {
			return this.retry && !this.closed && this.why !== 'refusal' && (this.kind === 'unverified' || this.kind === 'refused')
		},
		icon() {
			return (this.why && CAUSE_ICONS[this.why]) || ICONS[this.kind]
		},
		// every key is written out (a key built from the state cannot be found by the i18n tests of the plugins)
		word() {
			if (this.why === 'refusal') return ts('wf_state_refusal')
			if (this.why === 'busy') return ts('wf_busy')
			if (this.kind === 'sending') return ts('wf_state_sending')
			if (this.kind === 'verifying') return ts('wf_state_verifying')
			if (this.kind === 'done') return ts('wf_state_done')
			if (this.kind === 'refused') return ts('wf_state_refused')
			if (this.kind === 'unverified') return ts('wf_state_unverified')
			return ''
		},
		neededRole() {
			const body = this.err && this.err.body && this.err.body.error
			return (body && body.needed_role) || ''
		},
		sentence() {
			if (this.kind === 'unverified') return ts('wf_unverified_note')
			if (this.closed) return ts('wf_session_closed')
			if (this.why === 'refusal') return this.text || (this.err && this.err.message) || (this.neededRole ? ts('wf_needs_role', { role: this.neededRole }) : ts('wf_refusal_default'))
			if (this.why === 'busy') return this.text || (this.err && this.err.message) || ts('wf_busy_note')
			if (this.kind === 'refused') return this.text || (this.err && this.err.message) || ''
			if (this.kind === 'done') return (this.action && this.action.text) || this.text || ''
			return ''
		},
		code() {
			return this.kind === 'refused' && !this.why && this.err && this.err.code && this.err.code !== 'internal' ? String(this.err.code) : ''
		}
	},
	methods: { ts }
}
</script>
