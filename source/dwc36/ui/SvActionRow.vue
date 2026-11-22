<template>
	<!-- THE row of the page: one thing, its sentence, its control and what happened when it was touched, all in one place.
	     Props:
	       icon (an mdi class), name, desc
	       action      the action object of the control ({ state, error, text, run, cancel, hold } of core/store/action.js) or null
	       permission  { state: 'ok' | 'resolving' | 'session' | 'role' } for the control (default: allowed)
	       label / armLabel   the built-in button: its text, and its text while armed ("Touch again to restart"); danger paints it red
	       stale       the datum is old (the service is stopped): the row dims and nothing can be touched
	       errorText   the sentence of a refusal, when the screen says it better than the service (it lists the reasons itself)
	     Slots: control ({ state, disabled, armed, run, hold, cancel }) replaces the built-in button (a switch, segments, a field + button);
	            ctl-before (before the control, in the same line), ctl-after (next to the control, e.g. its result), help (the row help), body (what the row unfolds, a block under the head at the full width), default (extra lines under the sentence).
	     Events: run (the control was touched: the screen calls action.run with its arguments), retry.
	     The outcome under the row follows the action: sending, verifying, done (leaves by itself), refused (stays until the next try),
	     not confirmed. A locked control shows NO sentence here: the block carries one for all its rows (LockReason). -->
	<li class="sv-row" :class="{ 'sv-stale': stale }" :data-state="state" :data-ctl="below ? 'below' : null">
		<div class="sv-row-main">
			<span v-if="icon" class="mdi sv-ico" :class="icon" aria-hidden="true" />
			<div>
				<div class="sv-row-name">{{ name }}</div>
				<div v-if="desc" class="sv-row-desc">{{ desc }}</div>
				<slot />
			</div>
		</div>
		<div class="sv-row-ctl">
			<slot name="ctl-before" />
			<span v-if="resolving" class="sv-neutral" role="img" :aria-label="kt('checking_permission')" />
			<slot v-else name="control" :state="state" :disabled="disabled" :armed="armed" :run="run" :hold="hold" :cancel="cancel">
				<button v-if="label" type="button" class="wf-btn sv-btn" :class="{ 'wf-danger': danger }" :data-state="state" :disabled="disabled" :aria-disabled="locked ? 'true' : null" :aria-describedby="locked && permission.text ? reasonId : null" :title="locked && permission.text ? permission.text : null"
					:aria-busy="busyHeld ? 'true' : null" @click="run" @focus="onFocus" @blur="onBlur" @keydown.esc="cancel">
					<span v-if="locked" class="mdi mdi-lock-outline sv-ico sv-ico-s" aria-hidden="true" />
					<!-- the button keeps ONE width: the texts it may show are stacked and the longest one sets it; a wait is a spinner over the text, never another text -->
					<span class="sv-btn-stack" :data-alt="alt">{{ buttonText }}</span>
				</button>
			</slot>
			<slot name="ctl-after" />
			<span v-if="working" class="sv-vh" role="status">{{ kt(state === 'verifying' ? 'verifying' : 'sending') }}</span>
		</div>
		<!-- a locked control carries its reason RIGHT THERE (what asks for the role, the role and what to do), grey with a padlock; the one of the foot of the card is then not drawn -->
		<p v-if="locked && permission.text" :id="reasonId" class="sv-row-reason" data-part="reason"><span class="mdi mdi-lock-outline sv-ico sv-ico-s" aria-hidden="true" />{{ permission.text }}</p>
		<div v-if="$scopedSlots.help || $slots.help" class="sv-row-help" data-part="help"><slot name="help" /></div>
		<!-- what a row unfolds (a diff, a detail): a block of its own under the head, the full width of the row, never beside the control -->
		<div v-if="$scopedSlots.body || $slots.body" class="sv-row-body" data-part="body"><slot name="body" /></div>
		<div v-if="out" class="sv-row-out" :data-kind="out.kind" :role="out.kind === 'error' ? 'alert' : 'status'">
			<span class="mdi sv-ico sv-ico-s" :class="out.icon" aria-hidden="true" />
			<span>{{ out.text }}<code v-if="out.code">{{ out.code }}</code></span>
			<button v-if="out.retry" type="button" class="wf-btn sv-btn" @click="$emit('retry')">{{ kt('retry') }}</button>
			<button v-if="out.signIn" type="button" class="wf-btn sv-btn wf-main" @click="svSignIn()">{{ kt('sign_in') }}</button>
		</div>
	</li>
</template>

<script>
import { svTextMixin } from './sv-text.js'
import { svBusyMixin } from './sv-busy.js'

let serial = 0
const ICONS = { progress: 'mdi-timer-sand', done: 'mdi-check-circle-outline', error: 'mdi-close-circle-outline', unverified: 'mdi-alert-outline' }

export default {
	name: 'SvActionRow',
	mixins: [svTextMixin, svBusyMixin],
	// the one way in of the page (the shell provides it); without it the row only says what happened
	inject: { svSignIn: { default: null } },
	props: {
		icon: { type: String, default: '' },
		below: { type: Boolean, default: false },   // the control goes on its own line under the row (a form above it: the button closes it, at the left)
		name: { type: String, default: '' },
		desc: { type: String, default: '' },
		action: { type: Object, default: null },
		permission: { type: Object, default: null },
		label: { type: String, default: '' },
		armLabel: { type: String, default: '' },
		danger: { type: Boolean, default: false },
		stale: { type: Boolean, default: false },
		errorText: { type: String, default: '' }
	},
	data() {
		serial += 1
		return { reasonId: 'sv-reason-' + serial }
	},
	computed: {
		state() {
			return (this.action && this.action.state) || 'idle'
		},
		resolving() {
			return !!this.permission && this.permission.state === 'resolving'
		},
		locked() {
			return !!this.permission && (this.permission.state === 'session' || this.permission.state === 'role')
		},
		working() {
			return this.state === 'sending' || this.state === 'verifying'
		},
		armed() {
			return this.state === 'armed'
		},
		disabled() {
			return this.locked || this.stale || this.working || this.state === 'confirming'
		},
		busyNow() {
			return this.working
		},
		buttonText() {
			return this.armed && this.armLabel ? this.armLabel : this.label
		},
		// the other text the button may show: it only lends its width (CSS ::after), so the button never changes size
		alt() {
			return this.armed && this.armLabel ? this.label : this.armLabel
		},
		// the line under the row: null, or { kind, icon, text, code, retry }
		out() {
			const a = this.action
			if (!a) return null
			const line = (kind, text, code, retry) => ({ kind, icon: ICONS[kind], text, code: code || '', retry: !!retry })
			if (a.state === 'sending') return line('progress', this.kt('sending_note'))
			if (a.state === 'verifying') return line('progress', this.kt('verifying_note'))
			if (a.state === 'done') return line('done', [this.kt('done'), a.text].filter(Boolean).join(' '))
			if (a.state === 'error' && a.error) {
				if (a.error.code === 'unverified') return line('unverified', this.kt('unverified'), '', true)
				// the session closed under the person's hand: said HERE, next to what they touched, with the way in
				if (a.error.kind === 'session' && a.error.reason !== 'damaged' && a.error.reason !== 'unknown') return Object.assign(line('error', this.kt('session_closed')), { signIn: typeof this.svSignIn === 'function' })
				if (a.error.kind === 'session' || a.error.kind === 'role') return null      // the block says it once (LockReason)
				return line('error', [this.kt('refused'), this.errorText || a.error.message].filter(Boolean).join(' '), a.error.code, true)
			}
			return null
		}
	},
	methods: {
		run() {
			if (!this.disabled) this.$emit('run')
		},
		hold(on) {
			if (this.action && typeof this.action.hold === 'function') this.action.hold(on)
		},
		cancel() {
			if (this.armed && this.action) this.action.cancel()
		},
		// keyboard focus on the armed control: its time does not run; when the focus leaves, it is disarmed at once
		onFocus(e) {
			let keyboard = false
			try { keyboard = e.target.matches(':focus-visible') } catch (err) { keyboard = false }
			if (keyboard) this.hold(true)
		},
		onBlur() {
			this.hold(false)
			this.cancel()
		}
	}
}
</script>
