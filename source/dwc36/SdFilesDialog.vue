<template>
	<span class="svc-sdf">
		<!-- Files per plugin: which files each plugin brings on THIS SD and how they are now. Read only (startup.files); the diff of an edited file is the one of
		     the integrity module, and what is missing is fixed in the start-up wizard. -->
		<v-btn small outlined class="svc-sdf-touch" @click="show = true"><v-icon small left>mdi-folder-search-outline</v-icon>{{ $t(T + 'open') }}</v-btn>
		<v-dialog v-model="show" max-width="1100" width="100%" scrollable content-class="svc-sdf-dialog">
			<v-card role="dialog" aria-labelledby="svc-sdf-title">
				<v-card-title id="svc-sdf-title" class="text-subtitle-1 d-flex align-center flex-wrap" style="gap:8px">
					<span>{{ $t(T + 'title') }}</span>
					<v-spacer />
					<v-btn small text class="svc-sdf-touch" :loading="loading" :disabled="!seeFiles" @click="read()"><v-icon small left>mdi-refresh</v-icon>{{ $t(T + 'refresh') }}</v-btn>
					<v-btn icon class="svc-sdf-touch-icon" :aria-label="$t(T + 'close')" :title="$t(T + 'close')" @click="show = false"><v-icon>mdi-close</v-icon></v-btn>
				</v-card-title>
				<v-card-text class="pt-2">
					<div class="text-body-2 mb-3 svc-sdf-intro">{{ $t(T + 'intro') }}</div>
					<session-notice v-if="needsLogin" kind="session" variant="section" />
					<lock-reason v-else-if="!seeFiles" min="technician" />
					<v-alert v-else-if="error" dense text type="error" class="mb-2 svc-sdf-error" role="alert">{{ error }}</v-alert>

					<template v-if="data && seeFiles">
						<div class="d-flex flex-wrap mb-3 svc-sdf-counts" style="gap:8px">
							<v-chip small label>{{ $t(T + 'c_expected', { n: sum.expected }) }}</v-chip>
							<v-chip small label color="success" outlined>{{ $t(T + 'c_present', { n: sum.present }) }}</v-chip>
							<v-chip small label :color="sum.missing ? 'error' : undefined" :outlined="!!sum.missing">{{ $t(T + 'c_missing', { n: sum.missing }) }}</v-chip>
							<v-chip small label :color="sum.edited ? 'warning' : undefined" :outlined="!!sum.edited">{{ $t(T + 'c_edited', { n: sum.edited }) }}</v-chip>
						</div>

						<v-text-field v-model="filter.q" dense outlined clearable hide-details prepend-inner-icon="mdi-magnify" class="mb-2 svc-sdf-search"
							:label="$t(T + 'search')" :aria-label="$t(T + 'search')" />
						<div class="d-flex flex-wrap mb-3" style="gap:6px" role="group" :aria-label="$t(T + 'filter')">
							<v-chip v-for="s in filters" :key="s" label :outlined="filter.status !== s" :color="filter.status === s ? 'primary' : undefined"
								class="svc-sdf-chip" :aria-pressed="filter.status === s ? 'true' : 'false'" @click="filter.status = s">
								{{ $t(T + 'filter_' + s) }} ({{ counts[s] }})
							</v-chip>
						</div>

						<div v-if="wizardHint" class="svc-sdf-hint mb-3">
							<span class="text-body-2">{{ $t(T + 'missing_hint') }}</span>
							<v-btn small outlined color="primary" class="svc-sdf-touch ml-2" @click="goWizard"><v-icon small left>mdi-clipboard-check-outline</v-icon>{{ $t(T + 'wizard_link') }}</v-btn>
						</div>

						<div v-if="!data.plugins.length" class="text-body-2 svc-sdf-intro">{{ $t(T + 'no_files') }}</div>
						<div v-else-if="!shown.length" class="text-body-2 svc-sdf-intro">{{ $t(T + 'none_match') }}</div>

						<section v-for="p in shown" :key="p.plugin" class="svc-sdf-plugin">
							<button type="button" class="svc-sdf-head" :aria-expanded="isOpen(p) ? 'true' : 'false'" @click="toggle(p)">
								<v-icon small class="mr-1">{{ isOpen(p) ? 'mdi-chevron-down' : 'mdi-chevron-right' }}</v-icon>
								<strong>{{ p.plugin }}</strong>
								<span v-if="p.version" class="text-caption svc-sdf-faint ml-2">{{ $t(T + 'plugin_version', { v: p.version }) }}</span>
								<v-spacer />
								<span class="text-caption svc-sdf-faint mr-2">{{ $t(T + 'plugin_counts', { present: p.counts.present, expected: p.counts.expected }) }}</span>
								<v-chip v-if="p.counts.missing" x-small label color="error" outlined class="mr-1">{{ $t(T + 'st_missing') }} {{ p.counts.missing }}</v-chip>
								<v-chip v-if="p.counts.edited" x-small label color="warning" outlined class="mr-1">{{ $t(T + 'st_edited') }} {{ p.counts.edited }}</v-chip>
							</button>
							<v-simple-table v-if="isOpen(p)" dense class="svc-sdf-table">
								<thead>
									<tr>
										<th class="text-left">{{ $t(T + 'col_path') }}</th>
										<th class="text-left">{{ $t(T + 'col_kind') }}</th>
										<th class="text-left">{{ $t(T + 'col_status') }}</th>
									</tr>
								</thead>
								<tbody>
									<template v-for="f in p.files">
										<tr :key="f.path" class="svc-sdf-row">
											<td>
												<code class="svc-sdf-path">{{ f.path }}</code>
												<v-chip v-if="f.safety" x-small label color="warning" class="ml-1"><v-icon x-small left>mdi-shield-alert-outline</v-icon>{{ $t(T + 'safety') }}</v-chip>
												<div class="text-caption svc-sdf-faint">{{ $t(T + 'used_by') }}: {{ usedBy(f) }}</div>
												<div v-if="f.breaks_if_missing" class="text-caption warning--text">{{ $t(T + 'breaks', { what: f.breaks_if_missing }) }}</div>
											</td>
											<td>
												<v-chip small label outlined :title="kindHelp(f)">{{ kindText(f) }}</v-chip>
											</td>
											<td>
												<v-chip small label outlined :color="color(f)" :title="appliedLine(f)"><v-icon x-small left>{{ icon(f) }}</v-icon>{{ $t(T + statusKey(f)) }}</v-chip>
												<v-chip v-if="wont(f)" x-small label class="ml-1" :title="$t(T + 'created_before_help')">{{ $t(T + 'created_before') }}</v-chip>
												<div v-if="f.applied" class="text-caption svc-sdf-faint mt-1 svc-sdf-applied">{{ appliedLine(f) }}</div>
												<div class="mt-1">
													<v-btn small outlined class="svc-sdf-touch" :aria-label="$t(T + 'open_file') + ': ' + f.path" @click="openFile(f.path)"><v-icon small left>mdi-file-eye-outline</v-icon>{{ $t(T + 'open_file') }}</v-btn>
												</div>
												<div v-if="can(f)" class="mt-1">
													<!-- locked-in-place style: the lock is inside the control; the reason shows only after the person touches it -->
													<span class="svc-sdf-lockwrap" @click="touchLocked">
														<v-btn small text class="svc-sdf-touch" :disabled="!isAdmin" :loading="!!busy[f.path]" @click="toggleDiff(f)">
															<v-icon small left>{{ isAdmin ? (diffs[f.path] ? 'mdi-chevron-up' : 'mdi-chevron-down') : 'mdi-lock-outline' }}</v-icon>{{ diffs[f.path] ? $t(T + 'diff_hide') : $t(T + 'diff_show') }}
														</v-btn>
													</span>
												</div>
											</td>
										</tr>
										<tr v-if="diffs[f.path]" :key="f.path + ':diff'">
											<td colspan="3">
												<div class="text-caption mb-1">{{ $t(T + 'diff_count', stats(f)) }} {{ $t(T + 'diff_help') }}</div>
												<div v-if="diffs[f.path].why" class="text-body-2 mb-1 svc-sdf-why">{{ $t(T + diffs[f.path].why) }}</div>
												<div v-if="!lines(f).length && !diffs[f.path].why" class="text-caption svc-sdf-faint">{{ $t(T + 'diff_none') }}</div>
												<pre v-if="lines(f).length" class="svc-sdf-diff"><span v-for="(l, n) in lines(f)" :key="n" :class="'d-' + l.cls">{{ l.text }}
</span></pre>
											</td>
										</tr>
									</template>
								</tbody>
							</v-simple-table>
						</section>

						<section v-if="data.extras && data.extras.length" class="svc-sdf-plugin mt-3">
							<div class="svc-sdf-head2">{{ $t(T + 'extras_title', { n: data.extras.length }) }}</div>
							<div class="text-caption svc-sdf-faint mb-1">{{ $t(T + 'extras_help') }}</div>
							<div v-for="x in data.extras" :key="x" class="d-flex align-center flex-wrap" style="gap:8px">
								<code class="svc-sdf-path">{{ x }}</code>
								<v-btn small outlined class="svc-sdf-touch" :aria-label="$t(T + 'open_file') + ': ' + x" @click="openFile(x)"><v-icon small left>mdi-file-eye-outline</v-icon>{{ $t(T + 'open_file') }}</v-btn>
							</div>
						</section>
					</template>
					<lock-reason v-if="touched && !isAdmin && seeFiles" op="startup.integrity.restore.preview" need="admin" class="mt-2" />
				</v-card-text>
				<v-card-actions>
					<v-spacer />
					<v-btn text class="svc-sdf-touch" @click="show = false">{{ $t(T + 'close') }}</v-btn>
				</v-card-actions>
			</v-card>
		</v-dialog>
		<v-dialog v-model="viewer.show" max-width="1100" width="100%" scrollable content-class="svc-sdf-dialog">
			<v-card role="dialog" aria-labelledby="svc-sdf-view-title" class="svc-sdf-reader">
				<v-card-title id="svc-sdf-view-title" class="text-subtitle-1 d-flex align-center flex-wrap" style="gap:8px">
					<span>{{ $t(T + 'view_title') }}</span>
					<v-spacer />
					<v-btn icon class="svc-sdf-touch-icon" :aria-label="$t(T + 'view_close')" :title="$t(T + 'view_close')" @click="viewer.show = false"><v-icon>mdi-close</v-icon></v-btn>
				</v-card-title>
				<v-card-text class="pt-2">
					<code class="svc-sdf-path d-block mb-2">{{ viewer.path }}</code>
					<div v-if="viewer.loading" class="text-body-2 svc-sdf-faint">{{ $t(T + 'view_loading') }}</div>
					<v-alert v-else-if="viewer.error" dense text type="error" role="alert" class="svc-sdf-error">{{ viewer.error }}</v-alert>
					<template v-else-if="viewer.view">
						<v-alert dense text :type="alertType" class="mb-2 svc-sdf-headline">
							<div class="text-body-1">{{ headline }}</div>
							<div v-for="(n, i) in noteLines" :key="i" class="text-body-2">{{ n }}</div>
						</v-alert>
						<div class="text-body-2 mb-1 svc-sdf-applied-line"><strong>{{ $t(T + 'view_applied_label') }}</strong> {{ appliedHead }}</div>
						<div class="text-caption svc-sdf-faint mb-2">{{ $t(T + 'view_kind_line', { kind: kindOf(viewer.view), used: usedOf(viewer.view) }) }} {{ $t(T + 'view_meta', { lines: viewer.view.lines, kb: kb }) }}</div>
						<div class="d-flex flex-wrap align-center mb-2" style="gap:8px">
							<v-btn v-if="comparison" small outlined class="svc-sdf-touch svc-sdf-only" :color="viewer.only ? 'primary' : undefined" :aria-pressed="viewer.only ? 'true' : 'false'" @click="viewer.only = !viewer.only">
								<v-icon small left>{{ viewer.only ? 'mdi-eye-outline' : 'mdi-filter-outline' }}</v-icon>{{ viewer.only ? $t(T + 'view_all') : $t(T + 'view_only_changes') }}
							</v-btn>
							<v-btn v-if="canCopy" small outlined class="svc-sdf-touch svc-sdf-copy" @click="copy"><v-icon small left>mdi-content-copy</v-icon>{{ viewer.copied === 'ok' ? $t(T + 'view_copied') : $t(T + 'view_copy') }}</v-btn>
							<span v-if="comparison" class="text-caption svc-sdf-legend" role="group" :aria-label="$t(T + 'view_legend')">
								{{ $t(T + 'view_legend') }}:
								<span class="l-mine">{{ $t(T + 'legend_mine') }}</span>
								<span class="l-factory">{{ $t(T + 'legend_factory') }}</span>
							</span>
						</div>
						<div v-if="viewer.copied === 'fail'" class="text-caption warning--text mb-1">{{ $t(T + 'view_copy_fail') }}</div>
						<div v-if="viewer.view.content === null" class="text-body-2 svc-sdf-faint">{{ $t(T + 'view_nothing') }}</div>
						<div v-else-if="viewer.only && !shownRows.length" class="text-body-2 svc-sdf-faint">{{ $t(T + 'view_no_changes') }}</div>
						<div v-else-if="!shownRows.length" class="text-body-2 svc-sdf-faint">{{ $t(T + 'view_empty') }}</div>
						<div v-else class="svc-sdf-code" role="region" tabindex="0" :aria-label="$t(T + 'view_title')"><template v-for="(r, i) in shownRows"><div v-if="r.gap" :key="i" class="r-gap">{{ $t(T + 'view_hidden', { count: r.count }) }}</div><div v-else :key="i" :class="'r-' + r.flag"><span class="r-n">{{ r.n === null ? '' : r.n }}</span><span class="r-t">{{ r.text }}</span></div></template></div>
					</template>
				</v-card-text>
				<v-card-actions>
					<v-spacer />
					<v-btn text class="svc-sdf-touch" @click="viewer.show = false">{{ $t(T + 'view_close') }}</v-btn>
				</v-card-actions>
			</v-card>
		</v-dialog>
	</span>
</template>

<script>
'use strict'

import { api } from './workshop-api.js'
import { roleMixin } from './role-mixin.js'
import SessionNotice from './SessionNotice.vue'
import LockReason from './LockReason.vue'
import { signedOut } from './workshop-auth.js'
import { errorKind } from './friendly-error.js'
import { blinkLocked } from './lock-attention.js'
import { diffLines, diffStats } from './startup-wizard.js'
import * as sv from './sd-viewer.js'
import { emptyFilter, visible, totals, byStatus, needsLook, canDiff, hasMissing, wontRecreate, statusKey, kindKey, STATUS_COLOR, STATUS_ICON } from './sd-files.js'

export default {
	name: 'SdFilesDialog',
	components: { SessionNotice, LockReason },
	mixins: [roleMixin],
	// everything here was read by the person who left (ESTANDAR 3.3)
	sessionData: ['data', 'diffs', 'needsLogin', 'error', 'touched', 'viewer'],
	data() {
		return { T: 'plugins.WorkshopService.sd_files.', show: false, data: null, filter: emptyFilter(), openMap: {}, diffs: {}, busy: {}, loading: false, needsLogin: false, error: '', touched: false, viewer: { show: false, path: '', loading: false, view: null, error: '', only: false, copied: '' } };
	},
	computed: {
		seeFiles() { return this.atLeast('technician'); },
		isAdmin() { return this.atLeast('admin'); },
		filters() { return ['all', 'ok', 'edited', 'missing', 'not_yet', 'attention']; },
		plugins() { return this.data ? this.data.plugins : []; },
		shown() { return visible(this.plugins, this.filter); },
		sum() { return totals(this.plugins); },
		counts() { return byStatus(this.plugins); },
		wizardHint() { return hasMissing(this.plugins); },
		comparison() { return sv.hasComparison(this.viewer.view); },
		canCopy() { return !!this.viewer.view && typeof this.viewer.view.content === 'string'; },
		alertType() { const k = sv.tone(this.viewer.view); return k === 'success' ? 'success' : k === 'warning' ? 'warning' : k === 'grey' ? 'info' : 'error'; },
		headline() { return sv.headline(this.viewer.view, this.tt); },
		noteLines() { return sv.notes(this.viewer.view, this.tt); },
		appliedHead() { return sv.appliedText(this.viewer.view && this.viewer.view.applied, this.tt); },
		kb() { const n = (this.viewer.view && this.viewer.view.size) || 0; return n < 1024 ? (n ? '<1' : '0') : Math.round(n / 1024); },
		shownRows() { return sv.visibleRows(sv.rows(this.viewer.view), this.viewer.only && this.comparison); },
		filtering() { return this.filter.status !== 'all' || !!String(this.filter.q || '').trim(); }
	},
	methods: {
		statusKey,
		tt(key, p) { return this.$t(this.T + key, p); },
		appliedLine(f) { return f.applied ? sv.appliedText(f.applied, this.tt) : ''; },
		kindOf(v) { const k = kindKey(v); return k ? this.$t(this.T + k) : v.kind === 'unknown' ? this.$t(this.T + 'extras_kind') : v.kind; },
		usedOf(v) { return v.used_by && v.used_by.length ? v.used_by.join(', ') : this.$t(this.T + 'used_by_none'); },
		async openFile(path) {
			const gen = this._gen;
			this.viewer = { show: true, path, loading: true, view: null, error: '', only: false, copied: '' };
			try {
				const r = await api('startup.file.view', { path }, { quiet: true });
				if (gen !== this._gen) return;
				this.viewer.view = r;
				this.viewer.only = sv.hasComparison(r) && sv.changedCount(r) > 0;
			} catch (e) {
				if (gen !== this._gen) return;
				this.viewer.error = sv.friendlyError(e, this.tt);
			} finally {
				if (gen === this._gen) this.viewer.loading = false;
			}
		},
		async copy() {
			const text = sv.copyText(this.viewer.view);
			let ok = false;
			try {
				if (navigator.clipboard && navigator.clipboard.writeText) { await navigator.clipboard.writeText(text); ok = true; }
			} catch (e) { ok = false; }
			if (!ok) {
				const ta = document.createElement('textarea');
				ta.value = text;
				ta.setAttribute('readonly', '');
				ta.style.position = 'fixed';
				ta.style.opacity = '0';
				document.body.appendChild(ta);
				ta.select();
				try { ok = document.execCommand('copy'); } catch (e) { ok = false; }
				document.body.removeChild(ta);
			}
			this.viewer.copied = ok ? 'ok' : 'fail';
		},
		can: canDiff,
		wont: wontRecreate,
		color(f) { return STATUS_COLOR[f.status] || 'warning'; },
		icon(f) { return STATUS_ICON[f.status] || STATUS_ICON.attention; },
		kindText(f) { const k = kindKey(f); return k ? this.$t(this.T + k) : f.kind; },
		kindHelp(f) { return kindKey(f) ? this.$t(this.T + 'kind_help_' + f.kind) : ''; },
		usedBy(f) { return f.used_by && f.used_by.length ? f.used_by.join(', ') : this.$t(this.T + 'used_by_none'); },
		lines(f) { return diffLines(this.diffs[f.path].diff); },
		stats(f) { return diffStats(this.diffs[f.path].diff); },
		// a search or a filter opens every plugin that has a match; otherwise only the ones with something to look at, unless the person chose
		isOpen(p) {
			if (this.filtering) return true;
			return p.plugin in this.openMap ? this.openMap[p.plugin] : needsLook(p);
		},
		toggle(p) { this.$set(this.openMap, p.plugin, !this.isOpen(p)); },
		touchLocked() {
			if (this.isAdmin) return;
			this.touched = true;
			this.$nextTick(() => blinkLocked(this.$el, signedOut()));
		},
		goWizard() {
			this.show = false;
			this.$nextTick(() => {
				const el = document.querySelector('.svc-wiz');
				if (el && el.scrollIntoView) el.scrollIntoView({ behavior: 'smooth', block: 'start' });
			});
		},
		onSessionChange() { this._gen++; },
		async toggleDiff(f) {
			if (!this.isAdmin) return;
			if (this.diffs[f.path]) { this.$delete(this.diffs, f.path); return; }
			const gen = this._gen;
			this.$set(this.busy, f.path, true);
			try {
				const r = await api('startup.integrity.restore.preview', { path: f.path }, { quiet: true });
				if (gen === this._gen) this.$set(this.diffs, f.path, { diff: (r && r.diff) || '', why: sv.diffWhy(r) });
			} catch (e) {
				if (gen === this._gen) this.error = sv.friendlyError(e, this.tt);
			} finally {
				this.$delete(this.busy, f.path);
			}
		},
		async read() {
			if (!this.seeFiles) return;
			const gen = this._gen;
			this.loading = true;
			this.error = '';
			try {
				const d = await api('startup.files', {}, { noLogin: true, quiet: true });
				if (gen !== this._gen) return;
				this.data = d;
				this.diffs = {};
				this.needsLogin = false;
			} catch (e) {
				if (gen !== this._gen) return;
				this.data = null;
				const kind = errorKind(e);
				this.needsLogin = kind === 'login' || (kind === 'role' && signedOut());
				this.error = this.needsLogin || kind === 'role' ? '' : sv.friendlyError(e, this.tt);
			} finally {
				if (gen === this._gen) this.loading = false;
			}
		}
	},
	created() { this._gen = 0; },
	watch: {
		seeFiles(v) { if (v && this.show && !this.data) this.read(); },
		// the button only sets `show`, and v-dialog does not emit input for that: read when it opens
		show(v) { if (v) this.read(); }
	}
};
</script>

<style scoped>
.svc-sdf-intro { color: var(--tp-faint, #9e9e9e); max-width: 70ch; }
.svc-sdf-faint { color: var(--tp-faint, #9e9e9e); }
.svc-sdf-touch { min-height: 44px; }
.svc-sdf-touch-icon { min-width: 44px; min-height: 44px; }
.svc-sdf-chip { min-height: 44px; display: inline-flex; align-items: center; }
.svc-sdf-search { max-width: 480px; }
.svc-sdf-hint { padding: 8px; border-left: 3px solid #FB8C00; display: flex; align-items: center; flex-wrap: wrap; row-gap: 6px; }
.svc-sdf-plugin { margin-top: 10px; }
.svc-sdf-head { display: flex; align-items: center; width: 100%; min-height: 48px; padding: 4px 8px; text-align: left; border-bottom: 1px solid var(--wf-line); font-size: 14px; }
.svc-sdf-head2 { font-size: 13px; font-weight: 600; padding-bottom: 4px; border-bottom: 1px solid var(--wf-line); }
.svc-sdf-row td { padding-top: 6px !important; padding-bottom: 6px !important; vertical-align: top; }
.svc-sdf-path { font-size: 13px; overflow-wrap: anywhere; }
.svc-sdf-lockwrap { display: inline-block; }
.svc-sdf-diff { font-size: 12px; line-height: 1.45; max-height: 320px; overflow: auto; padding: 8px; border-radius: 4px; background: rgba(128, 128, 128, 0.1); white-space: pre; }
.svc-sdf-diff .d-add { color: #2e7d32; display: block; }
.svc-sdf-diff .d-del { color: #c62828; display: block; }
.svc-sdf-diff .d-hunk, .svc-sdf-diff .d-file { color: #1565c0; display: block; }
.svc-sdf-diff .d-ctx { display: block; }
.svc-sdf-why { padding: 6px 8px; border-left: 3px solid #1565C0; }
.svc-sdf-code { font-family: monospace; font-size: 13px; line-height: 1.5; max-height: 55vh; overflow: auto; border-radius: 4px; background: rgba(128, 128, 128, 0.1); padding: 4px 0; }
.svc-sdf-code > div { display: flex; white-space: pre-wrap; overflow-wrap: anywhere; padding: 0 8px 0 0; }
.svc-sdf-code .r-n { flex: 0 0 4.5em; text-align: right; padding-right: 10px; color: var(--tp-faint, #9e9e9e); user-select: none; }
.svc-sdf-code .r-t { flex: 1 1 auto; }
.svc-sdf-code .r-changed, .svc-sdf-code .r-added { background: rgba(251, 140, 0, 0.22); border-left: 3px solid #FB8C00; }
.svc-sdf-code .r-factory { background: rgba(21, 101, 192, 0.18); border-left: 3px solid #1565C0; }
.svc-sdf-code .r-gap { justify-content: center; padding: 6px 0; color: var(--tp-faint, #9e9e9e); font-family: inherit; font-size: 12px; background: rgba(128, 128, 128, 0.12); }
.svc-sdf-legend .l-mine, .svc-sdf-legend .l-factory { padding: 2px 8px; margin-left: 6px; border-radius: 3px; }
.svc-sdf-legend .l-mine { background: rgba(251, 140, 0, 0.22); border-left: 3px solid #FB8C00; }
.svc-sdf-legend .l-factory { background: rgba(21, 101, 192, 0.18); border-left: 3px solid #1565C0; }
</style>
