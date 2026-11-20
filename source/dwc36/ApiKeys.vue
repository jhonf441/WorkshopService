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
			<lock-reason v-else :ops="['keys.create', 'keys.update', 'keys.revoke']" class="mb-2" />
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
							<v-chip v-for="c in k.kinds" :key="c" x-small label outlined class="mr-1 mb-1" :title="nameClass(c)"><v-icon x-small left aria-hidden="true">{{ iconClass(c) }}</v-icon>{{ nameClass(c) }}</v-chip>
							<div class="text-caption grey--text mt-1">{{ $tc('plugins.WorkshopService.keys.can_call', howmany(k), { n: howmany(k) }) }}</div>
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
							<sv-toggle :value="!!k.enabled" :label="$t('plugins.WorkshopService.keys.col_active')" :disabled="isExpired(k)" @input="v => enable(k, v)" />
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
					<api-key-form :form="form" :operations="operations" :catalog="catalog" :preview="preview" :preview-error="previewError" :error-form="errorForm" @preset="applyPreset" />
				</v-card-text>
				<v-card-actions>
					<v-spacer />
					<v-btn text @click="dlg = false">{{ $t('plugins.WorkshopService.common.cancel') }}</v-btn>
					<v-btn color="primary" :loading="saving" @click="save">{{ form.id ? $t('plugins.WorkshopService.keys.save') : $t('plugins.WorkshopService.keys.create') }}</v-btn>
				</v-card-actions>
			</v-card>
		</v-dialog>

		<api-key-shown v-model="dlgKey" :key-new="keyNew" :example-curl="exampleCurl" :copied="copied" @copy="copy" @done="dlgKey = false; keyNew = ''" />
	</v-card>
</template>

<script>
'use strict'

import { api, askLogin, currentIdentity, whoami } from './workshop-api.js'
import { signedOut } from './workshop-auth.js'
import { accessCanMixin } from './reason-mixin.js'
import { copyText } from './copy.js'
import SessionNotice from './SessionNotice.vue'
import ErrorNotice from './ErrorNotice.vue'
import LockReason from './LockReason.vue'
import HelpGuide from './HelpGuide.vue'
import ApiKeyForm from './ApiKeyForm.vue'
import ApiKeyShown from './ApiKeyShown.vue'
import SvToggle from './ui/SvToggle.vue'
import { keyNamesMixin, normPatterns as norm } from './api-key-names-mixin.js'

// the class of an operation is told by an icon AND its word, in the neutral chip of the family: a colour of its own made the text unreadable (grey on red)
const icons = { read: 'mdi-eye-outline', write: 'mdi-pencil-outline', motion: 'mdi-axis-arrow', stop: 'mdi-stop-circle-outline', power: 'mdi-flash-outline' };

export default {
	name: 'ApiKeys',
	components: { SessionNotice, ErrorNotice, LockReason, HelpGuide, ApiKeyForm, ApiKeyShown, SvToggle },
	mixins: [accessCanMixin, keyNamesMixin],
	// the keys, the forms and above all the dialog with the new key in the clear come from the person who left (ESTANDAR 3.3): emptied on
	// sign-out and change of role; onSessionChange closes the dialogs in every identity change
	sessionData: ['keys', 'presets', 'catalog', 'preview', 'previewError', 'loading', 'error', 'dlg', 'saving', 'errorForm', 'form', 'dlgKey', 'keyNew', 'copied'],
	props: {
		// api.describe of the service: [{op, kind, desc, args...}]
		operations: { type: Array, default: () => [] }
	},
	data() {
		return {
			keys: [], presets: {}, loading: true, error: null, catalog: [], preview: [], previewError: '',
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
		iconClass(c) { return icons[c] || 'mdi-help-circle-outline'; },
		isExpired(k) { return !!k.expires && k.expires * 1000 < Date.now(); },
		expiresSoon(k) { return !!k.expires && !this.isExpired(k) && k.expires * 1000 - Date.now() < 7 * 86400000; },
		date(t) { try { return new Date(t * 1000).toLocaleString(this.$i18n.locale); } catch (e) { return String(t); } },
		// the operations a saved key may call: resolved by the service (keys.list -> allowed_ops)
		howmany(k) { return (k.allowed_ops || []).length; },
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
