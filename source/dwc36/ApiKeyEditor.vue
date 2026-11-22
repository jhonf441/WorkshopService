<template>
	<!-- The editor of the keys: the dialogs to create / edit a key and the key shown ONCE, and the calls that change a key (create, update, enable, revoke).
	     It draws no list: the card of Access > Keys (AccessKeys) holds the list and asks this component through its methods openNew(), openEdit(rawKey),
	     toggle(row) and remove(row). It is the ONE owner of the key in the clear: it is shown once and forgotten on any change of person (sessionData, onSessionChange).
	     Props: operations (api.describe), presets (keys.list). Events: changed (the list must be read again), failed (an error of a call: the card shows it). -->
	<div class="api-key-editor">
		<!-- create / edit -->
		<v-dialog v-model="dlg" max-width="640" width="100%" scrollable persistent content-class="ws-keys-dialog" @keydown.esc="closeForm" @click:outside="closeForm">
			<v-card>
				<v-card-title class="text-subtitle-1">{{ form.id ? $t('plugins.WorkshopService.keys.edit_title') : $t('plugins.WorkshopService.keys.new_title') }}<sv-unsaved-mark :show="hasUnsaved" class="ml-3" /></v-card-title>
				<v-card-text class="ws-keys-body">
					<api-key-form :form="form" :operations="operations" :catalog="catalog" :preview="preview" :preview-error="previewError" :error-form="errorForm" @preset="applyPreset" />
				</v-card-text>
				<v-card-actions>
					<v-spacer />
					<v-btn text @click="closeForm">{{ $t('plugins.WorkshopService.common.cancel') }}</v-btn>
					<v-btn color="primary" :class="{ 'sv-save-hot': hasUnsaved }" :loading="saving" @click="save">{{ form.id ? $t('plugins.WorkshopService.keys.save') : $t('plugins.WorkshopService.keys.create') }}</v-btn>
				</v-card-actions>
			</v-card>
		</v-dialog>

		<api-key-shown v-model="dlgKey" :key-new="keyNew" :example-curl="exampleCurl" :copied="copied" @copy="copy" @done="dlgKey = false; keyNew = ''" />
	</div>
</template>

<script>
'use strict'

import { api, askLogin, currentIdentity, whoami } from './workshop-api.js'
import { accessCanMixin } from './reason-mixin.js'
import { copyText } from './copy.js'
import ApiKeyForm from './ApiKeyForm.vue'
import SvUnsavedMark from './ui/SvUnsavedMark.vue'
import { unsavedMixin } from './ui/unsaved-mixin.js'
import { snapshot } from './ui/unsaved-guard.js'
import ApiKeyShown from './ApiKeyShown.vue'
import { keyNamesMixin, normPatterns as norm, daysProblem } from './api-key-names-mixin.js'

export default {
	name: 'ApiKeyEditor',
	components: { ApiKeyForm, ApiKeyShown, SvUnsavedMark },
	mixins: [accessCanMixin, keyNamesMixin, unsavedMixin],
	// the keys, the forms and above all the dialog with the new key in the clear come from the person who left (ESTANDAR 3.3): emptied on
	// sign-out and change of role; onSessionChange closes the dialogs in every identity change
	sessionData: ['catalog', 'preview', 'previewError', 'dlg', 'saving', 'errorForm', 'form', 'dlgKey', 'keyNew', 'copied'],
	props: {
		// api.describe of the service: [{op, kind, desc, args...}]
		operations: { type: Array, default: () => [] },
		// keys.list: the starting points of the dialog (read, lights and air, ...)
		presets: { type: Object, default: () => ({}) }
	},
	data() {
		return {
			catalog: [], preview: [], previewError: '',
			dlg: false, formBase: null, saving: false, errorForm: '',
			form: { id: '', name: '', preset: 'read', kinds: ['read'], ops: [], deny: [], days: '', strict: true },
			dlgKey: false, keyNew: '', copied: ''
		};
	},
	computed: {
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
		this.readCatalog();
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
			if (kind !== 'signed-out') this.readCatalog();
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
		// unsaved changes (ui/unsaved-mixin.js): the key form against how it opened; Cancel, Escape and a touch outside ask first when something was typed.
		// The key in the clear is not part of this: it is shown once and forgotten on a change of person, as before.
		unsavedPair() {
			return this.dlg ? [this.form, this.formBase] : [null, null];
		},
		async saveBeforeLeaving() {
			await this.save();
			return !this.dlg;
		},
		discardUnsaved() { this.dlg = false; },
		closeForm() { this.leaveWith(() => { this.dlg = false; }); },
		openNew() {
			if (currentIdentity() && currentIdentity().configured && currentIdentity().login_required) return askLogin();
			this.errorForm = '';
			this.form = { id: '', name: '', preset: 'read', kinds: ['read'], ops: [], deny: [], days: '', strict: true };
			this.formBase = snapshot(this.form);
			this.dlg = true;
		},
		// k: the key as keys.list gives it (kinds, ops, deny, strict)
		openEdit(k) {
			if (currentIdentity() && currentIdentity().configured && currentIdentity().login_required) return askLogin();
			this.errorForm = '';
			this.form = { id: k.id, name: k.name, preset: 'custom', kinds: k.kinds.slice(), ops: k.ops.slice(), deny: k.deny.slice(), days: '', strict: k.strict !== false };
			this.formBase = snapshot(this.form);
			this.dlg = true;
		},
		applyPreset(p) {
			const d = (this.presets || {})[p];
			if (!d) return;
			this.form.kinds = (d.kinds || []).slice();
			this.form.ops = (d.ops || []).slice();
		},
		async save() {
			const gen = this._gen;
			this.saving = true;
			this.errorForm = '';
			const f = this.form;
			if (daysProblem(f.days, !!f.id)) {
				this.errorForm = this.$t('plugins.WorkshopService.keys.days_invalid');
				this.saving = false;
				return;
			}
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
				this.$emit('changed');
			} catch (e) {
				if (e.code !== 'cancelled') this.errorForm = e.message || String(e);
			}
			this.saving = false;
		},
		// the switch of a row: on / off (an expired key cannot be switched: the card does not offer it)
		async toggle(k, v) {
			try {
				await api('keys.update', { id: k.id, enabled: !!v });
			} catch (e) {
				if (e.code !== 'cancelled') this.$emit('failed', e);
			}
			this.$emit('changed');
		},
		// the bin of a row: the service asks for confirmation (level 3, keys.revoke)
		async remove(k) {
			try {
				await api('keys.revoke', { id: k.id });
			} catch (e) {
				if (e.code !== 'cancelled') this.$emit('failed', e);
			}
			this.$emit('changed');
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
.ws-keys-menu { max-width: calc(100vw - 32px); border: 1px solid var(--sv-control-line); border-radius: var(--sv-r-control); background: var(--wf-surface) !important; box-shadow: var(--sv-shadow) !important; }
.ws-keys-menu .v-list { background: var(--wf-surface) !important; padding: 4px 0; }
.ws-keys-menu .v-list-item { min-height: var(--sv-touch); color: var(--sv-text); }
.ws-keys-menu .v-list-item--highlighted, .ws-keys-menu .v-list-item:focus { background: var(--wf-soft); outline: 2px solid var(--sv-focus); outline-offset: -2px; }
.ws-keys-menu .v-list-item__title, .ws-keys-menu .v-list-item__subtitle { white-space: normal; overflow-wrap: anywhere; }
.ws-keys-menu .v-list-item__subtitle { color: var(--sv-text-2); }
</style>
