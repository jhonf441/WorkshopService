<template>
	<div>
		<!-- No user yet: everybody with access to DWC is an administrator (compatibility). Wizard for the first one. -->
		<!-- The roles are switched off but the people are saved: anybody with access to DWC is an administrator until they are switched on again. -->
		<v-card v-if="identity && identity.users_disabled" class="mb-3">
			<v-card-title>
				<v-icon small class="mr-2" color="warning">mdi-account-off-outline</v-icon>{{ $t('plugins.WorkshopService.users.disabled_title') }}
			</v-card-title>
			<v-card-text>
				<div class="text-body-2 mb-3">{{ $t('plugins.WorkshopService.users.disabled_help') }}</div>
				<v-btn small color="primary" :loading="busy" @click="switchOn">{{ $t('plugins.WorkshopService.users.switch_on') }}</v-btn>
				<v-alert v-if="error" dense text type="error" class="mt-3 mb-0">{{ error }}</v-alert>
			</v-card-text>
		</v-card>

		<v-card v-else-if="state.configured === false" class="mb-3">
			<v-card-title>
				<v-icon small class="mr-2" color="warning">mdi-account-alert-outline</v-icon>{{ $t('plugins.WorkshopService.users.no_users_title') }}
			</v-card-title>
			<v-card-text>
				<v-alert dense text type="warning" class="mb-3">{{ $t('plugins.WorkshopService.users.no_users_notice') }}</v-alert>
				<div class="text-body-2 mb-3">{{ $t('plugins.WorkshopService.users.wizard_help') }}</div>
				<v-row dense>
					<v-col cols="12" sm="4"><v-text-field v-model="first.name" :label="$t('plugins.WorkshopService.users.name')" dense outlined hide-details autocomplete="username" /></v-col>
					<v-col cols="6" sm="3"><v-text-field :append-icon="showPins ? 'mdi-eye-off' : 'mdi-eye'" @click:append="showPins = !showPins" v-model="first.pin" :type="showPins ? 'text' : 'password'" inputmode="numeric" :label="$t('plugins.WorkshopService.users.pin')" dense outlined hide-details autocomplete="new-password" /></v-col>
					<v-col cols="6" sm="3"><v-text-field v-model="first.repeat" :type="showPins ? 'text' : 'password'" inputmode="numeric" :label="$t('plugins.WorkshopService.users.pin_repeat')" dense outlined hide-details autocomplete="new-password" /></v-col>
					<v-col cols="12" sm="2" class="d-flex align-center">
						<v-btn small block color="primary" :loading="busy" :disabled="!firstValid" @click="createFirst">{{ $t('plugins.WorkshopService.users.create_admin') }}</v-btn>
					</v-col>
				</v-row>
				<div v-if="first.pin && first.repeat && first.pin !== first.repeat" class="text-caption warning--text mt-1">{{ $t('plugins.WorkshopService.users.pins_differ') }}</div>
				<v-alert v-if="error" dense text type="error" class="mt-3 mb-0">{{ error }}</v-alert>
			</v-card-text>
		</v-card>

		<!-- My session -->
		<v-card v-if="state.configured" class="mb-3">
			<v-card-title>
				<v-icon small class="mr-2 svx-ico">mdi-account-circle-outline</v-icon>{{ $t('plugins.WorkshopService.users.my_session') }}
			</v-card-title>
			<v-card-text class="d-flex align-center flex-wrap" style="gap:8px">
				<template v-if="me && me.name">
					<strong>{{ me.name }}</strong>
					<v-chip small outlined :color="roleColor(me.role)">{{ roleName(me.role) }}</v-chip>
					<v-spacer />
					<v-btn small outlined @click="openPin"><v-icon left small>mdi-form-textbox-password</v-icon>{{ $t('plugins.WorkshopService.users.change_my_pin') }}</v-btn>
					<v-btn small outlined @click="logout"><v-icon left small>mdi-logout</v-icon>{{ $t('plugins.WorkshopService.users.log_out') }}</v-btn>
				</template>
				<template v-else>
					<span class="text-body-2 grey--text">{{ $t('plugins.WorkshopService.users.not_identified') }}</span>
					<v-spacer />
					<v-btn small color="primary" @click="logIn"><v-icon left small>mdi-login</v-icon>{{ $t('plugins.WorkshopService.users.log_in') }}</v-btn>
				</template>
			</v-card-text>
		</v-card>

		<v-alert v-if="state.configured && !isAdmin" dense text type="info" class="mb-3">{{ $t('plugins.WorkshopService.users.admin_only') }}</v-alert>

		<template v-if="state.configured && isAdmin">
			<!-- People -->
			<v-card class="mb-3">
				<v-card-title>
					<v-icon small class="mr-2 svx-ico">mdi-account-group-outline</v-icon>{{ $t('plugins.WorkshopService.users.title') }}
					<v-spacer />
					<v-btn small color="primary" @click="openNew"><v-icon left small>mdi-plus</v-icon>{{ $t('plugins.WorkshopService.users.add') }}</v-btn>
				</v-card-title>
				<v-card-text>
					<div class="text-caption grey--text mb-2">{{ $t('plugins.WorkshopService.users.help') }}</div>
					<v-alert v-if="error" dense text type="error" class="mb-2">{{ error }}</v-alert>
					<v-simple-table dense>
						<thead>
							<tr>
								<th>{{ $t('plugins.WorkshopService.users.name') }}</th>
								<th>{{ $t('plugins.WorkshopService.users.role') }}</th>
								<th>{{ $t('plugins.WorkshopService.users.modes') }}</th>
								<th>{{ $t('plugins.WorkshopService.users.camera') }}</th>
								<th>{{ $t('plugins.WorkshopService.users.last_seen') }}</th>
								<th />
							</tr>
						</thead>
						<tbody>
							<tr v-for="u in state.users" :key="u.name">
								<td><strong>{{ u.name }}</strong></td>
								<td><v-chip x-small label :color="roleColor(u.role)" dark>{{ roleName(u.role) }}</v-chip></td>
								<td>
									<span v-if="u.role === 'operator'">
										<v-chip v-for="m in u.modes" :key="m" x-small label outlined class="mr-1">{{ modeName(m) }}</v-chip>
										<span v-if="!u.modes.length" class="text-caption grey--text">{{ $t('plugins.WorkshopService.users.no_modes') }}</span>
									</span>
									<span v-else class="text-caption grey--text">{{ u.role === 'viewer' ? '-' : $t('plugins.WorkshopService.users.all_modes') }}</span>
								</td>
								<td>
									<v-icon v-if="u.role === 'viewer'" small :color="u.camera_for_viewer || state.settings.camera_for_viewer ? 'success' : 'grey'">{{ u.camera_for_viewer || state.settings.camera_for_viewer ? 'mdi-video' : 'mdi-video-off' }}</v-icon>
									<span v-else class="text-caption grey--text">-</span>
								</td>
								<td class="text-caption">{{ u.last_seen ? date(u.last_seen) : $t('plugins.WorkshopService.users.never') }}</td>
								<td class="text-right" style="white-space:nowrap">
									<v-btn icon small :title="$t('plugins.WorkshopService.users.edit')" @click="openEdit(u)"><v-icon small>mdi-pencil</v-icon></v-btn>
									<v-btn icon small :title="$t('plugins.WorkshopService.users.reset_pin')" @click="openReset(u)"><v-icon small>mdi-form-textbox-password</v-icon></v-btn>
									<v-btn icon small :color="armed === u.name ? 'error' : null" :disabled="isMe(u)" :title="armed === u.name ? $t('plugins.WorkshopService.users.tap_again_remove') : $t('plugins.WorkshopService.users.remove')" @click="remove(u)">
										<v-icon small>mdi-delete</v-icon>
									</v-btn>
								</td>
							</tr>
						</tbody>
					</v-simple-table>
				</v-card-text>
			</v-card>

			<!-- Sessions -->
			<v-card class="mb-3">
				<v-card-title>
					<v-icon small class="mr-2 svx-ico">mdi-timer-outline</v-icon>{{ $t('plugins.WorkshopService.users.sessions_title') }}
				</v-card-title>
				<v-card-text>
					<v-row dense>
						<v-col cols="12"><v-switch v-model="cfg.never_expires" dense hide-details :label="$t('plugins.WorkshopService.users.never_expires')" /><div class="text-caption grey--text">{{ $t('plugins.WorkshopService.users.never_expires_help') }}</div></v-col>
						<v-col cols="6" sm="3"><v-text-field v-model.number="cfg.idle_minutes" type="number" min="1" max="1440" :disabled="!!cfg.never_expires" :label="$t('plugins.WorkshopService.users.idle_minutes')" dense outlined hide-details /></v-col>
						<v-col cols="6" sm="3"><v-text-field v-model.number="cfg.max_hours" type="number" min="1" max="168" :disabled="!!cfg.never_expires" :label="$t('plugins.WorkshopService.users.max_hours')" dense outlined hide-details /></v-col>
					</v-row>
					<v-switch v-model="cfg.camera_for_viewer" dense hide-details :label="$t('plugins.WorkshopService.users.camera_for_viewers')" class="mt-3" />
					<div class="text-caption grey--text mb-2">{{ $t('plugins.WorkshopService.users.camera_for_viewers_help') }}</div>
					<v-switch v-model="cfg.anonymous_viewer" dense hide-details :label="$t('plugins.WorkshopService.users.anonymous_viewer')" />
					<div class="text-caption grey--text mb-2">{{ $t('plugins.WorkshopService.users.anonymous_viewer_help') }}</div>
					<v-btn small color="primary" :loading="busy" @click="saveSettings">{{ $t('plugins.WorkshopService.users.save') }}</v-btn>
					<span v-if="msg" class="text-caption ml-3">{{ msg }}</span>
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
						<v-text-field v-model="offPin" type="password" inputmode="numeric" :label="$t('plugins.WorkshopService.users.pin')" dense outlined autocomplete="current-password" @keyup.enter="switchOff" />
						<v-alert v-if="offError" dense text type="error" class="mb-0">{{ offError }}</v-alert>
					</v-card-text>
					<v-card-actions>
						<v-spacer />
						<v-btn text @click="dlgOff = false">{{ $t('plugins.WorkshopService.common.cancel') }}</v-btn>
						<v-btn color="warning" :loading="busy" :disabled="!offPin" @click="switchOff">{{ $t('plugins.WorkshopService.users.off_confirm') }}</v-btn>
					</v-card-actions>
				</v-card>
			</v-dialog>
		</template>

		<!-- add / edit a person -->
		<v-dialog v-model="dlg" max-width="480">
			<v-card>
				<v-card-title class="text-subtitle-1">{{ form.edit ? $t('plugins.WorkshopService.users.edit_title', { name: form.name }) : $t('plugins.WorkshopService.users.new_title') }}</v-card-title>
				<v-card-text>
					<v-text-field v-if="!form.edit" v-model="form.name" :label="$t('plugins.WorkshopService.users.name')" dense outlined counter="32" autocomplete="off" />
					<template v-if="!form.edit">
						<v-row dense>
							<v-col cols="6"><v-text-field :append-icon="showPins ? 'mdi-eye-off' : 'mdi-eye'" @click:append="showPins = !showPins" v-model="form.pin" :type="showPins ? 'text' : 'password'" inputmode="numeric" :label="$t('plugins.WorkshopService.users.pin')" dense outlined hide-details autocomplete="new-password" /></v-col>
							<v-col cols="6"><v-text-field v-model="form.repeat" :type="showPins ? 'text' : 'password'" inputmode="numeric" :label="$t('plugins.WorkshopService.users.pin_repeat')" dense outlined hide-details autocomplete="new-password" /></v-col>
						</v-row>
						<div class="text-caption grey--text mt-1 mb-3">{{ $t('plugins.WorkshopService.users.pin_help', { min: state.min_pin, max: state.max_pin }) }}</div>
					</template>
					<v-select v-model="form.role" :items="roleItems" :label="$t('plugins.WorkshopService.users.role')" dense outlined :disabled="form.edit && isMe({ name: form.name })" />
					<div v-if="form.role === 'operator'">
						<div class="text-caption grey--text mb-1">{{ $t('plugins.WorkshopService.users.modes_help') }}</div>
						<div class="d-flex flex-wrap">
							<v-checkbox v-for="m in state.modes" :key="m" v-model="form.modes" :value="m" dense hide-details class="mr-4 mt-0" :label="modeName(m)" />
						</div>
					</div>
					<v-switch v-if="form.role === 'viewer'" v-model="form.camera" dense hide-details :label="$t('plugins.WorkshopService.users.camera_for_this')" />
					<v-alert v-if="formError" dense text type="error" class="mt-3 mb-0">{{ formError }}</v-alert>
				</v-card-text>
				<v-card-actions>
					<v-spacer />
					<v-btn text @click="dlg = false">{{ $t('plugins.WorkshopService.common.cancel') }}</v-btn>
					<v-btn color="primary" :loading="busy" :disabled="!formValid" @click="saveForm">{{ $t('plugins.WorkshopService.users.save') }}</v-btn>
				</v-card-actions>
			</v-card>
		</v-dialog>

		<!-- PIN: reset one of a person, or change my own -->
		<v-dialog v-model="dlgPin" max-width="400">
			<v-card>
				<v-card-title class="text-subtitle-1">{{ pinForm.own ? $t('plugins.WorkshopService.users.change_my_pin') : $t('plugins.WorkshopService.users.reset_title', { name: pinForm.name }) }}</v-card-title>
				<v-card-text>
					<v-text-field v-if="pinForm.own" v-model="pinForm.old" type="password" inputmode="numeric" :label="$t('plugins.WorkshopService.users.old_pin')" dense outlined autocomplete="current-password" />
					<v-text-field :append-icon="showPins ? 'mdi-eye-off' : 'mdi-eye'" @click:append="showPins = !showPins" v-model="pinForm.pin" :type="showPins ? 'text' : 'password'" inputmode="numeric" :label="$t('plugins.WorkshopService.users.new_pin')" dense outlined autocomplete="new-password" />
					<v-text-field v-model="pinForm.repeat" :type="showPins ? 'text' : 'password'" inputmode="numeric" :label="$t('plugins.WorkshopService.users.pin_repeat')" dense outlined hide-details autocomplete="new-password" />
					<div v-if="!pinForm.own" class="text-caption grey--text mt-2">{{ $t('plugins.WorkshopService.users.reset_help') }}</div>
					<v-alert v-if="formError" dense text type="error" class="mt-3 mb-0">{{ formError }}</v-alert>
				</v-card-text>
				<v-card-actions>
					<v-spacer />
					<v-btn text @click="dlgPin = false">{{ $t('plugins.WorkshopService.common.cancel') }}</v-btn>
					<v-btn color="primary" :loading="busy" :disabled="!pinValid" @click="savePin">{{ $t('plugins.WorkshopService.users.save') }}</v-btn>
				</v-card-actions>
			</v-card>
		</v-dialog>
	</div>
</template>

<script>
'use strict'

import { api, adoptSession, askLogin, changePin, currentIdentity, logout, onIdentity, whoami } from './workshop-api.js'

const ROLE_COLORS = { viewer: 'blue-grey', operator: 'primary', technician: 'amber darken-3', admin: 'error' };
const PIN_RE = /^[0-9]{4,12}$/;

function emptyForm() {
	return { edit: false, name: '', pin: '', repeat: '', role: 'operator', modes: ['laser'], camera: false };
}

export default {
	name: 'UsersCard',
	data() {
		return {
			state: { configured: null, users: [], settings: {}, roles: [], modes: [], min_pin: 4, max_pin: 12 },
			cfg: { idle_minutes: 720, max_hours: 12, never_expires: false, camera_for_viewer: false, anonymous_viewer: false },
			identity: currentIdentity(),
			showPins: false, dlgOff: false, offPin: '', offError: '', first: { name: '', pin: '', repeat: '' },
			form: emptyForm(), dlg: false,
			pinForm: { own: false, name: '', old: '', pin: '', repeat: '' }, dlgPin: false,
			armed: '', busy: false, error: '', formError: '', msg: '', off: null
		};
	},
	computed: {
		me() { return this.identity && this.identity.user && this.identity.user.name ? this.identity.user : null; },
		isAdmin() { return !!this.identity && this.identity.role === 'admin'; },
		roleItems() { return (this.state.roles || []).map(r => ({ value: r, text: this.roleName(r) })); },
		firstValid() { return !!this.first.name.trim() && PIN_RE.test(this.first.pin) && this.first.pin === this.first.repeat; },
		formValid() {
			const f = this.form;
			if (f.edit) return true;
			return !!f.name.trim() && PIN_RE.test(f.pin) && f.pin === f.repeat;
		},
		pinValid() {
			const p = this.pinForm;
			return PIN_RE.test(p.pin) && p.pin === p.repeat && (!p.own || !!p.old);
		}
	},
	async mounted() {
		this.off = onIdentity(i => { this.identity = i; this.read(); });
		await whoami().catch(() => null);
		this.identity = currentIdentity();
		await this.read();
	},
	beforeDestroy() { if (this.off) this.off(); },
	watch: {
		// the PINs are hidden again whenever a dialog closes
		dlg(open) { if (!open) this.showPins = false; },
		dlgPin(open) { if (!open) this.showPins = false; }
	},
	methods: {
		roleName(r) { return this.$t('plugins.WorkshopService.users.role_' + r); },
		modeName(m) { return this.$t('plugins.WorkshopService.users.mode_' + m); },
		roleColor(r) { return ROLE_COLORS[r] || 'grey'; },
		date(t) { try { return new Date(t * 1000).toLocaleString(this.$i18n.locale); } catch (e) { return String(t); } },
		isMe(u) { return !!this.me && this.me.name.toLowerCase() === String(u.name).toLowerCase(); },
		fail(e) { return e && e.code !== 'cancelled' ? (e.message || String(e)) : ''; },
		async read() {
			const id = this.identity;
			if (id && id.configured === false) {
				this.state = Object.assign({}, this.state, { configured: false });
				return;
			}
			if (!id || id.role !== 'admin') {
				this.state = Object.assign({}, this.state, { configured: id ? !!id.configured : null });
				return;
			}
			try {
				const r = await api('users.list', {}, { noLogin: true });
				this.state = r;
				Object.assign(this.cfg, r.settings);
				this.error = '';
			} catch (e) {
				this.error = this.fail(e);
			}
		},
		async createFirst() {
			this.busy = true;
			this.error = '';
			try {
				const r = await api('users.add', { name: this.first.name.trim(), pin: this.first.pin, role: 'admin' });
				await adoptSession(r.token); // whoever creates the first administrator is that administrator from now on
				this.first = { name: '', pin: '', repeat: '' };
				this.identity = currentIdentity();
				await this.read();
			} catch (e) {
				this.error = this.fail(e);
			}
			this.busy = false;
		},
		async switchOff() {
			if (!this.offPin) return;
			this.busy = true;
			this.offError = '';
			try {
				await api('users.enable', { enabled: false, pin: this.offPin }, { noLogin: true });
				this.offPin = '';
				this.dlgOff = false;
				await whoami(); // the sessions ended: the page is in compatibility mode now
			} catch (e) {
				this.offError = this.fail(e);
			}
			this.busy = false;
		},
		async switchOn() {
			this.busy = true;
			this.error = '';
			try {
				await api('users.enable', { enabled: true });
				await whoami(); // the roles are on again: this browser has to log in
			} catch (e) {
				this.error = this.fail(e);
			}
			this.busy = false;
		},
		openNew() { this.formError = ''; this.form = emptyForm(); this.dlg = true; },
		openEdit(u) {
			this.formError = '';
			this.form = Object.assign(emptyForm(), { edit: true, name: u.name, role: u.role, modes: u.modes.slice(), camera: !!u.camera_for_viewer });
			this.dlg = true;
		},
		async saveForm() {
			const f = this.form;
			this.busy = true;
			this.formError = '';
			try {
				const extra = { modes: f.role === 'operator' ? f.modes : [], camera_for_viewer: f.role === 'viewer' && f.camera };
				if (f.edit) await api('users.set', Object.assign({ name: f.name, role: f.role }, extra));
				else await api('users.add', Object.assign({ name: f.name.trim(), pin: f.pin, role: f.role }, extra));
				this.dlg = false;
				await this.read();
			} catch (e) {
				this.formError = this.fail(e);
			}
			this.busy = false;
		},
		openReset(u) { this.formError = ''; this.pinForm = { own: false, name: u.name, old: '', pin: '', repeat: '' }; this.dlgPin = true; },
		openPin() { this.formError = ''; this.pinForm = { own: true, name: this.me.name, old: '', pin: '', repeat: '' }; this.dlgPin = true; },
		async savePin() {
			const p = this.pinForm;
			this.busy = true;
			this.formError = '';
			try {
				if (p.own) await changePin(p.old, p.pin);
				else await api('users.reset_pin', { name: p.name, pin: p.pin });
				this.dlgPin = false;
				await this.read();
			} catch (e) {
				this.formError = this.fail(e);
			}
			this.busy = false;
		},
		async remove(u) {
			if (this.armed !== u.name) {
				this.armed = u.name;
				setTimeout(() => { if (this.armed === u.name) this.armed = ''; }, 4000);
				return;
			}
			this.armed = '';
			try {
				await api('users.remove', { name: u.name });
				await this.read();
			} catch (e) {
				this.error = this.fail(e);
			}
		},
		async saveSettings() {
			this.busy = true;
			this.msg = '';
			try {
				const c = this.cfg;
				const r = await api('users.settings', { idle_minutes: Number(c.idle_minutes), max_hours: Number(c.max_hours), never_expires: !!c.never_expires, camera_for_viewer: !!c.camera_for_viewer, anonymous_viewer: !!c.anonymous_viewer });
				Object.assign(this.cfg, r.settings);
				this.msg = this.$t('plugins.WorkshopService.users.saved');
				await this.read();
			} catch (e) {
				this.msg = this.fail(e);
			}
			this.busy = false;
		},
		async logIn() { await askLogin(); this.identity = currentIdentity(); await this.read(); },
		async logout() { await logout(); this.identity = currentIdentity(); await this.read(); }
	}
};
</script>
