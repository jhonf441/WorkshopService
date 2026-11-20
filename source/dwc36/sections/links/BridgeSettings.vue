<template>
	<!-- Bridge > settings: the port, whether one connection has the control, the greeting, the names of known IPs, the queries always allowed and the
	     time the debug stays on. Saved together with one button (the bridge picks the file up by itself); nothing is saved on change.
	     The settings file is read when the fold is opened. -->
	<div class="sv-bridge-settings">
		<p v-if="!config" class="sv-quiet" role="status">{{ tr('reading_settings') }}</p>
		<form v-else class="sv-form" @submit.prevent="save">
			<label class="sv-field-line"><span>{{ tr('port') }}</span><span class="sv-field"><input v-model.number="config.port" type="number" min="1" max="65535" :aria-label="tr('port')" :disabled="!mayEdit" :aria-invalid="portProblem ? 'true' : null"></span></label>
			<p v-if="portError" class="sv-field-error" role="alert">{{ errorText }}</p>
			<p v-else-if="hint" class="sv-hint" role="note" data-part="port-hint">{{ hint }}</p>
			<label class="sv-check"><input v-model="config.exclusive" type="checkbox" :disabled="!mayEdit"><span>{{ tr('a_single_connection_with_control') }}</span></label>
			<label class="sv-check"><input v-model="config.extended_greeting" type="checkbox" :disabled="!mayEdit"><span>{{ tr('greeting_with_help_on_connect') }}</span></label>
			<label class="sv-check"><input v-model="config.skip_material_macro" type="checkbox" :disabled="!mayEdit"><span>{{ tr('skip_material_gcode') }}</span></label>
			<p class="sv-hint">{{ tr('changing_the_port_does_not_cut') }} {{ tr('ports_below_1024_need') }} <code class="sv-code">install.sh</code>.</p>

			<span class="sv-label">{{ tr('names_by_ip') }}</span>
			<div v-for="(n, i) in names" :key="i" class="sv-row-ctl" data-part="name">
				<label class="sv-field"><span class="sv-vh">IP</span><input v-model.trim="n.ip" type="text" aria-label="IP" :disabled="!mayEdit"></label>
				<label class="sv-field"><span class="sv-vh">{{ tr('name_e_g_pc_workshop') }}</span><input v-model.trim="n.name" type="text" :placeholder="tr('name_e_g_pc_workshop')" :aria-label="tr('name_e_g_pc_workshop')" :disabled="!mayEdit"></label>
				<button type="button" class="sv-btn sv-text" data-act="delete-name" :aria-label="tr('delete_this_name')" :disabled="!mayEdit" @click="names.splice(i, 1)">{{ tr('delete_this_name') }}</button>
			</div>
			<div class="sv-row-ctl"><button type="button" class="sv-btn" data-act="add-name" :disabled="!mayEdit" @click="names.push({ ip: '', name: '' })">{{ tr('add_name') }}</button></div>

			<label class="sv-field-line"><span>{{ tr('queries_always_allowed_comma_separated') }}</span><span class="sv-field"><input v-model="queriesTxt" type="text" :aria-label="tr('queries_always_allowed_comma_separated')" :disabled="!mayEdit"></span></label>
			<p class="sv-hint">{{ tr('queries_go_through_even_if_someone') }}</p>
			<label class="sv-field-line"><span>{{ tr('minutes_until_debug_turns_itself_off') }}</span><span class="sv-field"><input v-model.number="config.debug_timeout_min" type="number" min="1" max="1440" :aria-label="tr('minutes_until_debug_turns_itself_off')" :disabled="!mayEdit"></span></label>
			<label class="sv-check"><input v-model="config.debug_renew" type="checkbox" :disabled="!mayEdit"><span>{{ tr('debug_renew_label') }}</span></label>
			<p class="sv-hint">{{ tr('debug_renew_help') }}</p>
			<div class="sv-fbar"><button type="submit" class="sv-btn sv-main" data-act="save-config" :disabled="!mayEdit || saving">{{ tr('save') }}</button><span class="sv-quiet">{{ t('data.settings_nothing') }}</span></div>
			<div v-if="note" class="sv-row-out" :data-kind="note.ok ? 'done' : 'error'" :role="note.ok ? 'status' : 'alert'" data-part="note"><span class="mdi sv-ico sv-ico-s" :class="note.ok ? 'mdi-check-circle-outline' : 'mdi-close-circle-outline'" aria-hidden="true" />{{ note.text }}</div>
		</form>
		<sv-reason :lock="lockOf(['bridge.service.set'])" @sign-in="signIn" />
	</div>
</template>

<script>
import { bridge, loadConfig, saveConfig } from '../../core/store/bridge.js'
import { rowsMixin } from '../../core/rows-mixin.js'
import { parsePortError, portHint } from '../../bridge-port.js'
import * as forms from '../../bridge-forms.js'
import SvReason from '../../ui/SvReason.vue'
import { tr } from './bridge-orders.js'

export default {
	name: 'BridgeSettings',
	components: { SvReason },
	mixins: [rowsMixin],
	data() {
		return { config: null, names: [], queriesTxt: '', saving: false, note: null }
	},
	computed: {
		mayEdit() {
			return this.perm('bridge.service.set').state === 'ok'
		},
		portError() {
			return bridge.e && bridge.e.error ? parsePortError(bridge.e.error) : null
		},
		errorText() {
			const pe = this.portError
			return pe ? tr('port_err_' + pe.kind, { port: pe.port, detail: pe.detail }) : ''
		},
		portProblem() {
			return !!this.config && !forms.validPort(Number(this.config.port))
		},
		hint() {
			const h = this.config ? portHint(this.config.port) : null
			if (!h) return ''
			return h.kind === 'usual' ? tr('port_hint_usual', { port: h.port, who: tr('port_who_' + h.who) }) : tr('port_hint_low', { port: h.port })
		}
	},
	methods: {
		tr,
		async open() {
			this.note = null
			const f = forms.configFrom(await loadConfig())
			this.config = f.config
			this.names = f.names
			this.queriesTxt = f.queriesTxt
		},
		async save() {
			const port = Number(this.config.port)
			if (!forms.validPort(port)) { this.note = { ok: false, text: tr('invalid_port_1_to_65535') }; return }
			this.saving = true
			try {
				await saveConfig(current => forms.applyConfig(current, this.config, port, this.names, this.queriesTxt))
				this.note = { ok: true, text: tr('saved_the_bridge_picks_it_up') }
			} catch (e) {
				this.note = { ok: false, text: this.t('common.could_not_save_x', { x: e.message }) }
			}
			this.saving = false
		}
	}
}
</script>
