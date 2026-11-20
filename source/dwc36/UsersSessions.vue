<template>
	<!-- Sessions and settings of the people (administrator only, drawn by UsersCard): expiry, camera for viewers, anonymous viewer, close the other
	     sessions (double tap) and turn the roles off. Operations: users.settings, users.close_sessions, users.enable. Emits `changed` after each one. -->
	<div>
		<v-card class="mb-3">
			<v-card-title>
				<v-icon small class="mr-2 svx-ico">mdi-timer-outline</v-icon>{{ $t('plugins.WorkshopService.users.sessions_title') }}
			</v-card-title>
			<v-card-text>
				<v-row dense>
					<v-col cols="12"><sv-toggle v-model="cfg.never_expires" :label="$t('plugins.WorkshopService.users.never_expires')" /><div class="text-caption grey--text">{{ $t('plugins.WorkshopService.users.never_expires_help') }}</div></v-col>
					<v-col cols="6" sm="3"><sv-text-field v-model.number="cfg.idle_minutes" type="number" min="1" max="1440" :disabled="!!cfg.never_expires" :label="$t('plugins.WorkshopService.users.idle_minutes')" /></v-col>
					<v-col cols="6" sm="3"><sv-text-field v-model.number="cfg.max_hours" type="number" min="1" max="168" :disabled="!!cfg.never_expires" :label="$t('plugins.WorkshopService.users.max_hours')" /></v-col>
				</v-row>
				<sv-toggle v-model="cfg.camera_for_viewer" :label="$t('plugins.WorkshopService.users.camera_for_viewers')" />
				<div class="text-caption grey--text mb-2">{{ $t('plugins.WorkshopService.users.camera_for_viewers_help') }}</div>
				<sv-toggle v-model="cfg.anonymous_viewer" :label="$t('plugins.WorkshopService.users.anonymous_viewer')" />
				<div class="text-caption grey--text mb-2">{{ $t('plugins.WorkshopService.users.anonymous_viewer_help') }}</div>
				<v-btn small color="primary" :loading="busy" @click="saveSettings">{{ $t('plugins.WorkshopService.users.save') }}</v-btn>
				<span v-if="msg" class="text-caption ml-3">{{ msg }}</span>
				<v-divider class="my-4" />
				<div class="text-body-2 font-weight-medium">{{ $t('plugins.WorkshopService.users.close_title') }}</div>
				<div class="text-caption grey--text mb-2">{{ $t('plugins.WorkshopService.users.close_help') }}</div>
				<v-btn small outlined :color="armed ? 'error' : null" :loading="busy" @click="closeOthers">{{ armed ? $t('plugins.WorkshopService.users.close_again') : $t('plugins.WorkshopService.users.close_btn') }}</v-btn>
				<span v-if="closeMsg" class="text-caption ml-3" role="status">{{ closeMsg }}</span>
				<v-divider class="my-4" />
				<div class="text-body-2 font-weight-medium">{{ $t('plugins.WorkshopService.users.off_title') }}</div>
				<div class="text-caption grey--text mb-2">{{ $t('plugins.WorkshopService.users.off_help') }}</div>
				<v-btn small outlined color="warning" @click="offPin = ''; offError = ''; dlgOff = true">{{ $t('plugins.WorkshopService.users.off_button') }}</v-btn>
			</v-card-text>
		</v-card>
		<v-dialog v-model="dlgOff" max-width="400">
			<v-card>
				<v-card-title class="text-subtitle-1">{{ $t('plugins.WorkshopService.users.off_dialog_title') }}</v-card-title>
				<v-card-text>
					<div class="text-body-2 mb-3">{{ $t('plugins.WorkshopService.users.off_dialog_help') }}</div>
					<sv-text-field v-model="offPin" type="password" inputmode="numeric" :label="$t('plugins.WorkshopService.users.pin')" autocomplete="current-password" @enter="switchOff" />
					<v-alert v-if="offError" dense text type="error" class="mb-0">{{ offError }}</v-alert>
				</v-card-text>
				<v-card-actions>
					<v-spacer />
					<v-btn text @click="dlgOff = false">{{ $t('plugins.WorkshopService.common.cancel') }}</v-btn>
					<v-btn color="warning" :loading="busy" :disabled="!offPin" @click="switchOff">{{ $t('plugins.WorkshopService.users.off_confirm') }}</v-btn>
				</v-card-actions>
			</v-card>
		</v-dialog>
	</div>
</template>

<script>
'use strict'

import SvTextField from './ui/SvTextField.vue'
import { api, whoami } from './workshop-api.js'
import { roleMixin } from './role-mixin.js'
import SvToggle from './ui/SvToggle.vue'

export default {
	name: 'UsersSessions',
	components: { SvTextField, SvToggle },
	mixins: [roleMixin],
	// what was typed or answered belongs to the session that left: emptied on sign-out and on a change of role
	sessionData: ['dlgOff', 'offPin', 'offError', 'armed', 'busy', 'msg', 'closeMsg'],
	props: { settings: { type: Object, default: () => ({}) } }, // users.list settings: the values of the form
	data() {
		return {
			cfg: Object.assign({ idle_minutes: 720, max_hours: 12, never_expires: false, camera_for_viewer: false, anonymous_viewer: false }, this.settings),
			dlgOff: false, offPin: '', offError: '', armed: false, busy: false, msg: '', closeMsg: ''
		}
	},
	watch: {
		settings(s) { Object.assign(this.cfg, s) }
	},
	methods: {
		fail(e) { return e && e.code !== 'cancelled' ? (e.message || String(e)) : '' },
		async switchOff() {
			if (!this.offPin) return
			this.busy = true
			this.offError = ''
			try {
				await api('users.enable', { enabled: false, pin: this.offPin }, { noLogin: true })
				this.offPin = ''
				this.dlgOff = false
				await whoami() // the sessions ended: the page is in compatibility mode now
			} catch (e) {
				this.offError = this.fail(e)
			}
			this.busy = false
		},
		// ends every session but this one (two touches: it throws people out, kiosk included, until they type their PIN again)
		async closeOthers() {
			if (!this.armed) {
				this.armed = true
				this.closeMsg = ''
				setTimeout(() => { this.armed = false }, 4000)
				return
			}
			this.armed = false
			this.busy = true
			try {
				const r = await api('users.close_sessions', {})
				const n = Number(r && r.closed) || 0
				this.closeMsg = n ? this.$tc('plugins.WorkshopService.users.close_done', n, { n }) : this.$t('plugins.WorkshopService.users.close_none')
				this.$emit('changed')
			} catch (e) {
				this.closeMsg = this.fail(e)
			}
			this.busy = false
		},
		async saveSettings() {
			this.busy = true
			this.msg = ''
			try {
				const c = this.cfg
				const r = await api('users.settings', { idle_minutes: Number(c.idle_minutes), max_hours: Number(c.max_hours), never_expires: !!c.never_expires, camera_for_viewer: !!c.camera_for_viewer, anonymous_viewer: !!c.anonymous_viewer })
				Object.assign(this.cfg, r.settings)
				this.msg = this.$t('plugins.WorkshopService.users.saved')
				this.$emit('changed')
			} catch (e) {
				this.msg = this.fail(e)
			}
			this.busy = false
		}
	}
}
</script>
