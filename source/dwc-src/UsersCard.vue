<template>
	<div>
		<!-- No user yet: everybody with access to DWC is an administrator (compatibility). Wizard for the first one. -->
		<!-- The roles are switched off but the people are saved: anybody with access to DWC is an administrator until they are switched on again. -->
		<v-card v-if="identity && identity.users_disabled" class="mb-3">
			<v-card-title>
				<v-icon size="small" class="mr-2" color="warning">mdi-account-off-outline</v-icon>{{ $t('plugins.WorkshopService.users.disabled_title') }}
			</v-card-title>
			<v-card-text>
				<div class="text-body-medium mb-3">{{ $t('plugins.WorkshopService.users.disabled_help') }}</div>
				<v-btn size="small" color="primary" :loading="busy" @click="switchOn">{{ $t('plugins.WorkshopService.users.switch_on') }}</v-btn>
				<v-alert v-if="error" density="compact" variant="tonal" type="error" class="mt-3 mb-0">{{ error }}</v-alert>
			</v-card-text>
		</v-card>

		<v-card v-else-if="state.configured === false" class="mb-3">
			<v-card-title>
				<v-icon size="small" class="mr-2" color="warning">mdi-account-alert-outline</v-icon>{{ $t('plugins.WorkshopService.users.no_users_title') }}
			</v-card-title>
			<v-card-text>
				<v-alert density="compact" variant="tonal" type="warning" class="mb-3">{{ $t('plugins.WorkshopService.users.no_users_notice') }}</v-alert>
				<div class="text-body-medium mb-3">{{ $t('plugins.WorkshopService.users.wizard_help') }}</div>
				<v-row density="compact">
					<v-col cols="12" sm="4"><v-text-field v-model="first.name" :label="$t('plugins.WorkshopService.users.name')" density="compact" variant="outlined" hide-details autocomplete="username" /></v-col>
					<v-col cols="6" sm="3"><v-text-field :append-inner-icon="showPins ? 'mdi-eye-off' : 'mdi-eye'" @click:append-inner="showPins = !showPins" v-model="first.pin" :type="showPins ? 'text' : 'password'" inputmode="numeric" :label="$t('plugins.WorkshopService.users.pin')" density="compact" variant="outlined" hide-details autocomplete="new-password" /></v-col>
					<v-col cols="6" sm="3"><v-text-field v-model="first.repeat" :type="showPins ? 'text' : 'password'" inputmode="numeric" :label="$t('plugins.WorkshopService.users.pin_repeat')" density="compact" variant="outlined" hide-details autocomplete="new-password" /></v-col>
					<v-col cols="12" sm="2" class="d-flex align-center">
						<v-btn size="small" block color="primary" :loading="busy" :disabled="!firstValid" @click="createFirst">{{ $t('plugins.WorkshopService.users.create_admin') }}</v-btn>
					</v-col>
				</v-row>
				<div v-if="first.pin && first.repeat && first.pin !== first.repeat" class="text-body-small text-warning mt-1">{{ $t('plugins.WorkshopService.users.pins_differ') }}</div>
				<v-alert v-if="error" density="compact" variant="tonal" type="error" class="mt-3 mb-0">{{ error }}</v-alert>
			</v-card-text>
		</v-card>

		<!-- My session -->
		<v-card v-if="state.configured" class="mb-3">
			<v-card-title>
				<v-icon size="small" class="mr-2 svx-ico">mdi-account-circle-outline</v-icon>{{ $t('plugins.WorkshopService.users.my_session') }}
			</v-card-title>
			<v-card-text class="d-flex align-center flex-wrap" style="gap:8px">
				<template v-if="me && me.name">
					<strong>{{ me.name }}</strong>
					<v-chip size="small" variant="outlined" :color="roleColor(me.role)">{{ roleName(me.role) }}</v-chip>
					<v-spacer />
					<v-btn size="small" variant="outlined" @click="openPin"><v-icon start size="small">mdi-form-textbox-password</v-icon>{{ $t('plugins.WorkshopService.users.change_my_pin') }}</v-btn>
					<v-btn size="small" variant="outlined" @click="doLogout"><v-icon start size="small">mdi-logout</v-icon>{{ $t('plugins.WorkshopService.users.log_out') }}</v-btn>
				</template>
				<template v-else>
					<span class="text-body-medium text-medium-emphasis">{{ $t('plugins.WorkshopService.users.not_identified') }}</span>
					<v-spacer />
					<v-btn size="small" color="primary" @click="logIn"><v-icon start size="small">mdi-login</v-icon>{{ $t('plugins.WorkshopService.users.log_in') }}</v-btn>
				</template>
			</v-card-text>
		</v-card>

		<v-alert v-if="state.configured && !isAdmin" density="compact" variant="tonal" type="info" class="mb-3">{{ $t('plugins.WorkshopService.users.admin_only') }}</v-alert>

		<template v-if="state.configured && isAdmin">
			<!-- People -->
			<v-card class="mb-3">
				<v-card-title>
					<v-icon size="small" class="mr-2 svx-ico">mdi-account-group-outline</v-icon>{{ $t('plugins.WorkshopService.users.title') }}
					<v-spacer />
					<v-btn size="small" color="primary" @click="openNew"><v-icon start size="small">mdi-plus</v-icon>{{ $t('plugins.WorkshopService.users.add') }}</v-btn>
				</v-card-title>
				<v-card-text>
					<div class="text-body-small text-medium-emphasis mb-2">{{ $t('plugins.WorkshopService.users.help') }}</div>
					<v-alert v-if="error" density="compact" variant="tonal" type="error" class="mb-2">{{ error }}</v-alert>
					<v-table density="compact">
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
								<td><v-chip size="x-small" label :color="roleColor(u.role)" variant="flat">{{ roleName(u.role) }}</v-chip></td>
								<td>
									<span v-if="u.role === 'operator'">
										<v-chip v-for="m in u.modes" :key="m" size="x-small" label variant="outlined" class="mr-1">{{ modeName(m) }}</v-chip>
										<span v-if="!u.modes.length" class="text-body-small text-medium-emphasis">{{ $t('plugins.WorkshopService.users.no_modes') }}</span>
									</span>
									<span v-else class="text-body-small text-medium-emphasis">{{ u.role === 'viewer' ? '-' : $t('plugins.WorkshopService.users.all_modes') }}</span>
								</td>
								<td>
									<v-icon v-if="u.role === 'viewer'" size="small" :color="u.camera_for_viewer || state.settings.camera_for_viewer ? 'success' : 'grey'">{{ u.camera_for_viewer || state.settings.camera_for_viewer ? 'mdi-video' : 'mdi-video-off' }}</v-icon>
									<span v-else class="text-body-small text-medium-emphasis">-</span>
								</td>
								<td class="text-body-small">{{ u.last_seen ? date(u.last_seen) : $t('plugins.WorkshopService.users.never') }}</td>
								<td class="text-right" style="white-space:nowrap">
									<v-btn variant="text" icon size="small" :title="$t('plugins.WorkshopService.users.edit')" @click="openEdit(u)"><v-icon size="small">mdi-pencil</v-icon></v-btn>
									<v-btn variant="text" icon size="small" :title="$t('plugins.WorkshopService.users.reset_pin')" @click="openReset(u)"><v-icon size="small">mdi-form-textbox-password</v-icon></v-btn>
									<v-btn variant="text" icon size="small" :color="armed === u.name ? 'error' : null" :disabled="isMe(u)" :title="armed === u.name ? $t('plugins.WorkshopService.users.tap_again_remove') : $t('plugins.WorkshopService.users.remove')" @click="remove(u)">
										<v-icon size="small">mdi-delete</v-icon>
									</v-btn>
								</td>
							</tr>
						</tbody>
					</v-table>
				</v-card-text>
			</v-card>

			<!-- Sessions -->
			<v-card class="mb-3">
				<v-card-title>
					<v-icon size="small" class="mr-2 svx-ico">mdi-timer-outline</v-icon>{{ $t('plugins.WorkshopService.users.sessions_title') }}
				</v-card-title>
				<v-card-text>
					<v-row density="compact">
						<v-col cols="12"><v-switch v-model="cfg.never_expires" density="compact" hide-details :label="$t('plugins.WorkshopService.users.never_expires')" /><div class="text-body-small text-medium-emphasis">{{ $t('plugins.WorkshopService.users.never_expires_help') }}</div></v-col>
						<v-col cols="6" sm="3"><v-text-field v-model.number="cfg.idle_minutes" type="number" min="1" max="1440" :disabled="!!cfg.never_expires" :label="$t('plugins.WorkshopService.users.idle_minutes')" density="compact" variant="outlined" hide-details /></v-col>
						<v-col cols="6" sm="3"><v-text-field v-model.number="cfg.max_hours" type="number" min="1" max="168" :disabled="!!cfg.never_expires" :label="$t('plugins.WorkshopService.users.max_hours')" density="compact" variant="outlined" hide-details /></v-col>
					</v-row>
					<v-switch v-model="cfg.camera_for_viewer" density="compact" hide-details :label="$t('plugins.WorkshopService.users.camera_for_viewers')" class="mt-3" />
					<div class="text-body-small text-medium-emphasis mb-2">{{ $t('plugins.WorkshopService.users.camera_for_viewers_help') }}</div>
					<v-switch v-model="cfg.anonymous_viewer" density="compact" hide-details :label="$t('plugins.WorkshopService.users.anonymous_viewer')" />
					<div class="text-body-small text-medium-emphasis mb-2">{{ $t('plugins.WorkshopService.users.anonymous_viewer_help') }}</div>
					<v-btn size="small" color="primary" :loading="busy" @click="saveSettings">{{ $t('plugins.WorkshopService.users.save') }}</v-btn>
					<span v-if="msg" class="text-body-small ml-3">{{ msg }}</span>
					<v-divider class="my-4" />
					<div class="text-body-medium font-weight-medium">{{ $t('plugins.WorkshopService.users.off_title') }}</div>
					<div class="text-body-small text-medium-emphasis mb-2">{{ $t('plugins.WorkshopService.users.off_help') }}</div>
					<v-btn size="small" variant="outlined" color="warning" @click="offPin = ''; offError = ''; dlgOff = true">{{ $t('plugins.WorkshopService.users.off_button') }}</v-btn>
				</v-card-text>
			</v-card>
			<v-dialog v-model="dlgOff" max-width="400">
				<v-card>
					<v-card-title class="text-title-medium">{{ $t('plugins.WorkshopService.users.off_dialog_title') }}</v-card-title>
					<v-card-text>
						<div class="text-body-medium mb-3">{{ $t('plugins.WorkshopService.users.off_dialog_help') }}</div>
						<v-text-field v-model="offPin" type="password" inputmode="numeric" :label="$t('plugins.WorkshopService.users.pin')" density="compact" variant="outlined" autocomplete="current-password" @keyup.enter="switchOff" />
						<v-alert v-if="offError" density="compact" variant="tonal" type="error" class="mb-0">{{ offError }}</v-alert>
					</v-card-text>
					<v-card-actions>
						<v-spacer />
						<v-btn variant="text" @click="dlgOff = false">{{ $t('plugins.WorkshopService.common.cancel') }}</v-btn>
						<v-btn color="warning" :loading="busy" :disabled="!offPin" @click="switchOff">{{ $t('plugins.WorkshopService.users.off_confirm') }}</v-btn>
					</v-card-actions>
				</v-card>
			</v-dialog>
		</template>

		<!-- add / edit a person -->
		<v-dialog v-model="dlg" max-width="480">
			<v-card>
				<v-card-title class="text-title-medium">{{ form.edit ? $t('plugins.WorkshopService.users.edit_title', { name: form.name }) : $t('plugins.WorkshopService.users.new_title') }}</v-card-title>
				<v-card-text>
					<v-text-field v-if="!form.edit" v-model="form.name" :label="$t('plugins.WorkshopService.users.name')" density="compact" variant="outlined" counter="32" autocomplete="off" />
					<template v-if="!form.edit">
						<v-row density="compact">
							<v-col cols="6"><v-text-field :append-inner-icon="showPins ? 'mdi-eye-off' : 'mdi-eye'" @click:append-inner="showPins = !showPins" v-model="form.pin" :type="showPins ? 'text' : 'password'" inputmode="numeric" :label="$t('plugins.WorkshopService.users.pin')" density="compact" variant="outlined" hide-details autocomplete="new-password" /></v-col>
							<v-col cols="6"><v-text-field v-model="form.repeat" :type="showPins ? 'text' : 'password'" inputmode="numeric" :label="$t('plugins.WorkshopService.users.pin_repeat')" density="compact" variant="outlined" hide-details autocomplete="new-password" /></v-col>
						</v-row>
						<div class="text-body-small text-medium-emphasis mt-1 mb-3">{{ $t('plugins.WorkshopService.users.pin_help', { min: state.min_pin, max: state.max_pin }) }}</div>
					</template>
					<v-select v-model="form.role" :items="roleItems" item-title="text" item-value="value" :label="$t('plugins.WorkshopService.users.role')" density="compact" variant="outlined" :disabled="form.edit && isMe({ name: form.name })" />
					<div v-if="form.role === 'operator'">
						<div class="text-body-small text-medium-emphasis mb-1">{{ $t('plugins.WorkshopService.users.modes_help') }}</div>
						<div class="d-flex flex-wrap">
							<v-checkbox v-for="m in state.modes" :key="m" v-model="form.modes" :value="m" density="compact" hide-details class="mr-4 mt-0" :label="modeName(m)" />
						</div>
					</div>
					<v-switch v-if="form.role === 'viewer'" v-model="form.camera" density="compact" hide-details :label="$t('plugins.WorkshopService.users.camera_for_this')" />
					<v-alert v-if="formError" density="compact" variant="tonal" type="error" class="mt-3 mb-0">{{ formError }}</v-alert>
				</v-card-text>
				<v-card-actions>
					<v-spacer />
					<v-btn variant="text" @click="dlg = false">{{ $t('plugins.WorkshopService.common.cancel') }}</v-btn>
					<v-btn color="primary" :loading="busy" :disabled="!formValid" @click="saveForm">{{ $t('plugins.WorkshopService.users.save') }}</v-btn>
				</v-card-actions>
			</v-card>
		</v-dialog>

		<!-- PIN: reset one of a person, or change my own -->
		<v-dialog v-model="dlgPin" max-width="400">
			<v-card>
				<v-card-title class="text-title-medium">{{ pinForm.own ? $t('plugins.WorkshopService.users.change_my_pin') : $t('plugins.WorkshopService.users.reset_title', { name: pinForm.name }) }}</v-card-title>
				<v-card-text>
					<v-text-field v-if="pinForm.own" v-model="pinForm.old" type="password" inputmode="numeric" :label="$t('plugins.WorkshopService.users.old_pin')" density="compact" variant="outlined" autocomplete="current-password" />
					<v-text-field :append-inner-icon="showPins ? 'mdi-eye-off' : 'mdi-eye'" @click:append-inner="showPins = !showPins" v-model="pinForm.pin" :type="showPins ? 'text' : 'password'" inputmode="numeric" :label="$t('plugins.WorkshopService.users.new_pin')" density="compact" variant="outlined" autocomplete="new-password" />
					<v-text-field v-model="pinForm.repeat" :type="showPins ? 'text' : 'password'" inputmode="numeric" :label="$t('plugins.WorkshopService.users.pin_repeat')" density="compact" variant="outlined" hide-details autocomplete="new-password" />
					<div v-if="!pinForm.own" class="text-body-small text-medium-emphasis mt-2">{{ $t('plugins.WorkshopService.users.reset_help') }}</div>
					<v-alert v-if="formError" density="compact" variant="tonal" type="error" class="mt-3 mb-0">{{ formError }}</v-alert>
				</v-card-text>
				<v-card-actions>
					<v-spacer />
					<v-btn variant="text" @click="dlgPin = false">{{ $t('plugins.WorkshopService.common.cancel') }}</v-btn>
					<v-btn color="primary" :loading="busy" :disabled="!pinValid" @click="savePin">{{ $t('plugins.WorkshopService.users.save') }}</v-btn>
				</v-card-actions>
			</v-card>
		</v-dialog>
	</div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { i18n } from './dwc-host.js'
import { api, adoptSession, askLogin, changePin, currentIdentity, logout, onIdentity, whoami } from './workshop-api.js'

const ROLE_COLORS = { viewer: 'blue-grey', operator: 'primary', technician: 'amber-darken-3', admin: 'error' }
const PIN_RE = /^[0-9]{4,12}$/

function emptyForm() {
	return { edit: false, name: '', pin: '', repeat: '', role: 'operator', modes: ['laser'], camera: false }
}

const state = ref({ configured: null, users: [], settings: {}, roles: [], modes: [], min_pin: 4, max_pin: 12 })
const cfg = ref({ idle_minutes: 720, max_hours: 12, never_expires: false, camera_for_viewer: false, anonymous_viewer: false })
const identity = ref(currentIdentity())
const showPins = ref(false)
const dlgOff = ref(false)
const offPin = ref('')
const offError = ref('')
const first = ref({ name: '', pin: '', repeat: '' })
const form = ref(emptyForm())
const dlg = ref(false)
const pinForm = ref({ own: false, name: '', old: '', pin: '', repeat: '' })
const dlgPin = ref(false)
const armed = ref('')
const busy = ref(false)
const error = ref('')
const formError = ref('')
const msg = ref('')
let off = null

const me = computed(() => identity.value && identity.value.user && identity.value.user.name ? identity.value.user : null)
const isAdmin = computed(() => !!identity.value && identity.value.role === 'admin')
const roleItems = computed(() => (state.value.roles || []).map(r => ({ value: r, text: roleName(r) })))
const firstValid = computed(() => !!first.value.name.trim() && PIN_RE.test(first.value.pin) && first.value.pin === first.value.repeat)
const formValid = computed(() => {
	const f = form.value
	if (f.edit) return true
	return !!f.name.trim() && PIN_RE.test(f.pin) && f.pin === f.repeat
})
const pinValid = computed(() => {
	const p = pinForm.value
	return PIN_RE.test(p.pin) && p.pin === p.repeat && (!p.own || !!p.old)
})

// the PINs are hidden again whenever a dialog closes
watch(dlg, open => { if (!open) showPins.value = false })
watch(dlgPin, open => { if (!open) showPins.value = false })

onMounted(async () => {
	off = onIdentity(i => { identity.value = i; read() })
	await whoami().catch(() => null)
	identity.value = currentIdentity()
	await read()
})
onBeforeUnmount(() => { if (off) off() })

function roleName(r) { return i18n.t('plugins.WorkshopService.users.role_' + r) }
function modeName(m) { return i18n.t('plugins.WorkshopService.users.mode_' + m) }
function roleColor(r) { return ROLE_COLORS[r] || 'grey' }
function date(t) { try { return new Date(t * 1000).toLocaleString(i18n.locale) } catch (e) { return String(t) } }
function isMe(u) { return !!me.value && me.value.name.toLowerCase() === String(u.name).toLowerCase() }
function fail(e) { return e && e.code !== 'cancelled' ? (e.message || String(e)) : '' }
async function read() {
	const id = identity.value
	if (id && id.configured === false) {
		state.value = Object.assign({}, state.value, { configured: false })
		return
	}
	if (!id || id.role !== 'admin') {
		state.value = Object.assign({}, state.value, { configured: id ? !!id.configured : null })
		return
	}
	try {
		const r = await api('users.list', {}, { noLogin: true })
		state.value = r
		Object.assign(cfg.value, r.settings)
		error.value = ''
	} catch (e) {
		error.value = fail(e)
	}
}
async function createFirst() {
	busy.value = true
	error.value = ''
	try {
		const r = await api('users.add', { name: first.value.name.trim(), pin: first.value.pin, role: 'admin' })
		await adoptSession(r.token) // whoever creates the first administrator is that administrator from now on
		first.value = { name: '', pin: '', repeat: '' }
		identity.value = currentIdentity()
		await read()
	} catch (e) {
		error.value = fail(e)
	}
	busy.value = false
}
async function switchOff() {
	if (!offPin.value) return
	busy.value = true
	offError.value = ''
	try {
		await api('users.enable', { enabled: false, pin: offPin.value }, { noLogin: true })
		offPin.value = ''
		dlgOff.value = false
		await whoami() // the sessions ended: the page is in compatibility mode now
	} catch (e) {
		offError.value = fail(e)
	}
	busy.value = false
}
async function switchOn() {
	busy.value = true
	error.value = ''
	try {
		await api('users.enable', { enabled: true })
		await whoami() // the roles are on again: this browser has to log in
	} catch (e) {
		error.value = fail(e)
	}
	busy.value = false
}
function openNew() { formError.value = ''; form.value = emptyForm(); dlg.value = true }
function openEdit(u) {
	formError.value = ''
	form.value = Object.assign(emptyForm(), { edit: true, name: u.name, role: u.role, modes: u.modes.slice(), camera: !!u.camera_for_viewer })
	dlg.value = true
}
async function saveForm() {
	const f = form.value
	busy.value = true
	formError.value = ''
	try {
		const extra = { modes: f.role === 'operator' ? f.modes : [], camera_for_viewer: f.role === 'viewer' && f.camera }
		if (f.edit) await api('users.set', Object.assign({ name: f.name, role: f.role }, extra))
		else await api('users.add', Object.assign({ name: f.name.trim(), pin: f.pin, role: f.role }, extra))
		dlg.value = false
		await read()
	} catch (e) {
		formError.value = fail(e)
	}
	busy.value = false
}
function openReset(u) { formError.value = ''; pinForm.value = { own: false, name: u.name, old: '', pin: '', repeat: '' }; dlgPin.value = true }
function openPin() { formError.value = ''; pinForm.value = { own: true, name: me.value.name, old: '', pin: '', repeat: '' }; dlgPin.value = true }
async function savePin() {
	const p = pinForm.value
	busy.value = true
	formError.value = ''
	try {
		if (p.own) await changePin(p.old, p.pin)
		else await api('users.reset_pin', { name: p.name, pin: p.pin })
		dlgPin.value = false
		await read()
	} catch (e) {
		formError.value = fail(e)
	}
	busy.value = false
}
async function remove(u) {
	if (armed.value !== u.name) {
		armed.value = u.name
		setTimeout(() => { if (armed.value === u.name) armed.value = '' }, 4000)
		return
	}
	armed.value = ''
	try {
		await api('users.remove', { name: u.name })
		await read()
	} catch (e) {
		error.value = fail(e)
	}
}
async function saveSettings() {
	busy.value = true
	msg.value = ''
	try {
		const c = cfg.value
		const r = await api('users.settings', { idle_minutes: Number(c.idle_minutes), max_hours: Number(c.max_hours), never_expires: !!c.never_expires, camera_for_viewer: !!c.camera_for_viewer, anonymous_viewer: !!c.anonymous_viewer })
		Object.assign(cfg.value, r.settings)
		msg.value = i18n.t('plugins.WorkshopService.users.saved')
		await read()
	} catch (e) {
		msg.value = fail(e)
	}
	busy.value = false
}
async function logIn() { await askLogin(); identity.value = currentIdentity(); await read() }
async function doLogout() { await logout(); identity.value = currentIdentity(); await read() }
</script>
