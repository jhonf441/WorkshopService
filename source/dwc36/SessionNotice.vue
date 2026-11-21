<template>
	<!-- The ONE notice component of the session (ESTANDAR 2.2). The cause (session / role / down / error / resolving) and its sentence are decided here;
	     the variant only says where it is drawn. The look is design/family.css (.wf-notice / .wf-cover / .wf-reason / .wf-session-chip); nothing here is styled.
	       variant="chip"     the chip of the bar: "Sign in" when nobody is signed in, "Read only · Change role" for a visitor (nothing otherwise)
	     act="sign-in"      the way out of the lock on a surface without the bar chip: "Sign in" for a session cause, "Change role" for a role cause
	                        (the same name + PIN dialog, askLogin(): the current session stays until the new one is accepted; DESIGN.md 7c)
	       variant="section"  N2, a note on top of a section (default)
	       variant="reason"   N3, one line next to a disabled control (min / op decide the cause, or kind)
	       variant="cover"    N4, replaces the content of a zone, with the "Sign in" button
	     <session-notice kind="role" needed="technician" action="Saving the zones" />   "Saving the zones requires the role Technician. Your role: Operator. ..."
	     <session-notice variant="reason" min="technician" />
	     <session-notice variant="cover" kind="down" @retry="load()" />
	     There is no toast variant: a toast is the control bar's (it says the same sentence by the same function). -->
	<button v-if="variant === 'chip' && chip === 'session'" type="button" class="wf-session-chip" :aria-label="ts('notice_bar_chip_help')" :title="ts('notice_bar_chip_help')" @click="run">
		<v-icon :size="16" class="wf-session-chip-icon">mdi-account-lock-outline</v-icon><span>{{ ts('notice_bar_chip') }}</span>
	</button>
	<!-- a visitor is signed in with a role that only looks: the chip offers the way out (another person signs in; this session stays until then) -->
	<button v-else-if="variant === 'chip' && chip === 'viewer'" type="button" class="wf-session-chip is-role" :aria-label="ts('header_read_only_help')" :title="ts('header_read_only_help')" @click="run">
		<v-icon :size="16" class="wf-session-chip-icon">mdi-eye-outline</v-icon><span>{{ ts('header_read_only') }} · {{ ts('notice_change_role') }}</span>
	</button>
	<div v-else-if="variant === 'reason' && shown" class="wf-reason" :class="'wf-reason--' + cssKind" :data-cause="verdictCause" role="note">
		<v-icon :size="16" class="wf-reason-icon" aria-hidden="true">{{ icon }}</v-icon>
		<span class="wf-reason-text">{{ message }}</span>
	</div>
	<div v-else-if="(variant === 'cover' || variant === 'section') && shown" :class="[variant === 'cover' ? 'wf-cover' : 'wf-notice', (variant === 'cover' ? 'wf-cover--' : 'wf-notice--') + cssKind]" :role="variant === 'cover' ? 'status' : 'note'">
		<v-icon :size="variant === 'cover' ? 32 : 16" :class="variant === 'cover' ? 'wf-cover-icon' : 'wf-notice-icon'" aria-hidden="true">{{ icon }}</v-icon>
		<template v-if="variant === 'cover'">
			<div v-if="heading" class="wf-cover-title">{{ heading }}</div>
			<div v-if="message" class="wf-cover-text">{{ message }}</div>
			<!-- the button follows `step` (the decided action), not the raw prop: a down cover retries by default and a session cover offers "Sign in"
				     when the page gives act="sign-in" (a surface without the bar chip, e.g. a card of the Service page) -->
				<button v-if="step" type="button" class="wf-btn wf-main" @click="run"><v-icon :size="16" class="wf-btn-icon">{{ actIcon }}</v-icon>{{ actLabel }}</button>
		</template>
		<template v-else>
			<div class="wf-notice-body"><div class="wf-notice-text">{{ message }}</div></div>
			<button v-if="step" type="button" class="wf-btn wf-notice-action" @click="run"><v-icon :size="16" class="wf-btn-icon">{{ actIcon }}</v-icon>{{ actLabel }}</button>
		</template>
	</div>
</template>

<script>
'use strict'

import { ts } from './shared-t.js'
import { accessCanMixin, canStore } from './reason-mixin.js'
import { askLogin } from './workshop-api.js'
import { sessionState, signedOut, workshopRole, workshopRoleName } from './workshop-auth.js'
import { CAUSE_LOOK, groupFromAnswers } from './access-reason.js'
import { NOTICE_ICONS, noticeText, noticeActionOf } from './notice-kind.js'
import { lockKind, lockKindOp, lockReason, lockReasonOp } from './lock-reason.js'

// Props: kind 'session' | 'role' | 'down' | 'error' | 'empty' | 'resolving' ('' draws nothing; for variant "reason" it may come from min / op instead);
// variant 'chip' | 'section' | 'reason' | 'cover'; text (else the standard sentence of the cause); title (cover); needed (a role id: for kind 'role');
// action: what was refused, translated ("Saving the zones"): the sentence of a role refusal names it; act 'sign-in' | 'retry' | '' (default: cover+session =>
// sign-in, cover+down => retry, section => none: the page already has its sign-in chip; 'sign-in' on a role cause is drawn as "Change role", the same
// dialog); min / op / need / ctx: the cause of a locked control (variant "reason"). Emits `retry`.
export default {
	mixins: [accessCanMixin],
	props: {
		kind: { type: String, default: '' },
		variant: { type: String, default: 'section' },
		text: { type: String, default: '' },
		title: { type: String, default: '' },
		needed: { type: String, default: 'technician' },
		action: { type: String, default: '' },
		act: { type: String, default: null },
		min: { type: String, default: '' },
		op: { type: String, default: '' },
		need: { type: String, default: '' },
		ctx: { type: Object, default: null },
		target: { type: String, default: '' }, // workshop:<plugin>:<type>/<id> of the thing the control acts on (op only)
		ops: { type: Array, default: () => [] }, // a GROUP of operations: ONE sentence, the one of the first that is denied
		live: { type: Object, default: null }, // { job_running, machine_on }: the live value names the condition that failed exactly
		subject: { type: String, default: '' } // WHAT is locked ("Phone alerts"): a reason sits under a group of controls, so its sentence starts with the name of that group
	},
	created() {
		this.askCan()
	},
	watch: {
		op() { this.askCan() },
		target() { this.askCan() },
		ops() { this.askCan() }
	},
	computed: {
		// the cause: given, or (a locked control) the one of its role / operation
		// what is asked of the service for this reason: the operations of the group, or the one operation with its target
		askItems() {
			if (this.kind || this.variant !== 'reason') return []
			if (this.ops.length) return this.ops.map(o => (typeof o === 'string' ? { operation: o } : o))
			return this.op ? [this.target ? { operation: this.op, target: this.target } : { operation: this.op }] : []
		},
		// the answer of the service (auth.can) for them: { show, key, cause, params, nested, unknown, answered } or null when there is nothing to ask
		verdict() {
			void this.identityTick
			void this.canTick
			const items = this.askItems
			if (!items.length) return null
			const targets = {}
			items.forEach(i => { targets[i.operation] = i.target })
			const store = canStore()
			return groupFromAnswers(items.map(i => i.operation), op => store.get(op, targets[op]), { roleName: workshopRoleName(), live: this.live || undefined })
		},
		// the cause the service answered when it says no ('' = it says yes, or nothing is known yet and the table of the role decides)
		verdictCause() {
			return this.verdict && this.verdict.show ? this.verdict.cause : ''
		},
		k() {
			void this.identityTick
			if (this.kind) return this.kind
			const v = this.verdict
			if (v && v.show) return v.cause
			if (v && v.answered) return ''
			if (this.op) return lockKindOp(this.op, this.need, this.ctx || undefined)
			return this.min ? lockKind(this.min) : ''
		},
		// ONE session notice per page (2026-11-20): the chip of the header already says "Sign in" and blinks on a refusal, so a section note of the
		// session cause that names no resource (no subject) and has no button of its own (act) would only repeat it: it draws nothing. A note that names
		// what is locked (subject) or a surface without the chip (act="sign-in") still draws.
		redundantBand() {
			return this.variant === 'section' && this.k === 'session' && !this.subject && !this.act
		},
		shown() {
			return !!this.k && !this.redundantBand
		},
		// the chip of the bar: 'session' (nobody signed in, a button), 'viewer' (read only) or '' (nothing)
		chip() {
			void this.identityTick
			if (signedOut()) return 'session'
			return workshopRole() === 'viewer' ? 'viewer' : ''
		},
		// a note of the kind "empty" has no cause color: it is drawn as the quiet one
		cssKind() {
			if (CAUSE_LOOK[this.k]) return CAUSE_LOOK[this.k].css
			return this.k === 'empty' && this.variant !== 'cover' ? 'role' : this.k
		},
		icon() {
			if (CAUSE_LOOK[this.k]) return CAUSE_LOOK[this.k].icon
			return NOTICE_ICONS[this.k] || NOTICE_ICONS.error
		},
		heading() {
			if (this.title) return this.title
			if (this.k === 'session') return ts('notice_session_cover_title')
			if (this.k === 'role') return ts('notice_role_cover_title')
			if (this.k === 'down') return ts('notice_down_cover_title')
			if (this.k === 'error') return ts('notice_error_cover_title')
			if (this.k === 'resolving') return ts('notice_resolving')
			return ''
		},
		// the sentence, led by WHAT is locked when the page names it (subject): "Phone alerts: sign-in required." (one line under a group of controls)
		message() {
			const text = this.baseMessage
			return this.subject && (this.variant === 'reason' || this.variant === 'section') && text ? ts('notice_subject', { subject: this.subject, text }) : text
		},
		baseMessage() {
			void this.identityTick
			if (this.text) return this.text
			if (CAUSE_LOOK[this.k] && this.verdict && this.verdict.show) return this.causeText(this.verdict)
			if (this.k === 'role' && this.verdict && this.verdict.show && !this.kind && !this.action) return this.roleText(this.verdict)
			if (this.k === 'session' && this.variant === 'cover' && sessionState() === 'signed-out') return ts('notice_session_cover')
			const needed = this.kind ? this.needed || this.need || this.min : this.need || this.min || this.needed
			if (!this.kind && !this.action) return this.op ? lockReasonOp(this.op, this.need, this.ctx || undefined) : lockReason(this.min)
			return noticeText(this.k, { needed, role: workshopRole(), state: sessionState(), action: this.action }, ts)
		},
		step() {
			return noticeActionOf(this.k, this.variant, this.act)
		},
		// the button carries the icon of its action (2026-11-18), the same ones the bar chip and the notice use
		actIcon() {
			if (this.step === 'retry') return 'mdi-refresh'
			return this.step === 'change-role' ? 'mdi-account-switch-outline' : 'mdi-account-lock-outline'
		},
		actLabel() {
			if (this.step === 'retry') return ts('notice_retry')
			return this.step === 'change-role' ? ts('notice_change_role') : ts('notice_sign_in')
		}
	},
	methods: {
		ts,
		askCan() {
			if (this.askItems.length) this.wantCan(this.askItems)
		},
		// the sentence of a cause only a profile-aware answer gives; the name of a condition is a phrase of its own
		causeText(v) {
			const p = Object.assign({}, v.params)
			if (v.nested) p[v.nested.param] = ts(v.nested.key, v.nested.params)
			return ts(v.key, p)
		},
		roleText(v) {
			return noticeText('role', { needed: v.params.needed || this.need || this.min || this.needed, role: workshopRole(), state: sessionState() }, ts)
		},
		// "Sign in" and "Change role" are the one dialog (askLogin): the session of this browser, if any, stays until the new one is accepted
		async run() {
			if (this.step === 'retry') return this.$emit('retry')
			if (await askLogin()) this.$emit('retry')
		}
	}
}
</script>
