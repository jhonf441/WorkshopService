<template>
	<v-card class="mb-3">
		<v-card-title>
			<v-icon small class="mr-2 svx-ico">mdi-key-chain</v-icon>{{ $t('plugins.WorkshopService.keys.title') }}
			<v-spacer />
			<v-btn small color="primary" :disabled="locked" @click="openNew"><v-icon left small>mdi-plus</v-icon>{{ $t('plugins.WorkshopService.keys.new_key') }}</v-btn>
		</v-card-title>
		<v-card-text v-if="out">
			<session-notice kind="session" variant="section" class="mb-0" />
		</v-card-text>
		<v-card-text v-else>
			<lock-reason v-if="!canDo('keys.list')" op="keys.list" need="admin" class="mb-2" />
			<help-guide class="mb-3" :what="$t('plugins.WorkshopService.keys.intro')" :how="$t('plugins.WorkshopService.keys.how_to_use')" />
			<error-notice v-if="canDo('keys.list')" :error="error" class="mb-2" />
			<div v-if="!keys.length && !loading && canDo('keys.list')" class="text-body-2 grey--text">{{ $t('plugins.WorkshopService.keys.none') }}</div>
			<v-simple-table v-else dense>
				<thead>
					<tr>
						<th>{{ $t('plugins.WorkshopService.keys.col_name') }}</th>
						<th>{{ $t('plugins.WorkshopService.keys.col_allows') }}</th>
						<th>{{ $t('plugins.WorkshopService.keys.col_last_use') }}</th>
						<th>{{ $t('plugins.WorkshopService.keys.col_expires') }}</th>
						<th>{{ $t('plugins.WorkshopService.keys.col_active') }}</th>
						<th />
					</tr>
				</thead>
				<tbody>
					<tr v-for="k in keys" :key="k.id" :class="{ 'grey--text': isExpired(k) }">
						<td>
							<strong>{{ k.name }}</strong>
							<div class="text-caption grey--text"><code>{{ k.prefix }}...</code></div>
						</td>
						<td>
							<v-chip v-for="c in k.kinds" :key="c" x-small label class="mr-1" :color="colorClass(c)" dark>{{ nameClass(c) }}</v-chip>
							<div class="text-caption grey--text">{{ $t('plugins.WorkshopService.keys.can_call', { n: howmany(k) }) }}</div>
							<div v-if="k.ops.length" class="mt-1">
								<span class="text-caption grey--text mr-1">{{ $t('plugins.WorkshopService.keys.list_extra') }}</span>
								<v-chip v-for="o in k.ops" :key="'p' + o" x-small label outlined class="mr-1 mb-1" :title="descriptionOp(o)"><v-icon v-if="isCap(o)" x-small left>mdi-shape-outline</v-icon><code v-if="!isCap(o)">{{ o }}</code><span v-else>{{ capTitle(o) }}</span></v-chip>
							</div>
							<div v-if="k.deny.length" class="mt-1">
								<span class="text-caption grey--text mr-1">{{ $t('plugins.WorkshopService.keys.list_refused') }}</span>
								<v-chip v-for="o in k.deny" :key="'d' + o" x-small label outlined color="error" class="mr-1 mb-1" :title="descriptionOp(o)"><v-icon v-if="isCap(o)" x-small left>mdi-shape-outline</v-icon><code v-if="!isCap(o)">{{ o }}</code><span v-else>{{ capTitle(o) }}</span></v-chip>
							</div>
							<div v-if="k.strict === false" class="mt-1">
								<v-chip x-small label color="warning" dark :title="$t('plugins.WorkshopService.keys.cap_legacy_hint')">{{ $t('plugins.WorkshopService.keys.cap_legacy') }}</v-chip>
							</div>
						</td>
						<td class="text-caption">{{ k.last_used ? date(k.last_used) + ' (' + k.uses + ')' : $t('plugins.WorkshopService.keys.never_used') }}</td>
						<td class="text-caption">
							{{ k.expires ? date(k.expires) : $t('plugins.WorkshopService.keys.no_expiry') }}
							<div v-if="isExpired(k)"><v-chip x-small label color="error" dark>{{ $t('plugins.WorkshopService.keys.expired') }}</v-chip></div>
							<div v-else-if="expiresSoon(k)"><v-chip x-small label color="warning" dark>{{ $t('plugins.WorkshopService.keys.expires_soon') }}</v-chip></div>
						</td>
						<td>
							<v-switch :input-value="k.enabled" dense hide-details class="mt-0 pt-0" :disabled="isExpired(k)" @change="v => enable(k, v)" />
							<div v-if="isExpired(k)" class="text-caption grey--text">{{ $t('plugins.WorkshopService.keys.expired_hint') }}</div>
						</td>
						<td class="text-right" style="white-space:nowrap">
							<v-btn icon small :title="$t('plugins.WorkshopService.keys.edit')" @click="openEdit(k)"><v-icon small>mdi-pencil</v-icon></v-btn>
							<v-btn icon small color="error" :title="$t('plugins.WorkshopService.keys.revoke')" @click="revoke(k)"><v-icon small>mdi-delete</v-icon></v-btn>
						</td>
					</tr>
				</tbody>
			</v-simple-table>
		</v-card-text>

		<!-- create / edit -->
		<v-dialog v-model="dlg" max-width="640" width="100%" scrollable content-class="ws-keys-dialog">
			<v-card>
				<v-card-title class="text-subtitle-1">{{ form.id ? $t('plugins.WorkshopService.keys.edit_title') : $t('plugins.WorkshopService.keys.new_title') }}</v-card-title>
				<v-card-text class="ws-keys-body">
					<v-text-field v-model="form.name" :label="$t('plugins.WorkshopService.keys.service_name')" dense outlined counter="40" :rules="[v => !!v || '']" />
					<v-select
						v-if="!form.id" v-model="form.preset" :items="presetItems" :label="$t('plugins.WorkshopService.keys.starting_point')"
						dense outlined hide-details class="mb-3" :menu-props="menuProps" :title="presetTitle" @change="applyPreset"
					/>
					<div class="text-caption grey--text mb-1">{{ $t('plugins.WorkshopService.keys.classes') }}</div>
					<div class="d-flex flex-wrap mb-2">
						<v-checkbox
							v-for="c in classes" :key="c" v-model="form.kinds" :value="c" dense hide-details class="mr-4 mt-0"
							:label="nameClass(c)"
						/>
					</div>
					<div class="text-caption grey--text mb-2">{{ $t('plugins.WorkshopService.keys.classes_help') }}</div>
					<wf-field id="ws-key-ops" :label="$t('plugins.WorkshopService.keys.extra_operations')">
						<template #help>
							<help-tip :title="$t('plugins.WorkshopService.keys.extra_operations')" :what="$t('plugins.WorkshopService.keys.help_extra_what')" :why="$t('plugins.WorkshopService.keys.patterns_help')" :how="$t('plugins.WorkshopService.keys.help_patterns_how')" />
						</template>
						<v-combobox
							id="ws-key-ops" v-model="form.ops" :items="opItems" item-text="text" item-value="value" multiple chips small-chips deletable-chips
							:aria-label="$t('plugins.WorkshopService.keys.extra_operations')" hide-details dense outlined :menu-props="menuProps" :return-object="false" @change="form.ops = norm(form.ops)"
						>
							<template v-slot:selection="{ item, parent }">
								<v-chip small close :title="descriptionOp(item)" @click:close="parent.selectItem(item)">
									<v-icon v-if="isCap(item)" small left>mdi-shape-outline</v-icon>{{ isCap(item) ? capTitle(item) : item }}
								</v-chip>
							</template>
							<template v-slot:item="{ item }">
								<v-list-item-content>
									<v-list-item-title><code>{{ item.value }}</code> <span class="text-caption grey--text">{{ item.cssClass }}</span></v-list-item-title>
									<v-list-item-subtitle>{{ item.desc }}</v-list-item-subtitle>
								</v-list-item-content>
							</template>
						</v-combobox>
					</wf-field>
					<wf-field id="ws-key-deny" :label="$t('plugins.WorkshopService.keys.refused_operations')" class="mt-2">
						<template #help>
							<help-tip :title="$t('plugins.WorkshopService.keys.refused_operations')" :what="$t('plugins.WorkshopService.keys.help_refused_what')" :why="$t('plugins.WorkshopService.keys.patterns_help')" :how="$t('plugins.WorkshopService.keys.help_patterns_how')" />
						</template>
						<v-combobox
							id="ws-key-deny" v-model="form.deny" :items="opItems" item-text="text" item-value="value" multiple chips small-chips deletable-chips
							:aria-label="$t('plugins.WorkshopService.keys.refused_operations')" hide-details dense outlined :menu-props="menuProps" :return-object="false" @change="form.deny = norm(form.deny)"
						>
							<template v-slot:selection="{ item, parent }">
								<v-chip small close :title="descriptionOp(item)" @click:close="parent.selectItem(item)">
									<v-icon v-if="isCap(item)" small left>mdi-shape-outline</v-icon>{{ isCap(item) ? capTitle(item) : item }}
								</v-chip>
							</template>
							<template v-slot:item="{ item }">
								<v-list-item-content>
									<v-list-item-title><code>{{ item.value }}</code> <span class="text-caption grey--text">{{ item.cssClass }}</span></v-list-item-title>
									<v-list-item-subtitle>{{ item.desc }}</v-list-item-subtitle>
								</v-list-item-content>
							</template>
						</v-combobox>
					</wf-field>
					<wf-field id="ws-key-cap" :label="$t('plugins.WorkshopService.keys.cap_title')" class="mt-2">
						<template #help>
							<help-tip :title="$t('plugins.WorkshopService.keys.cap_title')" :what="$t('plugins.WorkshopService.keys.cap_help_what')" :why="$t('plugins.WorkshopService.keys.cap_help_why')" :how="$t('plugins.WorkshopService.keys.cap_help_how')" />
						</template>
						<div v-if="!capItems.length" class="text-caption grey--text">{{ $t('plugins.WorkshopService.keys.cap_catalog_missing') }}</div>
						<div v-else class="d-flex align-center flex-wrap">
							<v-autocomplete
								id="ws-key-cap" v-model="capPick" :items="capItems" item-text="text" item-value="value" :placeholder="$t('plugins.WorkshopService.keys.cap_pick')"
								:aria-label="$t('plugins.WorkshopService.keys.cap_title')" clearable hide-details dense outlined class="flex-grow-1 mr-2" :menu-props="capMenuProps"
							>
								<template v-slot:item="{ item }">
									<v-list-item-content v-if="item.header" class="text-overline">{{ item.header }}</v-list-item-content>
									<v-list-item-content v-else>
										<v-list-item-title>{{ item.text }} <span class="text-caption grey--text">{{ item.meta }}</span></v-list-item-title>
										<v-list-item-subtitle>{{ item.value }}</v-list-item-subtitle>
									</v-list-item-content>
								</template>
							</v-autocomplete>
							<v-btn small color="primary" class="mr-1" :disabled="!capPick || !capGrantable(capPick)" @click="addCap('ops')">{{ $t('plugins.WorkshopService.keys.cap_allow') }}</v-btn>
							<v-btn small color="error" outlined :disabled="!capPick" @click="addCap('deny')">{{ $t('plugins.WorkshopService.keys.cap_refuse') }}</v-btn>
						</div>
						<div v-if="capPick && !capGrantable(capPick)" class="text-caption warning--text mt-1">{{ $t('plugins.WorkshopService.keys.cap_not_for_keys') }}</div>
					</wf-field>
					<wf-field id="ws-key-days" :label="$t('plugins.WorkshopService.keys.valid_days')" :message="$t('plugins.WorkshopService.keys.valid_days_help')" class="mt-2" style="max-width:280px">
						<v-text-field id="ws-key-days" v-model="form.days" type="number" min="0" :aria-label="$t('plugins.WorkshopService.keys.valid_days')" hide-details dense outlined />
					</wf-field>
					<v-alert v-if="form.id && form.strict === false" dense text type="warning" class="mt-3 mb-0">{{ $t('plugins.WorkshopService.keys.cap_legacy_hint') }}</v-alert>
					<v-alert v-if="previewError" dense text type="error" class="mt-3 mb-0">{{ previewError }}</v-alert>
					<v-alert v-else dense text type="info" class="mt-3 mb-0">
						{{ $t('plugins.WorkshopService.keys.preview', { n: viewPreview.length }) }}
						<div class="text-caption" style="max-height:110px;overflow:auto">{{ viewPreview.join(', ') || '-' }}</div>
					</v-alert>
					<v-alert dense text type="warning" class="mt-2 mb-0">{{ $t('plugins.WorkshopService.keys.never_admin') }}</v-alert>
					<v-alert v-if="errorForm" dense text type="error" class="mt-2 mb-0">{{ errorForm }}</v-alert>
				</v-card-text>
				<v-card-actions>
					<v-spacer />
					<v-btn text @click="dlg = false">{{ $t('plugins.WorkshopService.common.cancel') }}</v-btn>
					<v-btn color="primary" :loading="saving" @click="save">{{ form.id ? $t('plugins.WorkshopService.keys.save') : $t('plugins.WorkshopService.keys.create') }}</v-btn>
				</v-card-actions>
			</v-card>
		</v-dialog>

		<!-- the key, shown once -->
		<v-dialog v-model="dlgKey" max-width="640" width="100%" persistent content-class="ws-keys-dialog">
			<v-card>
				<v-card-title class="text-subtitle-1">{{ $t('plugins.WorkshopService.keys.your_key') }}</v-card-title>
				<v-card-text>
					<v-alert dense text type="warning">{{ $t('plugins.WorkshopService.keys.shown_once') }}</v-alert>
					<div class="d-flex align-center">
						<code class="d-block pa-2 flex-grow-1" style="word-break:break-all">{{ keyNew }}</code>
						<v-btn icon small class="ml-1" @click="copy(keyNew, 'key', $event)"><v-icon small>{{ copied === 'key' ? 'mdi-check' : 'mdi-content-copy' }}</v-icon></v-btn>
					</div>
					<div class="text-caption grey--text mt-3 mb-1">{{ $t('plugins.WorkshopService.keys.example') }}</div>
					<div class="d-flex align-start">
						<code class="d-block pa-2 flex-grow-1" style="white-space:pre-wrap;word-break:break-all">{{ exampleCurl }}</code>
						<v-btn icon small class="ml-1" @click="copy(exampleCurl, 'curl', $event)"><v-icon small>{{ copied === 'curl' ? 'mdi-check' : 'mdi-content-copy' }}</v-icon></v-btn>
					</div>
				</v-card-text>
				<v-card-actions>
					<v-spacer />
					<v-btn color="primary" @click="dlgKey = false; keyNew = ''">{{ $t('plugins.WorkshopService.keys.i_copied_it') }}</v-btn>
				</v-card-actions>
			</v-card>
		</v-dialog>
	</v-card>
</template>

<script>
'use strict'

import { api, askLogin, currentIdentity, whoami } from './workshop-api.js'
import { signedOut } from './workshop-auth.js'
import { roleMixin } from './role-mixin.js'
import { copyText } from './copy.js'
import SessionNotice from './SessionNotice.vue'
import ErrorNotice from './ErrorNotice.vue'
import LockReason from './LockReason.vue'
import HelpGuide from './HelpGuide.vue'
import HelpTip from './HelpTip.vue'
import WfField from './WfField.vue'

const CLASES = ['read', 'write', 'motion', 'stop', 'power'];
const colors = { read: 'blue-grey', write: 'orange', motion: 'deep-purple', stop: 'red', power: 'red darken-3' };
const PRESETS = ['read', 'lights_air', 'notify', 'control', 'full', 'custom'];
const CAP_PREFIX = 'cap:'; // the same prefix as api_keys.CAP_PREFIX (keys.list answers it as cap_prefix)
const CAT_ORDER = ['machine', 'jobs', 'lights', 'energy', 'activity', 'camera', 'security', 'config', 'system'];

function list(txt) {
	return String(txt || '').split(/[\s,]+/).map(x => x.trim().toLowerCase()).filter(Boolean);
}
// the lists of the dialog are arrays (chips): the typed patterns are normalised like the text before
function norm(v) {
	return Array.isArray(v) ? [...new Set(v.map(x => String(x).trim().toLowerCase()).filter(Boolean))] : list(v);
}

export default {
	name: 'ApiKeys',
	components: { SessionNotice, ErrorNotice, LockReason, HelpGuide, HelpTip, WfField },
	mixins: [roleMixin],
	// the keys, the forms and above all the dialog with the new key in the clear come from the person who left (ESTANDAR 3.3): emptied on
	// sign-out and change of role; onSessionChange closes the dialogs in every identity change
	sessionData: ['keys', 'presets', 'catalog', 'capPick', 'preview', 'previewError', 'loading', 'error', 'dlg', 'saving', 'errorForm', 'form', 'dlgKey', 'keyNew', 'copied'],
	props: {
		// api.describe of the service: [{op, kind, desc, args...}]
		operations: { type: Array, default: () => [] }
	},
	data() {
		return {
			keys: [], presets: {}, loading: true, error: null, catalog: [], capPick: null, preview: [], previewError: '',
			dlg: false, saving: false, errorForm: '',
			form: { id: '', name: '', preset: 'read', kinds: ['read'], ops: [], deny: [], days: '', strict: true },
			dlgKey: false, keyNew: '', copied: ''
		};
	},
	computed: {
		// no session (or a token the service no longer accepts): nothing of the keys is shown or offered; the standard notice says why
		out() {
			void this.identityTick;
			const id = currentIdentity();
			return signedOut() || !!(id && id.configured && id.login_required);
		},
		// the button is locked when there is no session or the role cannot create keys (the service refuses it anyway: this only says so first)
		locked() { return this.out || !this.canDo('keys.create'); },
		classes() { return CLASES; },
		menuProps() { return { maxWidth: 600, contentClass: 'ws-keys-menu' }; },
		presetTitle() {
			const it = this.presetItems.find(i => i.value === this.form.preset);
			return it ? it.text : '';
		},
		presetItems() {
			return PRESETS.map(p => ({ value: p, text: this.$t('plugins.WorkshopService.keys.preset_' + p) }));
		},
		// what the service says the permissions of the form allow (keys.preview): the page has no copy of the rule
		viewPreview() { return this.preview; },
		capMenuProps() { return this.menuProps; },
		// the capabilities of roles.list (title, category, class, risk, delegable) grouped by category, to pick from
		capItems() {
			const out = [];
			for (const cat of CAT_ORDER) {
				const list = this.catalog.filter(c => c.category === cat);
				if (!list.length) continue;
				out.push({ header: this.$t('plugins.WorkshopService.keys.cap_group_' + cat) });
				for (const c of list) out.push({ text: c.title || c.id, value: c.id, meta: this.$t('plugins.WorkshopService.keys.cap_risk') + ' ' + c.risk + '/4' });
			}
			return out;
		},
		// every operation of the service (except administration, never given to a key) to pick from
		opItems() {
			return this.operations.filter(o => o.kind !== 'admin').map(o => ({ text: o.op, value: o.op, cssClass: this.nameClass(o.kind), desc: o.desc || '' }));
		},
		exampleCurl() {
			const host = (typeof location !== 'undefined' && location.host) || 'duet3.local';
			return "curl -s -X POST http://" + host + "/machine/WorkshopService/api \\\n  -H 'Content-Type: application/json' -H 'X-Workshop-Key: " + this.keyNew + "' \\\n  -d '{\"op\":\"api.ping\",\"args\":{}}'";
		}
	},
	created() {
		this._gen = 0;
	},
	mounted() {
		if (!currentIdentity()) whoami().catch(() => {});
		if (!this.out) this.read();
	},
	beforeDestroy() {
		clearTimeout(this._pt);
	},
	watch: {
		dlg(v) { if (v) { this.preview = []; this.previewError = ''; this.askPreview(); } },
		'form.kinds': 'askPreview',
		'form.ops': 'askPreview',
		'form.deny': 'askPreview'
	},
	methods: {
		// A secret does not survive a change of person: in ANY identity change both dialogs close and the key shown once is forgotten. An answer
		// of the old person still on its way is dropped; for the new identity the keys are read again.
		onSessionChange(kind) {
			this._gen++;
			this.dlg = false;
			this.dlgKey = false;
			this.keyNew = '';
			this.errorForm = '';
			if (kind !== 'signed-out' && !this.out) this.read();
		},
		nameClass(c) { return this.$t('plugins.WorkshopService.keys.class_' + c); },
		colorClass(c) { return colors[c] || 'grey'; },
		isExpired(k) { return !!k.expires && k.expires * 1000 < Date.now(); },
		expiresSoon(k) { return !!k.expires && !this.isExpired(k) && k.expires * 1000 - Date.now() < 7 * 86400000; },
		date(t) { try { return new Date(t * 1000).toLocaleString(this.$i18n.locale); } catch (e) { return String(t); } },
		// the operations a saved key may call: resolved by the service (keys.list -> allowed_ops)
		howmany(k) { return (k.allowed_ops || []).length; },
		isCap(e) { return String(e).startsWith(CAP_PREFIX); },
		capOf(e) { const id = String(e).slice(CAP_PREFIX.length); return this.catalog.find(c => c.id === id) || null; },
		capTitle(e) { const c = this.capOf(e); return c ? c.title : String(e).slice(CAP_PREFIX.length); },
		// only a capability that is delegable and not of the administration class can be allowed to a key (the service checks it again)
		capGrantable(id) { const c = this.catalog.find(x => x.id === id); return !!c && c.delegable && c.class !== 'admin'; },
		// what an entry is: a capability (its title and the operations it groups), an operation (its description) or a pattern
		descriptionOp(p) {
			if (this.isCap(p)) {
				const c = this.capOf(p);
				return c ? this.$t('plugins.WorkshopService.keys.cap_chip') + ': ' + c.title + ' (' + c.ops.join(', ') + ')' : p;
			}
			const o = this.operations.find(x => x.op === p);
			return o ? (o.desc || p) : this.$t('plugins.WorkshopService.keys.cap_pattern_hint');
		},
		addCap(field) {
			if (!this.capPick) return;
			const e = CAP_PREFIX + this.capPick;
			if (!this.form[field].includes(e)) this.form[field] = [...this.form[field], e];
			this.capPick = null;
		},
		async readCatalog() {
			const gen = this._gen;
			if (!this.canDo('roles.list')) { this.catalog = []; return; }
			try {
				const r = await api('roles.list');
				if (gen === this._gen) this.catalog = (r && r.capabilities) || [];
			} catch (e) {
				if (gen === this._gen) this.catalog = [];
			}
		},
		// asks the service what the permissions of the form would allow; the answer of an older form is dropped
		askPreview() {
			clearTimeout(this._pt);
			this._pt = setTimeout(async () => {
				const gen = this._gen, n = this._pn = (this._pn || 0) + 1;
				if (!this.dlg) return;
				const f = this.form;
				try {
					const r = await api('keys.preview', { kinds: f.kinds, ops: norm(f.ops), deny: norm(f.deny) });
					if (gen !== this._gen || n !== this._pn) return;
					this.preview = (r && r.allowed_ops) || [];
					this.previewError = '';
				} catch (e) {
					if (gen !== this._gen || n !== this._pn) return;
					this.previewError = e.message || String(e);
				}
			}, 250);
		},
		async read() {
			const gen = this._gen;
			if (!this.canDo('keys.list')) { this.keys = []; this.error = null; return; } // a role that cannot list keys does not ask: the lock reason says why
			this.loading = true;
			try {
				const r = await api('keys.list');
				if (gen !== this._gen) return;
				this.keys = (r && r.keys) || [];
				this.presets = (r && r.presets) || {};
				this.error = null;
				this.readCatalog();
			} catch (e) {
				if (gen !== this._gen) return;
				this.error = e;
			}
			this.loading = false;
		},
		openNew() {
			if (this.out) return askLogin();
			this.errorForm = '';
			this.form = { id: '', name: '', preset: 'read', kinds: ['read'], ops: [], deny: [], days: '', strict: true };
			this.dlg = true;
		},
		openEdit(k) {
			if (this.out) return askLogin();
			this.errorForm = '';
			this.form = { id: k.id, name: k.name, preset: 'custom', kinds: k.kinds.slice(), ops: k.ops.slice(), deny: k.deny.slice(), days: '', strict: k.strict !== false };
			this.dlg = true;
		},
		applyPreset(p) {
			const d = this.presets[p];
			if (!d) return;
			this.form.kinds = (d.kinds || []).slice();
			this.form.ops = (d.ops || []).slice();
		},
		async save() {
			const gen = this._gen;
			this.saving = true;
			this.errorForm = '';
			const f = this.form;
			try {
				if (f.id) {
					const args = { id: f.id, name: f.name, kinds: f.kinds, ops: norm(f.ops), deny: norm(f.deny) };
					if (f.days !== '' && f.days !== null) args.days = Number(f.days);
					await api('keys.update', args);
					this.dlg = false;
				} else {
					const args = { name: f.name, kinds: f.kinds, ops: norm(f.ops), deny: norm(f.deny) };
					if (f.days !== '' && f.days !== null && Number(f.days) > 0) args.days = Number(f.days);
					const r = await api('keys.create', args);
					if (gen !== this._gen) return; // the person changed meanwhile: the new key is not shown to anybody else
					this.dlg = false;
					this.keyNew = (r && r.key) || '';
					this.dlgKey = !!this.keyNew;
				}
				await this.read();
			} catch (e) {
				if (e.code !== 'cancelled') this.errorForm = e.message || String(e);
			}
			this.saving = false;
		},
		async enable(k, v) {
			try {
				await api('keys.update', { id: k.id, enabled: !!v });
			} catch (e) {
				this.error = e;
			}
			await this.read();
		},
		async revoke(k) {
			try {
				await api('keys.revoke', { id: k.id });
			} catch (e) {
				if (e.code !== 'cancelled') this.error = e;
			}
			await this.read();
		},
		// the buttons are inside a dialog: the copy happens inside it (see copy.js); only says "copied" if it was
		async copy(txt, id, ev) {
			const cont = ev && ev.currentTarget ? ev.currentTarget.closest('.v-card') : null;
			const ok = await copyText(txt, cont);
			if (!ok) return;
			this.copied = id;
			setTimeout(() => { if (this.copied === id) this.copied = ''; }, 1500);
		}
	}
};
</script>

<style>
/* both key modals (new and edit): stay inside the modal at any width, nothing cut at the top, long texts cut with an ellipsis */
.ws-keys-dialog { width: 100%; max-width: 640px; overflow-x: hidden; }
.ws-keys-dialog .v-card { min-width: 0; max-width: 100%; }
.ws-keys-dialog .ws-keys-body { padding-top: 24px !important; overflow-x: hidden; }
.ws-keys-dialog .v-input, .ws-keys-dialog .v-input__control, .ws-keys-dialog .v-input__slot, .ws-keys-dialog .v-select__slot { min-width: 0; max-width: 100%; }
.ws-keys-dialog .v-select__selections { min-width: 0; flex-wrap: wrap; }
.ws-keys-dialog .v-select__selection { max-width: 100%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.ws-keys-dialog .v-chip { max-width: 100%; }
.ws-keys-dialog .v-chip .v-chip__content { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; display: block; }
.ws-keys-menu { max-width: calc(100vw - 32px); }
.ws-keys-menu .v-list-item__title, .ws-keys-menu .v-list-item__subtitle { white-space: normal; overflow-wrap: anywhere; }
</style>
