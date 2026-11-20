<template>
	<!-- Bridge > security and key: who may connect (the local network or chosen IPs), the key to send commands, the IPs trusted without a key and the
	     limits. The limits are saved together with one button, nothing on change; key and trust are orders to the bridge. -->
	<div class="sv-bridge-safety">
		<div class="sv-note sv-note-long" data-level="info" role="note" data-part="telnet-note">
			<span class="mdi mdi-information-outline sv-ico" aria-hidden="true" />
			<div class="sv-note-body">
				<b>{{ t('links.note_short') }}</b>
				<details class="sv-note-more"><summary>{{ t('links.note_more') }}</summary><p>{{ tr('telnet_encrypts_nothing') }} <b>{{ tr('do_not_open_this_port_to') }}</b></p></details>
			</div>
		</div>

		<!-- the whole at a glance: who may connect, the key, the trusted IPs -->
		<ul class="sv-tiles" data-part="glance">
			<li class="sv-tile" data-level="ok"><span class="mdi mdi-lan sv-ico" aria-hidden="true" /><span class="sv-tile-k">{{ t('links.tile_who') }}</span><b class="sv-tile-v">{{ t(form.modeIp === 'list' ? 'links.tile_who_list' : 'links.tile_who_local') }}</b></li>
			<li class="sv-tile" :data-level="sec.password ? 'ok' : 'rest'"><span class="mdi sv-ico" :class="sec.password ? 'mdi-key-variant' : 'mdi-key-remove'" aria-hidden="true" /><span class="sv-tile-k">{{ t('links.tile_key') }}</span><b class="sv-tile-v">{{ t(sec.password ? 'links.tile_key_on' : 'links.tile_key_off') }}</b></li>
			<li class="sv-tile" :data-level="sec.trusted.length ? 'info' : 'rest'"><span class="mdi mdi-shield-check-outline sv-ico" aria-hidden="true" /><span class="sv-tile-k">{{ t('links.tile_trust') }}</span><b class="sv-tile-v">{{ sec.trusted.length ? tc('links.tile_trust_n', sec.trusted.length) : t('links.tile_trust_none') }}</b></li>
		</ul>

		<section class="sv-panel" data-part="who" aria-labelledby="sv-bs-who">
			<h3 id="sv-bs-who" class="sv-panel-title">{{ tr('who_can_connect') }}</h3>
			<div class="sv-choices" role="radiogroup" :aria-labelledby="'sv-bs-who'">
				<label class="sv-choice" :class="{ 'sv-on': form.modeIp === 'local' }"><input v-model="form.modeIp" type="radio" value="local" :disabled="!mayOrder"><span><b>{{ tr('only_my_local_network_recommended') }}</b><small>{{ t('links.choice_local_desc') }}</small></span></label>
				<label class="sv-choice" :class="{ 'sv-on': form.modeIp === 'list' }"><input v-model="form.modeIp" type="radio" value="list" :disabled="!mayOrder"><span><b>{{ tr('only_these_ips_or_networks') }}</b><small>{{ t('links.choice_list_desc') }}</small></span></label>
			</div>
			<label v-if="form.modeIp === 'list'" class="sv-field"><span class="sv-vh">{{ tr('ips_or_networks_enter_to_add') }}</span><input v-model="allowedText" type="text" :placeholder="tr('ips_or_networks_enter_to_add')" :aria-label="tr('ips_or_networks_enter_to_add')" :disabled="!mayOrder"></label>
			<p class="sv-hint">{{ tr('connections_from_other_ips_are_cut') }}</p>
		</section>

		<section class="sv-panel" data-part="key" aria-labelledby="sv-bs-key">
			<h3 id="sv-bs-key" class="sv-panel-title">{{ tr('key_to_send_commands') }} <span class="sv-word" :data-level="sec.password ? 'ok' : 'rest'">{{ tr(sec.password ? 'enabled' : 'no_key') }}</span></h3>
			<div class="sv-row-ctl">
				<label class="sv-field"><span class="sv-vh">{{ tr(sec.password ? 'new_key' : 'key_min_4_characters') }}</span><input v-model="keyNew" :type="viewKey ? 'text' : 'password'" autocomplete="new-password" :placeholder="tr(sec.password ? 'new_key' : 'key_min_4_characters')" :aria-label="tr(sec.password ? 'new_key' : 'key_min_4_characters')" :disabled="!mayOrder"></label>
				<button type="button" class="sv-btn sv-text" data-act="view-key" :aria-pressed="viewKey ? 'true' : 'false'" @click="viewKey = !viewKey"><span class="mdi sv-ico sv-ico-s" :class="viewKey ? 'mdi-eye-off-outline' : 'mdi-eye-outline'" aria-hidden="true" />{{ t(viewKey ? 'session.pin_hide' : 'session.pin_show') }}</button>
				<button type="button" class="sv-btn sv-main" data-act="put-key" :disabled="!mayOrder || keyNew.length < 4 || busy('key')" @click="putKey">{{ tr(sec.password ? 'change_key' : 'enable_key') }}</button>
				<button v-if="sec.password" type="button" class="sv-btn sv-danger" data-act="remove-key" :disabled="!mayOrder || busy('remove')" @click="removeKey">{{ armed === 'remove-key' ? tr('sure_tap_again') : tr('remove_key') }}</button>
			</div>
			<p class="sv-hint">{{ tr('with_a_key_a_new_connection') }} <code class="sv-code">BRIDGE KEY &lt;password&gt;</code>. {{ tr('stored_encrypted_salted_sha256') }}<template v-if="!sec.trusted.length"> {{ tr('before_enabling_it_mark_the_program') }}</template></p>
		</section>

		<section class="sv-panel" data-part="trust" aria-labelledby="sv-bs-trust">
			<h3 id="sv-bs-trust" class="sv-panel-title">{{ tr('trusted_ips_send_commands_without_a') }}</h3>
			<p class="sv-hint">{{ t('links.panel_trust_desc') }}</p>
			<ul v-if="sec.trusted.length" class="sv-rows">
				<li v-for="ip in sec.trusted" :key="ip" class="sv-row" :data-trusted="ip"><div class="sv-row-main"><div><div class="sv-row-name">{{ ip }}<template v-if="nameOf(ip)"> ({{ nameOf(ip) }})</template></div></div></div>
					<div class="sv-row-ctl"><button type="button" class="sv-btn sv-text" data-act="untrust" :aria-label="tr('remove_trust') + ': ' + ip" :disabled="!mayOrder || busy('conf-' + ip)" @click="order({ action: 'trust', ip: ip, yes: false }, 'conf-' + ip)">{{ tr('remove_trust') }}</button></div></li>
			</ul>
			<p v-else class="sv-quiet">{{ tr('none_f') }}</p>
			<div v-for="cl in pending" :key="'add' + cl.ip" class="sv-row-ctl"><button type="button" class="sv-btn" data-act="trust-client" :disabled="!mayOrder || busy('conf-' + cl.ip)" @click="order({ action: 'trust', ip: cl.ip, yes: true }, 'conf-' + cl.ip)">{{ tr('trust_this_ip') }}: {{ cl.name }} ({{ cl.ip }})</button></div>
			<div class="sv-row-ctl">
				<label class="sv-field"><span class="sv-vh">{{ tr('trust_add_label') }}</span><input v-model="trustNew" type="text" placeholder="192.0.2.16" autocomplete="off" :aria-label="tr('trust_add_label')" :aria-invalid="trustNew && !trustValid ? 'true' : null" :disabled="!mayOrder" @keyup.enter="addTrust"></label>
				<button type="button" class="sv-btn" data-act="trust-add" :disabled="!mayOrder || !trustValid || busy('trust-add')" @click="addTrust">{{ tr('trust_add_button') }}</button>
			</div>
			<p v-if="trustNew && !trustValid" class="sv-field-error" role="alert" data-part="trust-invalid"><span class="mdi mdi-alert-outline sv-ico sv-ico-s" aria-hidden="true" />{{ tr('trust_add_invalid') }}</p>
		</section>

		<form class="sv-panel" data-part="limits" aria-labelledby="sv-bs-limits" @submit.prevent="save">
			<h3 id="sv-bs-limits" class="sv-panel-title">{{ tr('limits') }}</h3>
			<p class="sv-hint">{{ t('links.panel_limits_desc') }}</p>
			<label v-for="f in LIMITS" :key="f.id" class="sv-field-line"><span>{{ tr(f.label) }}</span><span class="sv-field"><input v-model.number="form[f.id]" type="number" :min="f.min" :max="f.max" :aria-label="tr(f.label)" :disabled="!mayOrder"></span></label>
			<label class="sv-check"><input v-model="form.queries_in_job" type="checkbox" :disabled="!mayOrder"><span>{{ tr('position_queries_in_job') }}</span></label>
			<div class="sv-fbar"><button type="submit" class="sv-btn sv-main" data-act="save-safety" :disabled="!mayOrder || saving">{{ tr('save') }}</button><span class="sv-quiet">{{ t('data.settings_nothing') }}</span></div>
			<div v-if="note" class="sv-row-out" :data-kind="note.ok ? 'done' : 'error'" :role="note.ok ? 'status' : 'alert'" data-part="note"><span class="mdi sv-ico sv-ico-s" :class="note.ok ? 'mdi-check-circle-outline' : 'mdi-close-circle-outline'" aria-hidden="true" />{{ note.text }}</div>
		</form>
		<sv-reason :lock="lockOf(['bridge.service.set'])" @sign-in="signIn" />
	</div>
</template>

<script>
import { bridge, loadConfig, saveConfig } from '../../core/store/bridge.js'
import { rowsMixin } from '../../core/rows-mixin.js'
import { clientsToTrust, isTrustValid } from '../../bridge-view.js'
import * as forms from '../../bridge-forms.js'
import SvReason from '../../ui/SvReason.vue'
import { bridgeOrders, tr } from './bridge-orders.js'

const LIMITS = Object.freeze([
	{ id: 'max_connections', label: 'connections_at_once', min: 1, max: 50 }, { id: 'attempts_key', label: 'wrong_keys_before_blocking', min: 1, max: 50 },
	{ id: 'block_min', label: 'block_minutes', min: 1, max: 1440 }, { id: 'wait_order', label: 'order_wait_seconds', min: 1, max: 300 }
])

export default {
	name: 'BridgeSafety',
	components: { SvReason },
	mixins: [rowsMixin, bridgeOrders],
	data() {
		return { LIMITS, form: forms.secFormFrom({}), allowedText: '', keyNew: '', viewKey: false, trustNew: '', saving: false, note: null }
	},
	computed: {
		e() {
			return bridge.e
		},
		sec() {
			return this.e.security
		},
		mayOrder() {
			return this.perm('bridge.service.set').state === 'ok'
		},
		pending() {
			return clientsToTrust(this.e, this.sec)
		},
		trustValid() {
			return isTrustValid(this.trustNew)
		}
	},
	watch: {
		allowedText(v) { this.form.allowed = v.split(/[\s,]+/).filter(Boolean) }
	},
	created() {
		this.loadForm()
	},
	methods: {
		async loadForm() {
			this.form = forms.secFormFrom(await loadConfig())
			this.allowedText = this.form.allowed.join(', ')
		},
		nameOf(ip) {
			const cl = this.e.clients.find(x => x.ip === ip)
			return cl ? cl.name : ''
		},
		putKey() {
			const key = this.keyNew
			this.keyNew = ''
			this.order({ action: 'set_password', password: key }, 'key')
		},
		removeKey() {
			if (this.touch('remove-key')) this.order({ action: 'clear_password' }, 'remove')
		},
		addTrust() {
			if (!this.trustValid) return
			const ip = this.trustNew.trim()
			this.trustNew = ''
			this.order({ action: 'trust', ip, yes: true }, 'trust-add')
		},
		async save() {
			const check = forms.checkSecurity(this.form)
			if (check.error) { this.note = { ok: false, text: tr(check.error.key, check.error.params) }; return }
			const owner = this.e.clients.find(cl => cl.control)
			this.saving = true
			try {
				await saveConfig(current => forms.applySecurity(current, this.form, check.allowed))
				this.note = { ok: true, text: tr('saved_the_bridge_applies_it_within') + (owner && check.allowed.length ? tr('check_that_ip_stays_allowed', { ip: owner.ip, name: owner.name }) : '') }
			} catch (e) {
				this.note = { ok: false, text: this.t('common.could_not_save_x', { x: e.message }) }
			}
			this.saving = false
		}
	}
}
</script>
