<template>
	<v-card class="mb-3">
		<!-- Configuration package (2026-10-24). API: package.export / package.preview / package.apply.
		     Settings of the pages, work zones, the person's macros and the machine modes in one zip; no secrets.
		     Importing never overwrites: it shows what it would do first and keeps what is already there. -->
		<v-card-title class="d-flex align-center flex-wrap" style="gap:8px">
			<span><v-icon small class="mr-2 svx-ico">mdi-package-variant-closed</v-icon>{{ $t(T + 'title') }}</span>
		</v-card-title>
		<v-card-text>
			<div class="text-body-2 mb-3">{{ $t(T + 'intro') }}</div>
			<div v-if="msg" class="text-body-2 mb-2" :class="msgOk ? 'success--text' : 'error--text'">{{ msg }}</div>

			<!-- export -->
			<div class="text-subtitle-2">{{ $t(T + 'export_title') }}</div>
			<div class="d-flex flex-wrap align-center" style="gap:12px">
				<v-checkbox v-for="c in categories" :key="'x' + c" v-model="chosen" :value="c" dense hide-details class="mt-0 pt-0"
					:label="$t(T + 'cat_' + c)" />
			</div>
			<div class="text-caption grey--text mb-2">{{ $t(T + 'export_note') }}</div>
			<v-btn small color="primary" :loading="exporting" :disabled="!chosen.length || !can('package.export')" @click="exportPackage()">
				<v-icon small left>mdi-download</v-icon>{{ $t(T + 'download') }}
			</v-btn>
			<div v-for="s in skipped" :key="s.path" class="text-caption warning--text mt-1">
				<code>{{ s.path }}</code> &middot; {{ $t(T + 'skipped_' + s.reason) }}
			</div>

			<v-divider class="my-4" />

			<!-- import -->
			<div class="text-subtitle-2">{{ $t(T + 'import_title') }}</div>
			<div class="text-caption grey--text mb-2">{{ $t(T + 'import_note') }}</div>
			<div class="text-caption grey--text mb-2">{{ $t(T + 'secrets_note') }}</div>
			<v-file-input v-model="file" dense outlined hide-details accept=".zip" :label="$t(T + 'choose_file')" prepend-icon="mdi-package-down"
				:disabled="!can('package.preview')" class="mb-2" @change="preview()" />
			<template v-if="items">
				<div v-if="!items.length" class="grey--text">{{ $t(T + 'empty') }}</div>
				<v-simple-table v-else dense class="mb-2">
					<tbody>
						<tr v-for="i in items" :key="i.path">
							<td style="width:1%">
								<v-checkbox v-if="i.action === 'conflict'" v-model="replace" :value="i.path" dense hide-details class="mt-0 pt-0"
									:title="$t(T + 'replace_this')" />
							</td>
							<td><code class="text-caption">{{ i.path }}</code></td>
							<td class="text-right" style="white-space:nowrap">
								<v-chip x-small outlined :color="color(i.action)">{{ $t(T + 'act_' + i.action) }}</v-chip>
							</td>
						</tr>
					</tbody>
				</v-simple-table>
				<div v-if="hasConflict" class="text-caption mb-2">{{ $t(T + 'conflict_help') }}</div>
				<div v-if="hasReference" class="text-caption mb-2">{{ $t(T + 'reference_help') }}</div>
				<v-btn small color="primary" :loading="applying" :disabled="!todo || !can('package.apply')" @click="apply()">
					<v-icon small left>mdi-package-down</v-icon>{{ $t(T + 'import', { n: todo }) }}
				</v-btn>
				<span v-if="!can('package.apply')" class="text-caption grey--text ml-2">{{ $t(T + 'admin_only') }}</span>
			</template>
		</v-card-text>
	</v-card>
</template>

<script>
'use strict'

import { api, workshopCan } from './workshop-api.js'

const CATEGORIES = ['config', 'zones', 'macros', 'system'];
const COLORS = { create: 'success', same: undefined, conflict: 'warning', reference: 'info', skip: undefined };

// bytes <-> base64 in slices (a big string.fromCharCode(...bytes) overflows the stack)
function toBase64(buffer) {
	const bytes = new Uint8Array(buffer);
	let s = '';
	for (let i = 0; i < bytes.length; i += 0x8000) s += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
	return btoa(s);
}
function fromBase64(text) {
	const s = atob(text);
	const out = new Uint8Array(s.length);
	for (let i = 0; i < s.length; i++) out[i] = s.charCodeAt(i);
	return out;
}

export default {
	data() {
		return {
			T: 'plugins.WorkshopService.package.',
			categories: CATEGORIES,
			chosen: ['config', 'zones', 'macros', 'system'],
			skipped: [],
			exporting: false,
			file: null,
			data: '',
			items: null,
			replace: [],
			applying: false,
			msg: '',
			msgOk: true,
		};
	},
	computed: {
		hasConflict() { return (this.items || []).some(i => i.action === 'conflict'); },
		hasReference() { return (this.items || []).some(i => i.action === 'reference'); },
		// files that importing will write: the ones to create, the reference copies and the conflicts the person ticked
		todo() { return (this.items || []).filter(i => i.action === 'create' || i.action === 'reference' || (i.action === 'conflict' && this.replace.includes(i.path))).length; },
	},
	methods: {
		can(op) { return workshopCan(op); },
		color(a) { return COLORS[a]; },
		say(text, ok) { this.msg = text; this.msgOk = ok !== false; },
		async exportPackage() {
			this.exporting = true;
			this.msg = '';
			try {
				const r = await api('package.export', { categories: this.chosen });
				this.skipped = r.skipped || [];
				const url = URL.createObjectURL(new Blob([fromBase64(r.data)], { type: 'application/zip' }));
				const a = document.createElement('a');
				a.href = url;
				a.download = r.name;
				document.body.appendChild(a);
				a.click();
				a.remove();
				setTimeout(() => URL.revokeObjectURL(url), 10000);
				this.say(this.$t(this.T + 'exported', { n: r.manifest.files.length }));
			} catch (e) {
				this.say(e.message, false);
			} finally {
				this.exporting = false;
			}
		},
		async preview() {
			this.items = null;
			this.replace = [];
			this.msg = '';
			if (!this.file) return;
			try {
				this.data = toBase64(await this.file.arrayBuffer());
				const r = await api('package.preview', { data: this.data });
				this.items = r.items;
			} catch (e) {
				this.say(e.message, false);
			}
		},
		async apply() {
			this.applying = true;
			try {
				const r = await api('package.apply', { data: this.data, replace: this.replace });
				const errors = Object.keys(r.errors || {}).length;
				await this.preview();
				this.say(this.$t(this.T + 'applied', { created: r.created.length, replaced: r.replaced.length, kept: r.kept.length, reference: r.reference.length }) + (errors ? ' ' + this.$t(this.T + 'applied_errors', { n: errors }) : ''), !errors);
			} catch (e) {
				this.say(e.message, false);
			} finally {
				this.applying = false;
			}
		},
	},
};
</script>
