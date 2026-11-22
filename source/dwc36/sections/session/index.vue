<template>
	<!-- My session: a sheet over whatever is open (the session chip of the header opens it; `?s=session` is its address).
	     Signed in: who I am, my role, when the session closes by itself, change my PIN, change person, sign out.
	     Signed out: what can be seen without a session and the one way in. Nothing here opens the PIN dialog by itself.
	     Prop: open. Event: close (the shell goes back to the place underneath). -->
	<wf-sheet :open="open" :title="t('session.title')" @close="$emit('close')">
		<div class="sv-session" :data-mode="mode">
			<template v-if="mode === 'damaged'">
				<p role="alert"><strong>{{ t('shell.band_damaged_title') }}</strong></p>
				<p class="sv-quiet">{{ t('shell.cover_damaged_text') }}</p>
			</template>

			<template v-else-if="mode === 'in'">
				<dl class="sv-facts">
					<dt>{{ t('session.person') }}</dt><dd data-fact="name">{{ s.name }}</dd>
					<dt>{{ t('session.role') }}</dt><dd data-fact="role">{{ roleText }}</dd>
					<template v-if="idleText"><dt>{{ t('session.closes') }}</dt><dd data-fact="idle">{{ idleText }}</dd></template>
				</dl>

				<form v-if="pinOpen" class="sv-form sv-session-pin" autocomplete="off" @submit.prevent="submitPin">
					<div>
						<label class="sv-label" :for="ids.old">{{ t('session.pin_current') }}</label>
						<span class="sv-field"><input :id="ids.old" v-model="oldPin" type="password" inputmode="numeric" autocomplete="current-password" data-wf-autofocus :aria-invalid="oldError ? 'true' : null" :aria-describedby="oldError ? ids.old + '-e' : null" :disabled="busy"></span>
						<span v-if="oldError" :id="ids.old + '-e'" class="sv-field-error" role="alert"><span class="mdi mdi-alert-outline sv-ico sv-ico-s" aria-hidden="true" />{{ oldError }}</span>
					</div>
					<div>
						<label class="sv-label" :for="ids.fresh">{{ t('session.pin_new') }}</label>
						<span class="sv-field"><input :id="ids.fresh" v-model="newPin" :type="shown ? 'text' : 'password'" inputmode="numeric" autocomplete="new-password" :aria-invalid="newError ? 'true' : null" :aria-describedby="newError ? ids.fresh + '-e' : null" :disabled="busy"></span>
						<span v-if="newError" :id="ids.fresh + '-e'" class="sv-field-error" role="alert"><span class="mdi mdi-alert-outline sv-ico sv-ico-s" aria-hidden="true" />{{ newError }}</span>
					</div>
					<ul v-if="newPin" class="sv-pwm-reqs sv-session-reqs" :aria-label="t('session.pin_reqs')">
						<li v-for="r in reqs" :key="r.id" :class="r.ok ? 'sv-pwm-ok' : 'sv-pwm-no'"><span class="mdi" :class="r.ok ? 'mdi-check-circle-outline' : 'mdi-close-circle-outline'" aria-hidden="true" /><span class="sv-pwm-sr">{{ t(r.ok ? 'session.pin_req_met' : 'session.pin_req_not_met') }}: </span>{{ t('session.pin_req_' + r.id) }}</li>
					</ul>
					<div>
						<label class="sv-label" :for="ids.again">{{ t('session.pin_repeat') }}</label>
						<span class="sv-field"><input :id="ids.again" v-model="again" :type="shown ? 'text' : 'password'" inputmode="numeric" autocomplete="new-password" :aria-invalid="againError ? 'true' : null" :aria-describedby="againError ? ids.again + '-e' : null" :disabled="busy"></span>
						<span v-if="againError" :id="ids.again + '-e'" class="sv-field-error" role="alert"><span class="mdi mdi-alert-outline sv-ico sv-ico-s" aria-hidden="true" />{{ againError }}</span>
					</div>
					<button type="button" class="wf-btn sv-btn sv-text" :aria-pressed="shown ? 'true' : 'false'" @click="shown = !shown"><span class="mdi sv-ico sv-ico-s" :class="shown ? 'mdi-eye-off-outline' : 'mdi-eye-outline'" aria-hidden="true" />{{ t(shown ? 'session.pin_hide' : 'session.pin_show') }}</button>
					<p v-if="lockedS > 0" class="sv-field-error" role="alert"><span class="mdi mdi-lock-clock sv-ico sv-ico-s" aria-hidden="true" />{{ t('session.pin_locked', { t: lockedText }) }}</p>
					<p v-else-if="otherError" class="sv-field-error" role="alert"><span class="mdi mdi-alert-outline sv-ico sv-ico-s" aria-hidden="true" />{{ otherError }}</p>
					<div class="wf-sheet-foot">
						<button type="button" class="wf-btn sv-btn" :disabled="busy" @click="closePin">{{ t('kit.cancel') }}</button>
						<button type="submit" class="wf-btn sv-btn wf-main" :disabled="busy || lockedS > 0" :aria-busy="busy ? 'true' : null"><span class="sv-btn-stack"><span>{{ t('session.pin_save') }}</span></span></button>
					</div>
				</form>

				<template v-else>
					<p v-if="note" class="sv-session-note" role="status"><span class="mdi mdi-check-circle-outline sv-ico sv-ico-s" aria-hidden="true" />{{ note }}</p>
					<div class="sv-session-acts">
						<button type="button" class="wf-btn sv-btn" data-act="pin" @click="openPin">{{ t('session.change_pin') }}</button>
						<button type="button" class="wf-btn sv-btn" data-act="switch" @click="switchPerson">{{ kt('change_person') }}</button>
						<button type="button" class="wf-btn sv-btn" data-act="out" @click="leave">{{ t('session.sign_out') }}</button>
					</div>
				</template>
			</template>

			<template v-else-if="mode === 'open'">
				<p>{{ t(s.usersOff ? 'shell.band_roles_off_title' : 'shell.band_open_title') }}</p>
				<p class="sv-quiet">{{ t('session.open_text') }}</p>
			</template>

			<template v-else-if="mode === 'resolving'">
				<p class="sv-quiet" role="status">{{ t('shell.session_resolving') }}</p>
			</template>

			<template v-else>
				<p v-if="note" class="sv-session-note" role="status">{{ note }}</p>
				<p>{{ t(s.loginRequired ? 'session.out_closed' : 'session.out_text') }}</p>
				<div class="sv-session-acts">
					<button type="button" class="wf-btn sv-btn wf-main" data-act="in" data-wf-autofocus @click="switchPerson">{{ kt('sign_in') }}</button>
				</div>
			</template>
		</div>
	</wf-sheet>
</template>

<script>
import { t } from '../../core/dwc.js'
import { every, timeNow } from '../../core/clock.js'
import { session, signIn, signOut } from '../../core/store/session.js'
import { createAction } from '../../core/store/action.js'
import { durationText } from '../../core/format/duration.js'
import { svTextMixin } from '../../ui/sv-text.js'
import WfSheet from '../../WfSheet.vue'
import { modeOf, pinProblems, pinRequirements, roleText } from './view.js'

const changePin = createAction({ op: 'auth.change_pin' })
const BASE_ROLES = ['viewer', 'operator', 'technician', 'admin']
let serial = 0

export default {
	name: 'SessionSection',
	components: { WfSheet },
	mixins: [svTextMixin],
	props: { open: { type: Boolean, default: false } },
	data() {
		serial += 1
		const id = 'sv-session-' + serial
		return { s: session, changePin, pinOpen: false, oldPin: '', newPin: '', again: '', shown: false, tried: false, note: '', lockedS: 0, ids: { old: id + '-old', fresh: id + '-new', again: id + '-again' } }
	},
	computed: {
		mode() {
			return modeOf(this.s)
		},
		roleText() {
			const r = roleText(this.s, BASE_ROLES)
			const base = r.base ? t('api.role_' + r.base) : ''
			return r.custom ? (base ? t('session.role_custom', { name: r.custom, base }) : r.custom) : base
		},
		// "it closes after 12 h without use": never a countdown (the service does not tell when it expires)
		idleText() {
			const m = this.s.idleMinutes
			return typeof m === 'number' && m > 0 ? t('session.closes_after', { t: durationText(m * 60, (k, p) => t('kit.' + k, p)) }) : ''
		},
		busy() {
			return this.changePin.state === 'sending'
		},
		problems() {
			return pinProblems({ oldPin: this.oldPin, newPin: this.newPin, again: this.again })
		},
		reqs() {
			return pinRequirements(this.newPin, this.again)
		},
		failure() {
			return this.changePin.state === 'error' ? this.changePin.error : null
		},
		oldError() {
			if (this.failure && this.failure.kind === 'credentials') return t('session.pin_wrong')
			return this.tried && this.problems.old ? t('session.pin_need_current') : ''
		},
		newError() {
			if (this.failure && this.failure.kind === 'validation') return this.failure.message
			return this.tried && this.problems.fresh ? t('session.pin_' + this.problems.fresh) : ''
		},
		againError() {
			return this.tried && this.problems.again ? t('session.pin_mismatch') : ''
		},
		otherError() {
			const e = this.failure
			return e && ['credentials', 'validation', 'locked'].indexOf(e.kind) < 0 ? e.message : ''
		},
		lockedText() {
			return durationText(this.lockedS, (k, p) => t('kit.' + k, p))
		}
	},
	watch: {
		'changePin.state'(now) {
			if (now === 'error') this.focusOn('[aria-invalid="true"], .sv-session-pin input')
			if (now === 'done') {
				this.closePin()
				this.note = t('session.pin_done')
				this.focusOn('[data-act="pin"]')
			} else if (now === 'error' && this.changePin.error && this.changePin.error.kind === 'locked') {
				this.lockFor(Number(this.changePin.error.extra && this.changePin.error.extra.wait_s) || 0)
			}
		},
		// another person (or nobody): what was typed is not theirs
		's.generation'() {
			this.closePin()
			this.note = ''
		},
		open(now) {
			if (!now) { this.closePin(); this.note = '' }
		},
		// what the service refused was about what was typed THEN: typing again takes the sentence away
		oldPin() { this.forgetRefusal() },
		newPin() { this.forgetRefusal() }
	},
	beforeDestroy() {
		this.lockFor(0)
	},
	methods: {
		t,
		openPin() {
			this.note = ''
			this.pinOpen = true
			this.focusOn('[data-wf-autofocus]')
		},
		// the keyboard focus goes where the task goes on (the first field, the field at fault, the button that opened the form)
		focusOn(selector) {
			this.$nextTick(() => this.$nextTick(() => {
				const el = this.$el && this.$el.querySelector ? this.$el.querySelector(selector) : null
				if (el && typeof el.focus === 'function') el.focus()
			}))
		},
		forgetRefusal() {
			const e = this.changePin.state === 'error' && this.changePin.error
			if (e && (e.kind === 'credentials' || e.kind === 'validation')) this.changePin.reset()
		},
		closePin() {
			Object.assign(this, { pinOpen: false, oldPin: '', newPin: '', again: '', shown: false, tried: false })
			this.lockFor(0)
			if (this.changePin.state === 'error') this.changePin.reset()
		},
		// a locked PIN: the seconds the service said, counted down here (its own clock: it lives only while there is something to count)
		lockFor(seconds) {
			if (this.offLock) this.offLock()
			this.offLock = null
			this.lockedS = Math.max(0, Math.ceil(seconds))
			if (!this.lockedS) return
			const until = timeNow() + this.lockedS * 1000
			this.offLock = every(1, () => {
				this.lockedS = Math.max(0, Math.ceil((until - timeNow()) / 1000))
				if (!this.lockedS) this.lockFor(0)
			})
		},
		submitPin() {
			this.tried = true
			if (this.busy || this.lockedS > 0) return
			if (this.problems.old || this.problems.fresh || this.problems.again) return this.focusOn('[aria-invalid="true"]')
			if (this.changePin.state === 'error') this.changePin.reset()
			this.changePin.run({ old_pin: this.oldPin, new_pin: this.newPin })
		},
		// the one name + PIN dialog of the family; the session of now stays until the other person is in
		switchPerson() {
			this.$emit('close')
			signIn()
		},
		leave() {
			this.note = t('session.signed_out')
			signOut()
		}
	}
}
</script>
