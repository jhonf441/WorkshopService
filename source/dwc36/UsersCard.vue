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
				<sv-form-row>
					<sv-text-field v-model="first.name" :label="$t('plugins.WorkshopService.users.name')" autocomplete="username" />
					<sv-text-field v-model="first.pin" :type="showPins ? 'text' : 'password'" inputmode="numeric" :label="$t('plugins.WorkshopService.users.pin')" autocomplete="new-password">
						<template #append><button type="button" class="sv-field-btn" :aria-label="showPins ? $t('plugins.WorkshopService.users.hide_pin') : $t('plugins.WorkshopService.users.show_pin')" @click="showPins = !showPins"><span class="mdi" :class="showPins ? 'mdi-eye-off' : 'mdi-eye'" aria-hidden="true" /></button></template>
					</sv-text-field>
					<sv-text-field v-model="first.repeat" :type="showPins ? 'text' : 'password'" inputmode="numeric" :label="$t('plugins.WorkshopService.users.pin_repeat')" autocomplete="new-password" />
					<template #act><v-btn color="primary" :loading="busy" :disabled="!firstValid" @click="createFirst">{{ $t('plugins.WorkshopService.users.create_admin') }}</v-btn></template>
				</sv-form-row>
				<div v-if="first.pin && first.repeat && first.pin !== first.repeat" class="text-caption warning--text mt-1">{{ $t('plugins.WorkshopService.users.pins_differ') }}</div>
				<v-alert v-if="error" dense text type="error" class="mt-3 mb-0">{{ error }}</v-alert>
			</v-card-text>
		</v-card>

		<!-- the list of people is for administrators: without a session the cover offers to sign in; with a lower role it names the role -->
		<session-notice v-if="state.configured && !isAdmin" :kind="gateKind" variant="cover" needed="admin" class="mb-3" />

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
								<td><role-chip :role="u.role" :text="roleName(u.role)" /></td>
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

			<users-sessions :settings="state.settings" @changed="read" />
		</template>

		<!-- add / edit a person -->
		<v-dialog v-model="dlg" max-width="480" persistent @keydown.esc="closeForm" @click:outside="closeForm">
			<v-card>
				<v-card-title class="text-subtitle-1">{{ form.edit ? $t('plugins.WorkshopService.users.edit_title', { name: form.name }) : $t('plugins.WorkshopService.users.new_title') }}<sv-unsaved-mark :show="hasUnsaved" class="ml-3" /></v-card-title>
				<v-card-text>
					<v-text-field v-if="!form.edit" v-model="form.name" :label="$t('plugins.WorkshopService.users.name')" dense outlined counter="32" autocomplete="off" />
					<template v-if="!form.edit">
						<sv-form-row>
							<sv-text-field v-model="form.pin" :type="showPins ? 'text' : 'password'" inputmode="numeric" :label="$t('plugins.WorkshopService.users.pin')" autocomplete="new-password">
								<template #append><button type="button" class="sv-field-btn" :aria-label="showPins ? $t('plugins.WorkshopService.users.hide_pin') : $t('plugins.WorkshopService.users.show_pin')" @click="showPins = !showPins"><span class="mdi" :class="showPins ? 'mdi-eye-off' : 'mdi-eye'" aria-hidden="true" /></button></template>
							</sv-text-field>
							<sv-text-field v-model="form.repeat" :type="showPins ? 'text' : 'password'" inputmode="numeric" :label="$t('plugins.WorkshopService.users.pin_repeat')" autocomplete="new-password" />
						</sv-form-row>
						<div class="text-caption grey--text mt-1 mb-3">{{ $t('plugins.WorkshopService.users.pin_help', { min: state.min_pin, max: state.max_pin }) }}</div>
					</template>
					<sv-select v-model="form.role" :items="roleItems" :label="$t('plugins.WorkshopService.users.role')" :disabled="form.edit && isMe({ name: form.name })" />
					<div v-if="form.role === 'operator'">
						<div class="text-caption grey--text mb-1">{{ $t('plugins.WorkshopService.users.modes_help') }}</div>
						<div class="d-flex flex-wrap">
							<v-checkbox v-for="m in state.modes" :key="m" v-model="form.modes" :value="m" dense hide-details class="mr-4 mt-0" :label="modeName(m)" />
						</div>
					</div>
					<sv-toggle v-if="form.role === 'viewer'" v-model="form.camera" :label="$t('plugins.WorkshopService.users.camera_for_this')" />
					<v-alert v-if="formError" dense text type="error" class="mt-3 mb-0">{{ formError }}</v-alert>
				</v-card-text>
				<v-card-actions>
					<v-spacer />
					<v-btn text @click="closeForm">{{ $t('plugins.WorkshopService.common.cancel') }}</v-btn>
					<v-btn color="primary" :class="{ 'sv-save-hot': hasUnsaved }" :loading="busy" :disabled="!formValid" @click="saveForm">{{ $t('plugins.WorkshopService.users.save') }}</v-btn>
				</v-card-actions>
			</v-card>
		</v-dialog>

		<!-- PIN: reset one of a person, or change my own -->
		<v-dialog v-model="dlgPin" max-width="400" persistent @keydown.esc="closePin" @click:outside="closePin">
			<v-card>
				<v-card-title class="text-subtitle-1">{{ $t('plugins.WorkshopService.users.reset_title', { name: pinForm.name }) }}<sv-unsaved-mark :show="hasUnsaved" class="ml-3" /></v-card-title>
				<v-card-text>
					<sv-text-field v-model="pinForm.pin" :type="showPins ? 'text' : 'password'" inputmode="numeric" :label="$t('plugins.WorkshopService.users.new_pin')" autocomplete="new-password" class="mb-3">
						<template #append><button type="button" class="sv-field-btn" :aria-label="showPins ? $t('plugins.WorkshopService.users.hide_pin') : $t('plugins.WorkshopService.users.show_pin')" @click="showPins = !showPins"><span class="mdi" :class="showPins ? 'mdi-eye-off' : 'mdi-eye'" aria-hidden="true" /></button></template>
					</sv-text-field>
					<sv-text-field v-model="pinForm.repeat" :type="showPins ? 'text' : 'password'" inputmode="numeric" :label="$t('plugins.WorkshopService.users.pin_repeat')" autocomplete="new-password" />
					<div class="text-caption grey--text mt-2">{{ $t('plugins.WorkshopService.users.reset_help') }}</div>
					<v-alert v-if="formError" dense text type="error" class="mt-3 mb-0">{{ formError }}</v-alert>
				</v-card-text>
				<v-card-actions>
					<v-spacer />
					<v-btn text @click="closePin">{{ $t('plugins.WorkshopService.common.cancel') }}</v-btn>
					<v-btn color="primary" :class="{ 'sv-save-hot': hasUnsaved }" :loading="busy" :disabled="!pinValid" @click="savePin">{{ $t('plugins.WorkshopService.users.save') }}</v-btn>
				</v-card-actions>
			</v-card>
		</v-dialog>
	</div>
</template>

<script>
'use strict'

import SvTextField from './ui/SvTextField.vue'
import SvFormRow from './ui/SvFormRow.vue'
import SvSelect from './ui/SvSelect.vue'
import { api, adoptSession, currentIdentity, onIdentity, whoami } from './workshop-api.js'
import { signedOut } from './workshop-auth.js'
import { roleMixin } from './role-mixin.js'
import SvUnsavedMark from './ui/SvUnsavedMark.vue'
import { unsavedMixin } from './ui/unsaved-mixin.js'
import { snapshot } from './ui/unsaved-guard.js'
import SessionNotice from './SessionNotice.vue'
import RoleChip from './RoleChip.vue'
import UsersSessions from './UsersSessions.vue'
import SvToggle from './ui/SvToggle.vue'

const PIN_RE = /^[0-9]{4,12}$/;

function emptyForm() {
	return { edit: false, name: '', pin: '', repeat: '', role: 'operator', modes: ['laser'], camera: false };
}

export default {
	name: 'UsersCard',
	components: { SvTextField, SvFormRow, SvSelect, SessionNotice, RoleChip, UsersSessions, SvToggle, SvUnsavedMark },
	mixins: [roleMixin, unsavedMixin],
	// the people, the sessions and every open form or dialog came from the session that left (ESTANDAR 3.3): emptied on sign-out / change of role
	sessionData: ['state', 'showPins', 'first', 'form', 'dlg', 'pinForm', 'dlgPin', 'armed', 'busy', 'error', 'formError'],
	data() {
		return {
			state: { configured: null, users: [], settings: {}, roles: [], custom_roles: [], modes: [], min_pin: 4, max_pin: 12 },
			identity: currentIdentity(),
			showPins: false, first: { name: '', pin: '', repeat: '' },
			form: emptyForm(), dlg: false, formBase: null,
			pinForm: { name: '', pin: '', repeat: '' }, dlgPin: false, pinBase: null,
			armed: '', busy: false, error: '', formError: '', off: null
		};
	},
	computed: {
		me() { return this.identity && this.identity.user && this.identity.user.name ? this.identity.user : null; },
		gateKind() { void this.identityTick; return signedOut() ? 'session' : 'role'; },
		// one source of truth: the operation table of the service (users.list), as the rest of the page
		isAdmin() { return !!this.identity && this.canDo('users.list'); },
		roleItems() { return (this.state.roles || []).map(r => ({ value: r, text: this.roleName(r) })).concat((this.state.custom_roles || []).map(r => ({ value: r, text: r }))); },
		firstValid() { return !!this.first.name.trim() && PIN_RE.test(this.first.pin) && this.first.pin === this.first.repeat; },
		formValid() {
			const f = this.form;
			if (f.edit) return true;
			return !!f.name.trim() && PIN_RE.test(f.pin) && f.pin === f.repeat;
		},
		pinValid() {
			const p = this.pinForm;
			return PIN_RE.test(p.pin) && p.pin === p.repeat;
		}
	},
	created() { this._gen = 0; },
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
		// an answer of the old person that is still on its way must not fill the list again
		onSessionChange() { this._gen++; },
		// a custom role shows its own name (users.list sends custom_roles)
		roleName(r) { return (this.state.custom_roles || []).includes(r) ? r : this.$t('plugins.WorkshopService.users.role_' + r); },
		modeName(m) { return this.$t('plugins.WorkshopService.users.mode_' + m); },
		date(t) { try { return new Date(t * 1000).toLocaleString(this.$i18n.locale); } catch (e) { return String(t); } },
		isMe(u) { return !!this.me && this.me.name.toLowerCase() === String(u.name).toLowerCase(); },
		fail(e) { return e && e.code !== 'cancelled' ? (e.message || String(e)) : ''; },
		async read() {
			const gen = this._gen;
			const id = this.identity;
			if (id && id.configured === false) {
				this.state = Object.assign({}, this.state, { configured: false });
				return;
			}
			if (!id || !this.canDo('users.list')) {
				this.state = Object.assign({}, this.state, { configured: id ? !!id.configured : null });
				return;
			}
			try {
				const r = await api('users.list', {}, { noLogin: true });
				if (gen !== this._gen) return;
				this.state = r;
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
		// unsaved changes (unsaved-mixin.js): what was typed in the person dialog and in the PIN dialog, against how each one opened
		unsavedPair() {
			return [{ f: this.dlg ? this.form : null, p: this.dlgPin ? this.pinForm : null }, { f: this.dlg ? this.formBase : null, p: this.dlgPin ? this.pinBase : null }];
		},
		async saveBeforeLeaving() {
			if (this.dlg) {
				if (!this.formValid) return false;
				await this.saveForm();
				if (this.dlg) return false;
			}
			if (this.dlgPin) {
				if (!this.pinValid) return false;
				await this.savePin();
				if (this.dlgPin) return false;
			}
			return true;
		},
		discardUnsaved() { this.dlg = false; this.dlgPin = false; },
		// Cancel, Escape and a touch outside: out at once when nothing was typed, else the dialog of unsaved changes asks
		closeForm() { this.leaveWith(() => { this.dlg = false; }); },
		closePin() { this.leaveWith(() => { this.dlgPin = false; }); },
		openNew() { this.formError = ''; this.form = emptyForm(); this.formBase = snapshot(this.form); this.dlg = true; },
		openEdit(u) {
			this.formError = '';
			this.form = Object.assign(emptyForm(), { edit: true, name: u.name, role: u.role, modes: u.modes.slice(), camera: !!u.camera_for_viewer });
			this.formBase = snapshot(this.form);
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
		openReset(u) { this.formError = ''; this.pinForm = { name: u.name, pin: '', repeat: '' }; this.pinBase = snapshot(this.pinForm); this.dlgPin = true; },
		async savePin() {
			const p = this.pinForm;
			this.busy = true;
			this.formError = '';
			try {
				await api('users.reset_pin', { name: p.name, pin: p.pin });
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
		}
	}
};
</script>
