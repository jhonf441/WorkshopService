<template>
	<v-card class="mb-3">
		<v-card-title>
			<v-icon small class="mr-2 svx-ico">mdi-key-chain</v-icon>{{ $t('plugins.WorkshopService.keys.title') }}
			<v-spacer />
			<v-btn small color="primary" @click="openNew"><v-icon left small>mdi-plus</v-icon>{{ $t('plugins.WorkshopService.keys.new_key') }}</v-btn>
		</v-card-title>
		<v-card-text>
			<div class="wf-help mb-2">{{ $t('plugins.WorkshopService.keys.intro') }}</div>
			<details class="wf-more mb-3">
				<summary>{{ $t('plugins.WorkshopService.servicePage.how_it_works') }}</summary>
				<p>{{ $t('plugins.WorkshopService.keys.how_to_use') }}</p>
			</details>
			<v-alert v-if="error" dense text type="error" class="mb-2">{{ error }}</v-alert>
			<div v-if="!keys.length && !loading" class="text-body-2 grey--text">{{ $t('plugins.WorkshopService.keys.none') }}</div>
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
								<v-chip v-for="o in k.ops" :key="'p' + o" x-small label outlined class="mr-1 mb-1" :title="descriptionOp(o)"><code>{{ o }}</code></v-chip>
							</div>
							<div v-if="k.deny.length" class="mt-1">
								<span class="text-caption grey--text mr-1">{{ $t('plugins.WorkshopService.keys.list_refused') }}</span>
								<v-chip v-for="o in k.deny" :key="'d' + o" x-small label outlined color="error" class="mr-1 mb-1" :title="descriptionOp(o)"><code>{{ o }}</code></v-chip>
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
		<v-dialog v-model="dlg" max-width="640" scrollable>
			<v-card>
				<v-card-title class="text-subtitle-1">{{ form.id ? $t('plugins.WorkshopService.keys.edit_title') : $t('plugins.WorkshopService.keys.new_title') }}</v-card-title>
				<v-card-text>
					<v-text-field v-model="form.name" :label="$t('plugins.WorkshopService.keys.service_name')" dense outlined counter="40" :rules="[v => !!v || '']" />
					<v-select
						v-if="!form.id" v-model="form.preset" :items="presetItems" :label="$t('plugins.WorkshopService.keys.starting_point')"
						dense outlined hide-details class="mb-3" @change="applyPreset"
					/>
					<div class="text-caption grey--text mb-1">{{ $t('plugins.WorkshopService.keys.classes') }}</div>
					<div class="d-flex flex-wrap mb-2">
						<v-checkbox
							v-for="c in classes" :key="c" v-model="form.kinds" :value="c" dense hide-details class="mr-4 mt-0"
							:label="nameClass(c)"
						/>
					</div>
					<div class="text-caption grey--text mb-2">{{ $t('plugins.WorkshopService.keys.classes_help') }}</div>
					<v-combobox
						v-model="form.ops" :items="opItems" item-text="text" item-value="value" multiple chips small-chips deletable-chips
						:label="$t('plugins.WorkshopService.keys.extra_operations')" :hint="$t('plugins.WorkshopService.keys.patterns_help')"
						persistent-hint dense outlined :return-object="false" @change="form.ops = norm(form.ops)"
					>
						<template v-slot:item="{ item }">
							<v-list-item-content>
								<v-list-item-title><code>{{ item.value }}</code> <span class="text-caption grey--text">{{ item.cssClass }}</span></v-list-item-title>
								<v-list-item-subtitle>{{ item.desc }}</v-list-item-subtitle>
							</v-list-item-content>
						</template>
					</v-combobox>
					<v-combobox
						v-model="form.deny" :items="opItems" item-text="text" item-value="value" multiple chips small-chips deletable-chips
						:label="$t('plugins.WorkshopService.keys.refused_operations')" :hint="$t('plugins.WorkshopService.keys.patterns_help')"
						persistent-hint dense outlined class="mt-2" :return-object="false" @change="form.deny = norm(form.deny)"
					>
						<template v-slot:item="{ item }">
							<v-list-item-content>
								<v-list-item-title><code>{{ item.value }}</code> <span class="text-caption grey--text">{{ item.cssClass }}</span></v-list-item-title>
								<v-list-item-subtitle>{{ item.desc }}</v-list-item-subtitle>
							</v-list-item-content>
						</template>
					</v-combobox>
					<v-text-field
						v-model="form.days" type="number" min="0" :label="$t('plugins.WorkshopService.keys.valid_days')" :hint="$t('plugins.WorkshopService.keys.valid_days_help')"
						persistent-hint dense outlined class="mt-2" style="max-width:280px"
					/>
					<v-alert dense text type="info" class="mt-3 mb-0">
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
		<v-dialog v-model="dlgKey" max-width="640" persistent>
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

import { api } from './workshop-api.js'
import { copyText } from './copy.js'

// Same rule as Registry._key_allows / api_keys.allows (workshop_api.py): the class or a pattern allows,
// a deny pattern refuses, administration never.
function matches(pattern, nombre) {
	const re = new RegExp('^' + pattern.replace(/[.+^${}()|[\]\\]/g, '\\$&').replace(/\*/g, '.*').replace(/\?/g, '.') + '$');
	return re.test(nombre);
}
const CLASES = ['read', 'write', 'motion', 'stop', 'power'];
const colors = { read: 'blue-grey', write: 'orange', motion: 'deep-purple', stop: 'red', power: 'red darken-3' };
const PRESETS = ['read', 'lights_air', 'notify', 'control', 'full', 'custom'];

function list(txt) {
	return String(txt || '').split(/[\s,]+/).map(x => x.trim().toLowerCase()).filter(Boolean);
}
// the lists of the dialog are arrays (chips): the typed patterns are normalised like the text before
function norm(v) {
	return Array.isArray(v) ? [...new Set(v.map(x => String(x).trim().toLowerCase()).filter(Boolean))] : list(v);
}

export default {
	name: 'ApiKeys',
	props: {
		// api.describe of the service: [{op, kind, desc, args...}]
		operations: { type: Array, default: () => [] }
	},
	data() {
		return {
			keys: [], presets: {}, loading: true, error: '',
			dlg: false, saving: false, errorForm: '',
			form: { id: '', name: '', preset: 'read', kinds: ['read'], ops: [], deny: [], days: '' },
			dlgKey: false, keyNew: '', copied: ''
		};
	},
	computed: {
		classes() { return CLASES; },
		presetItems() {
			return PRESETS.map(p => ({ value: p, text: this.$t('plugins.WorkshopService.keys.preset_' + p) }));
		},
		viewPreview() {
			const rec = { kinds: this.form.kinds, ops: norm(this.form.ops), deny: norm(this.form.deny) };
			return this.allowed(rec);
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
	mounted() { this.read(); },
	methods: {
		nameClass(c) { return this.$t('plugins.WorkshopService.keys.class_' + c); },
		colorClass(c) { return colors[c] || 'grey'; },
		isExpired(k) { return !!k.expires && k.expires * 1000 < Date.now(); },
		expiresSoon(k) { return !!k.expires && !this.isExpired(k) && k.expires * 1000 - Date.now() < 7 * 86400000; },
		date(t) { try { return new Date(t * 1000).toLocaleString(this.$i18n.locale); } catch (e) { return String(t); } },
		allowed(rec) {
			return this.operations.filter(o => {
				if (o.kind === 'admin') return false;
				if ((rec.deny || []).some(p => matches(p, o.op))) return false;
				return (rec.kinds || []).includes(o.kind) || (rec.ops || []).some(p => matches(p, o.op));
			}).map(o => o.op);
		},
		howmany(k) { return this.allowed(k).length; },
		// what an operation (or a pattern) is: its description, or how many operations a pattern covers
		descriptionOp(p) {
			const o = this.operations.find(x => x.op === p);
			if (o) return o.desc || p;
			const n = this.operations.filter(x => x.kind !== 'admin' && matches(p, x.op)).length;
			return this.$t('plugins.WorkshopService.keys.pattern_covers', { n });
		},
		async read() {
			this.loading = true;
			try {
				const r = await api('keys.list');
				this.keys = (r && r.keys) || [];
				this.presets = (r && r.presets) || {};
				this.error = '';
			} catch (e) {
				this.error = e.message || String(e);
			}
			this.loading = false;
		},
		openNew() {
			this.errorForm = '';
			this.form = { id: '', name: '', preset: 'read', kinds: ['read'], ops: [], deny: [], days: '' };
			this.dlg = true;
		},
		openEdit(k) {
			this.errorForm = '';
			this.form = { id: k.id, name: k.name, preset: 'custom', kinds: k.kinds.slice(), ops: k.ops.slice(), deny: k.deny.slice(), days: '' };
			this.dlg = true;
		},
		applyPreset(p) {
			const d = this.presets[p];
			if (!d) return;
			this.form.kinds = (d.kinds || []).slice();
			this.form.ops = (d.ops || []).slice();
		},
		async save() {
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
				this.error = e.message || String(e);
			}
			await this.read();
		},
		async revoke(k) {
			try {
				await api('keys.revoke', { id: k.id });
			} catch (e) {
				if (e.code !== 'cancelled') this.error = e.message || String(e);
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
