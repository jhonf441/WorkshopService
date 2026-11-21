<template>
	<!-- Access > Settings: the password of DWC (the one DWC asks to connect). The chip says whether one is set; two fields; Set and Remove are level 3
	     (the card asks the two touches itself). The state is read with a session and read again after every change. -->
	<div class="sv-access-password">
		<dwc-password-card :state="key" :problem="problem" :valid="valid" :level="level" :reqs="reqs" :min="min" :max="max" :signed-out="out" @put="put" @remove="remove" />
	</div>
</template>

<script>
import { call } from '../../core/api/call.js'
import { session, want } from '../../core/store/session.js'
import { t } from '../../core/dwc.js'
import { DwcPasswordCard } from '../../session-kit.js'
import { failureOf, resultText } from '../../arm-kit.js'
import { check, strength, requirements, MIN_LEN, MAX_LEN } from '../../password-policy.js'

export default {
	name: 'PasswordTab',
	components: { DwcPasswordCard },
	props: { active: { type: Boolean, default: false } },
	data() {
		return { session, min: MIN_LEN, max: MAX_LEN, key: { has: null, newEntry: '', repeat: '', show: false, sending: false, msg: '', error: null, fieldError: null } }
	},
	computed: {
		out() {
			return this.session.state !== 'active' && this.session.state !== 'resolving'
		},
		names() {
			return [this.session.name]
		},
		// the first rule that is not met yet, in words ('' = it can be set). The server applies the same policy and has the last word.
		reason() {
			const c = this.key.newEntry || ''
			return c ? check(c, this.key.repeat || '', this.names) : 'empty'
		},
		problem() {
			return this.reason ? t('servicePage.pw_reason_' + this.reason) : ''
		},
		valid() {
			return !this.reason
		},
		level() {
			return strength(this.key.newEntry || '')
		},
		reqs() {
			return requirements(this.key.newEntry, this.key.repeat, this.names)
		}
	},
	watch: {
		active: { immediate: true, handler(on) { if (on) { want(['password.set', 'password.clear', 'password.status']); this.read() } } },
		// the person changed: what was typed and answered belonged to the one who left
		'session.generation'() {
			this.key = { has: null, newEntry: '', repeat: '', show: false, sending: false, msg: '', error: null, fieldError: null }
			if (this.active) this.read()
		},
		// typing again clears what the server said about the last try
		'key.newEntry'() { this.key.fieldError = null },
		'key.repeat'() { this.key.fieldError = null }
	},
	methods: {
		async read() {
			if (this.out) { this.key.has = null; return }
			try {
				const r = await call('password.status', {}, { quiet: true })
				this.key.has = r.data && typeof r.data.set === 'boolean' ? r.data.set : null
			} catch (e) {
				this.key.has = null
			}
		},
		// the card asks the two touches: these run on the second one; a failure keeps what was typed and shows the real error
		async run(op, args) {
			this.key.sending = true
			this.key.msg = ''
			this.key.error = null
			try {
				const r = await call(op, args || {})
				this.key.msg = r.data ? resultText(r.data) : r.text
				return true
			} catch (e) {
				// a refusal of the policy (422 invalid_args with reason) is said under its field; any other failure keeps the notice
				if (e && e.code === 'invalid_args' && e.reason) this.key.fieldError = { field: e.field === 'repeat' ? 'repeat' : 'password', text: e.message }
				else this.key.error = failureOf(e)
				return false
			} finally {
				this.key.sending = false
			}
		},
		async put() {
			if (!this.valid) return
			if (await this.run('password.set', { password: this.key.newEntry, repeat: this.key.repeat })) {
				this.key.newEntry = ''
				this.key.repeat = ''
			}
			this.read()
		},
		async remove() {
			await this.run('password.clear')
			this.read()
		}
	}
}
</script>
