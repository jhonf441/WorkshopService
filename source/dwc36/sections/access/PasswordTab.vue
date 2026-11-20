<template>
	<!-- Access > Settings: the password of DWC (the one DWC asks to connect). The chip says whether one is set; two fields; Set and Remove are level 3
	     (the card asks the two touches itself). The state is read with a session and read again after every change. -->
	<div class="sv-access-password">
		<dwc-password-card :state="key" :problem="problem" :valid="valid" :signed-out="out" @put="put" @remove="remove" />
	</div>
</template>

<script>
import { call } from '../../core/api/call.js'
import { session, want } from '../../core/store/session.js'
import { t } from '../../core/dwc.js'
import { DwcPasswordCard } from '../../session-kit.js'
import { failureOf, resultText } from '../../arm-kit.js'

export default {
	name: 'PasswordTab',
	components: { DwcPasswordCard },
	props: { active: { type: Boolean, default: false } },
	data() {
		return { session, key: { has: null, newEntry: '', repeat: '', sending: false, msg: '', error: null } }
	},
	computed: {
		out() {
			return this.session.state !== 'active' && this.session.state !== 'resolving'
		},
		// what is wrong with what was typed ('' = nothing)
		problem() {
			const c = this.key.newEntry || ''
			if (c.length < 4 || c.length > 60) return t('servicePage.it_must_have_4_to_60')
			if (/[";\r\n]/.test(c) || /[\x00-\x1f]/.test(c)) return t('servicePage.it_can_t_contain_quotes_semicolons')
			if (c.toLowerCase() === 'reprap') return t('servicePage.reprap_is_the_factory_one_no')
			if (c !== this.key.repeat) return t('servicePage.the_two_don_t_match')
			return ''
		},
		valid() {
			return !!this.key.newEntry && !this.problem
		}
	},
	watch: {
		active: { immediate: true, handler(on) { if (on) { want(['password.set', 'password.clear', 'password.status']); this.read() } } },
		// the person changed: what was typed and answered belonged to the one who left
		'session.generation'() {
			this.key = { has: null, newEntry: '', repeat: '', sending: false, msg: '', error: null }
			if (this.active) this.read()
		}
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
				this.key.error = failureOf(e)
				return false
			} finally {
				this.key.sending = false
			}
		},
		async put() {
			if (!this.valid) return
			if (await this.run('password.set', { password: this.key.newEntry })) {
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
