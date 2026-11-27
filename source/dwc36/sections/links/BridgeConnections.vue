<template>
	<!-- Bridge > who is connected: one row per connection with its role, its numbers and what can be done to it (give it control, trust its IP,
	     rename, kick, block). Kicking and blocking cut something, so they ask a second touch. Prop: host (the name of this Pi, for the hint). -->
	<div class="sv-bridge-clients">
		<!-- the state at a glance: how many are connected and where a program has to point -->
		<div class="sv-hero" :data-level="clients.length ? 'ok' : 'rest'" data-part="hero">
			<span class="mdi sv-ico sv-hero-ico" :class="clients.length ? 'mdi-lan-connect' : 'mdi-lan-disconnect'" aria-hidden="true" />
			<div class="sv-hero-main">
				<b class="sv-hero-v" role="status" data-part="nobody-or-n">{{ clients.length ? tc('links.conn_n', clients.length) : t('links.conn_none') }}</b>
				<span class="sv-hero-k">{{ t('links.conn_program') }}: {{ t('links.conn_device') }}</span>
			</div>
			<div class="sv-chips">
				<span class="sv-chip" data-part="host"><span class="mdi mdi-ip-network-outline sv-ico sv-ico-s" aria-hidden="true" />{{ t('links.conn_host') }} <code class="sv-code">{{ host }}</code></span>
				<span class="sv-chip" data-part="port"><span class="mdi mdi-ethernet sv-ico sv-ico-s" aria-hidden="true" />{{ t('links.conn_port') }} <code class="sv-code">{{ e.port }}</code></span>
			</div>
		</div>
		<ul v-if="clients.length" class="sv-rows">
			<li v-for="cl in clients" :key="cl.id" class="sv-row" :data-client="cl.id">
				<div class="sv-row-main">
					<span class="mdi sv-ico" :class="role(cl).icon" aria-hidden="true" />
					<div>
						<div v-if="editing === cl.id" class="sv-row-ctl" data-part="rename">
							<label class="sv-field"><span class="sv-vh">{{ t('links.bridge_rename') }}</span><input v-model.trim="nameNew" type="text" maxlength="40" :aria-label="t('links.bridge_rename')" @keyup.enter="rename(cl)" @keyup.esc="editing = null"></label>
							<label class="sv-check"><input v-model="remember" type="checkbox"><span>{{ tr('remember_for_ip', { ip: cl.ip }) }}</span></label>
							<button type="button" class="wf-btn sv-btn wf-main" data-act="rename-save" :disabled="!nameNew || busy('ren-' + cl.id)" @click="rename(cl)">{{ tr('save') }}</button>
							<button type="button" class="wf-btn sv-btn sv-text" @click="editing = null">{{ tr('cancel') }}</button>
						</div>
						<template v-else>
							<div class="sv-row-name">{{ cl.name }}<template v-if="cl.alias"> · {{ cl.alias }}</template> <button type="button" class="wf-btn sv-btn sv-text" data-act="rename" :aria-label="t('links.bridge_rename') + ': ' + cl.name" :disabled="!mayOrder" @click="beginRename(cl)"><span class="mdi mdi-pencil-outline sv-ico sv-ico-s" aria-hidden="true" /></button></div>
							<div class="sv-row-desc">{{ cl.id }} · {{ tr('connected_for_t', { t: dur(cl.connected_s) }) }} · {{ cl.idle_s > 5 ? tr('idle_for_t', { t: dur(cl.idle_s) }) : tr('active_now') }}</div>
						</template>
					</div>
				</div>
				<div class="sv-row-ctl">
					<span class="sv-word" :data-level="cl.control ? 'ok' : cl.role === 'no_password' ? 'warn' : 'rest'" data-part="role">{{ role(cl).text }}</span>
					<span v-if="cl.trusted" class="sv-tag">{{ tr('trusted') }}</span>
					<span v-if="cl.name_saved" class="sv-tag">{{ tr('saved_name') }}</span>
					<button v-if="!cl.control && e.exclusive" type="button" class="wf-btn sv-btn" data-act="give" :disabled="!mayOrder || busy('ctl-' + cl.id)" @click="order({ action: 'give_control', client: cl.id }, 'ctl-' + cl.id)">{{ tr('give_it_control') }}</button>
					<button v-if="cl.control" type="button" class="wf-btn sv-btn" data-act="release" :disabled="!mayOrder || busy('release')" @click="order({ action: 'release' }, 'release')">{{ t('common.release') }}</button>
					<button type="button" class="wf-btn sv-btn" data-act="trust" :disabled="!mayOrder || busy('conf-' + cl.ip)" @click="order({ action: 'trust', ip: cl.ip, yes: !cl.trusted }, 'conf-' + cl.ip)">{{ tr(cl.trusted ? 'remove_trust' : 'trust_this_ip') }}</button>
					<button type="button" class="wf-btn sv-btn wf-danger" :class="{ 'sv-armed': armed === 'exp-' + cl.id }" data-act="kick" :disabled="!mayOrder" @click="eject(cl)">{{ armed === 'exp-' + cl.id ? tr('sure_tap_again') : tr('kick') }}</button>
					<button type="button" class="wf-btn sv-btn wf-danger" :class="{ 'sv-armed': armed === 'blq-' + cl.ip }" data-act="block" :disabled="!mayOrder || busy('blq-' + cl.ip)" @click="block(cl)">{{ armed === 'blq-' + cl.ip ? tr('block_tap_again') : tr('block') }}</button>
				</div>
				<p class="sv-row-desc" data-part="numbers">{{ num(cl.orders) }} {{ tr('commands_lc') }} · {{ num(cl.queries) }} {{ tr('queries_lc') }} · <span :class="cl.rejects ? 'sv-field-error' : ''">{{ cl.rejects }} {{ tr('rejected_lc') }}</span> · {{ cl.cache_hits || 0 }} {{ tr('from_cache') }} {{ cl.coalesced || 0 }} {{ tr('shared_2') }} · {{ bytes(cl.bytes_rx) }} ↓ {{ bytes(cl.bytes_tx) }} ↑<template v-if="cl.last"> · {{ tr('last') }} <code class="sv-code">{{ cl.last }}</code><template v-if="cl.last_age_s != null"> {{ tr('t_ago', { t: dur(cl.last_age_s) }) }}</template></template></p>
				<p v-if="cl.role === 'no_password' && !cl.control" class="sv-field-error" role="status"><span class="mdi mdi-alert-outline sv-ico sv-ico-s" aria-hidden="true" />{{ tr('this_connection_can_only_query_until') }} <code class="sv-code">BRIDGE KEY &lt;password&gt;</code> {{ tr('or_mark_its_ip_as_trusted') }}</p>
			</li>
		</ul>
		<p v-if="sec && !sec.password && clients.length" class="sv-quiet" data-part="no-key">{{ tr('no_key_is_enabled_now_trusting') }} <b>{{ tr('block') }}</b>.</p>
		<p class="sv-quiet">{{ tr('has_control') }}{{ tr('sends_commands_move_cut_macros') }} {{ tr('listening') }}{{ tr('connected_queries_only_position_temperature') }}</p>
		<lock-reason class="sv-lock" :lock="lockOf(['bridge.service.set'])" />
	</div>
</template>

<script>
import { bridge } from '../../core/store/bridge.js'
import { tc } from '../../core/dwc.js'
import { rowsMixin } from '../../core/rows-mixin.js'
import { bytes, dur, num } from '../../bridge-view.js'
import * as words from '../../bridge-texts.js'
import LockReason from '../../LockReason.vue'
import { bridgeOrders, tr } from './bridge-orders.js'

export default {
	name: 'BridgeConnections',
	components: { LockReason },
	mixins: [rowsMixin, bridgeOrders],
	props: { host: { type: String, default: '' } },
	data() {
		return { editing: null, nameNew: '', remember: true }
	},
	computed: {
		e() {
			return bridge.e
		},
		clients() {
			return (this.e && this.e.clients) || []
		},
		sec() {
			return this.e && this.e.security
		},
		mayOrder() {
			return this.perm('bridge.service.set').state === 'ok'
		}
	},
	methods: {
		tc,
		dur,
		num,
		bytes,
		role(cl) {
			const r = words.roleOf(cl, !!(this.e && this.e.exclusive))
			return { text: tr(r.key), icon: r.icon }
		},
		beginRename(cl) {
			this.editing = cl.id
			this.nameNew = cl.alias || ''
			this.remember = true
		},
		rename(cl) {
			if (!this.nameNew) return
			this.order({ action: 'rename', client: cl.id, name: this.nameNew, remember: this.remember }, 'ren-' + cl.id)
			this.editing = null
		},
		eject(cl) {
			if (this.touch('exp-' + cl.id)) this.order({ action: 'kick', client: cl.id }, 'exp-' + cl.id)
		},
		block(cl) {
			if (this.touch('blq-' + cl.ip)) this.order({ action: 'block', ip: cl.ip }, 'blq-' + cl.ip)
		}
	}
}
</script>
