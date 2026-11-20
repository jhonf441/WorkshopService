<template>
	<!-- Setup > Files: the files each plugin creates or uses on the SD card and how they are now, one fold per plugin (the ones that need a look
	     open). A technician reads any file; an administrator restores the factory copy of a workshop file: first the preview with the differences
	     (nothing is written), then a level 3 dialog. Prop: active (this tab is in view). -->
	<div class="sv-setup-files">
		<section class="sv-card" aria-labelledby="sv-sf-title" data-card="files">
			<div class="sv-card-head">
				<h2 id="sv-sf-title"><span class="mdi mdi-file-multiple-outline sv-ico" aria-hidden="true" />{{ t('setup.files_title') }}</h2>
			</div>
			<p class="sv-lead">{{ t('configPackage.files_intro') }}</p>
			<state-legend kind="files" />
			<sv-zone :status="status" :error="files.error" :lock="files.lock" :updated="updated" refreshable :empty-title="t('configPackage.files_empty')" @retry="files.reload()" @refresh="files.reload()" @sign-in="signIn">
				<div class="sv-tools">
					<label class="sv-field"><span class="mdi mdi-magnify sv-ico sv-ico-s" aria-hidden="true" /><input v-model="filter.q" type="search" :placeholder="t('configPackage.files_search')" :aria-label="t('configPackage.files_search')"></label>
					<label class="sv-check"><input v-model="filter.only" type="checkbox"><span>{{ t('configPackage.files_only', { n: attention }) }}</span></label>
				</div>
				<p v-if="!groups.length" class="sv-quiet" role="status" data-part="none">{{ t('configPackage.files_none') }}</p>
				<details v-for="p in groups" :key="p.plugin" class="sv-fold" :open="p.attention > 0 || !!filter.q" :data-open="p.attention > 0 || !!filter.q ? '' : null" :data-plugin="p.plugin">
					<summary>
						<span class="mdi mdi-chevron-right sv-ico sv-chev" aria-hidden="true" />
						<span class="sv-fold-name">{{ p.plugin }}</span>
						<span class="sv-fold-sum">{{ t('configPackage.plugin_version', { v: p.version }) }} · {{ tc('configPackage.plugin_counts', p.counts.expected, { present: p.counts.present, expected: p.counts.expected }) }}</span>
						<span v-if="p.attention" class="sv-word" data-level="warn">{{ t('configPackage.plugin_attention', { n: p.attention }) }}</span>
					</summary>
					<div class="sv-fold-body">
						<ul class="sv-rows">
							<sv-action-row v-for="f in p.files" :key="f.path" icon="mdi-file-outline" :name="f.name" :desc="f.dir + f.name" :data-file="f.path">
								<p v-if="f.breaks_if_missing" class="sv-row-desc">{{ t('sd_files.breaks', { what: f.breaks_if_missing }) }}</p>
								<p class="sv-row-desc">{{ kindText(f) }} · {{ t('sd_files.used_by') }}: {{ usedBy(f) }}<span v-if="f.safety" class="sv-tag">{{ t('sd_files.safety') }}</span></p>
								<template #control>
									<span class="sv-state" :data-level="LEVEL[f.fileState]" :data-file="f.path" :title="t('configPackage.fsh_' + f.fileState)"><span class="mdi sv-ico sv-ico-s" :class="LEVEL_ICON[LEVEL[f.fileState]]" aria-hidden="true" />{{ t('configPackage.fs_' + f.fileState) }}</span>
									<button type="button" class="sv-btn" data-act="view" :aria-label="t('configPackage.view_file') + ': ' + f.name" @click="view(f.path)">{{ t('configPackage.view_file') }}</button>
									<button v-if="restorable(f)" type="button" class="sv-btn" data-act="changes" :disabled="!mayRestore || stale" :aria-label="t('configPackage.changes_show') + ': ' + f.name" @click="togglePreview(f)">
										<span v-if="!mayRestore" class="mdi mdi-lock-outline sv-ico sv-ico-s" aria-hidden="true" />{{ t(previews[f.path] ? 'configPackage.changes_hide' : 'configPackage.changes_show') }}
									</button>
								</template>
								<template v-if="previews[f.path]" #body>
									<div v-if="previews[f.path]" class="sv-changes" data-part="preview">
										<p v-for="r in previews[f.path].refusals || []" :key="r.code" class="sv-field-error" role="status"><span class="mdi mdi-alert-outline sv-ico sv-ico-s" aria-hidden="true" />{{ refusal(r) }}</p>
										<template v-if="diff(f).length">
											<p class="sv-quiet" data-part="diff-effect">{{ diffText(f) }} {{ t('sd_files.diff_help') }}</p>
											<pre class="sv-diff"><span v-for="(l, i) in diff(f)" :key="i" :class="'d-' + l.cls">{{ l.text }}
</span></pre>
										</template>
										<p v-else-if="!(previews[f.path].refusals || []).length" class="sv-quiet">{{ t('sd_files.diff_none') }}</p>
										<div v-if="previews[f.path].allowed" class="sv-row-ctl">
											<button type="button" class="sv-btn sv-danger" data-act="restore" :disabled="restoreFile.busy()" @click="askRestore(f)">{{ t('configPackage.restore') }}</button>
											<span class="sv-quiet">{{ t('configPackage.restore_help') }}</span>
										</div>
									</div>
								</template>
							</sv-action-row>
						</ul>
					</div>
				</details>
				<div v-if="note" class="sv-row-out" :data-kind="note.ok ? 'done' : 'error'" :role="note.ok ? 'status' : 'alert'" data-part="note"><span class="mdi sv-ico sv-ico-s" :class="note.ok ? 'mdi-check-circle-outline' : 'mdi-close-circle-outline'" aria-hidden="true" />{{ note.text }}</div>
				<p v-if="counts.missing > 0" class="sv-quiet"><a class="sv-btn sv-text" :href="nav.href({ s: 'setup', t: 'changes' })" @click="follow($event)">{{ t('configPackage.files_hint_missing') }} {{ t('configPackage.files_goto_apply') }}</a></p>
			</sv-zone>
			<sv-reason :lock="lockOf(['startup.integrity.restore'])" @sign-in="signIn" />
		</section>

		<sv-text-view ref="reader" :open="viewer.show" :title="viewer.path" :rows="shownRows" :loading="viewer.loading" :error="viewer.error" :gap-text="gapText" :block-text="blockText" :legend="t('sd_files.view_legend')" @close="viewer.show = false" @retry="view(viewer.path)" @copy="copyFile" @download="downloadFile">
			<template #head>
				<template v-if="viewer.view">
					<p data-part="view-head"><b>{{ headline }}</b></p>
					<p v-for="(n, i) in notes" :key="i" class="sv-quiet">{{ n }}</p>
					<p class="sv-quiet">{{ appliedText }}</p>
					<p v-if="viewer.view && !shownRows.length" class="sv-quiet">{{ t(viewer.view.content === '' ? 'sd_files.view_empty' : 'sd_files.view_nothing') }}</p>
				</template>
			</template>
			<template #tools>
				<label v-if="comparison" class="sv-check sv-tv-only" :title="t('sd_files.view_only_help')"><input v-model="viewer.only" type="checkbox"><span>{{ t('sd_files.view_only_changes') }}</span></label>
			</template>
			<template #legend>
				<div v-if="viewer.view && viewer.view.present && viewer.view.content !== null" class="sv-tv-legend-box" data-part="diff-legend">
					<p v-if="comparison" class="sv-quiet sv-tv-legend">
						<span class="sv-tv-key d-changed"><b>~</b>{{ t('sd_files.key_changed') }}</span><span class="sv-tv-key d-added"><b>+</b>{{ t('sd_files.key_added') }}</span><span class="sv-tv-key d-factory"><b>-</b>{{ t('sd_files.key_factory') }}</span><span class="sv-tv-key">{{ t('sd_files.key_same') }}</span><span class="sv-tv-key sv-comment">{{ t('sd_files.key_comment') }}</span>
					</p>
					<p v-else class="sv-quiet sv-tv-legend" data-part="no-factory">{{ t('sd_files.key_no_factory') }}</p>
					<div v-if="comparison && editedRanges.length" class="sv-chips" data-part="edited-chips">
						<span class="sv-quiet">{{ t('sd_files.edited_chips') }}</span>
						<button v-for="r in editedRanges" :key="r[0]" type="button" class="sv-btn" :class="{ 'sv-on': activeLine === r[0] }" :aria-pressed="activeLine === r[0] ? 'true' : 'false'" :data-line="r[0]" @click="goTo(r)">{{ rangeLabel(r) }}</button>
					</div>
				</div>
			</template>
		</sv-text-view>

		<sv-confirm-dialog :confirm="restoreFile.confirm" :title="t('setup.restore_title')" :text="t('setup.restore_text')" :object="{ name: target.name, context: target.dir }" :verb="t('configPackage.restore')" danger
			@accept="restoreFile.accept()" @cancel="restoreFile.cancel()" />
	</div>
</template>

<script>
import { call } from '../../core/api/call.js'
import { locale, saveText } from '../../core/dwc.js'
import { copyText } from '../../copy.js'
import { startupFiles } from '../../core/resources.js'
import { want } from '../../core/store/session.js'
import { restoreFile } from '../../core/actions/setup.js'
import { rowsMixin } from '../../core/rows-mixin.js'
import { time } from '../../core/format/dates.js'
import { canRestore, emptyFilter, fileCounts, groupFiles, needsAttention, refusalKey } from '../../package-view.js'
import { diffLines, diffStats } from '../../package-wizard.js'
import { kindKey } from '../../sd-files.js'
import * as sv from '../../sd-viewer.js'
import StateLegend from './StateLegend.vue'
import SvActionRow from '../../ui/SvActionRow.vue'
import SvConfirmDialog from '../../ui/SvConfirmDialog.vue'
import SvReason from '../../ui/SvReason.vue'
import SvTextView from '../../ui/SvTextView.vue'
import SvZone from '../../ui/SvZone.vue'

const LEVEL = { identical: 'ok', present: 'ok', missing: 'error', edited: 'warn', not_yet: 'rest', attention: 'warn' }
const LEVEL_ICON = { ok: 'mdi-check-circle-outline', warn: 'mdi-alert-outline', error: 'mdi-close-circle-outline', rest: 'mdi-clock-outline' }

export default {
	name: 'FilesTab',
	components: { StateLegend, SvActionRow, SvConfirmDialog, SvReason, SvTextView, SvZone },
	mixins: [rowsMixin],
	inject: { nav: { from: 'svNav', default: () => ({ go() {}, href: () => '#' }) } },
	props: { active: { type: Boolean, default: false } },
	data() {
		return { activeLine: 0, files: startupFiles, restoreFile, filter: emptyFilter(), previews: {}, note: null, target: { name: '', dir: '' }, viewer: { show: false, path: '', loading: false, view: null, error: '', only: false }, LEVEL, LEVEL_ICON }
	},
	computed: {
		plugins() {
			return (this.files.data && this.files.data.plugins) || []
		},
		groups() {
			return groupFiles(this.plugins, this.filter)
		},
		counts() {
			return fileCounts(this.plugins)
		},
		attention() {
			return this.plugins.reduce((n, p) => n + (p.files || []).filter(needsAttention).length, 0)
		},
		status() {
			return this.files.status === 'ready' && !this.plugins.length ? 'empty' : this.files.status
		},
		updated() {
			return this.files.loadedAt ? time(this.files.loadedAt, locale()).slice(0, 5) : ''
		},
		mayRestore() {
			return this.perm('startup.integrity.restore').state === 'ok'
		},
		comparison() {
			return sv.hasComparison(this.viewer.view)
		},
		headline() {
			return sv.headline(this.viewer.view, this.tt, this.tcc)
		},
		notes() {
			return sv.notes(this.viewer.view, this.tt, this.tcc)
		},
		appliedText() {
			return sv.appliedText(this.viewer.view && this.viewer.view.applied, this.tt)
		},
		// the lines that differ from the factory copy, as ranges [from, to] of the file on the card
		editedRanges() {
			return sv.changedRanges(this.viewer.view)
		},
		shownRows() {
			return sv.visibleRows(sv.markBlocks(sv.rows(this.viewer.view)), this.viewer.only && this.comparison).map(r => (r.gap ? { flag: 'gap', count: r.count, n: null, text: '' } : r))
		}
	},
	watch: {
		active: { immediate: true, handler(on) { if (on) { want(['startup.files', 'startup.file.view', 'startup.integrity.restore']); this.files.show() } else this.files.hide() } },
		// what the service holds changed (a file was restored): the previews belonged to the old state
		'files.loadedAt'() { this.previews = {} },
		'restoreFile.state'(now) {
			if (now === 'done') this.note = { ok: true, text: this.t('configPackage.restored', { name: this.target.name, backup: (this.restoreFile.data && this.restoreFile.data.backup_path) || '-' }) }
			else if (now === 'error' && this.restoreFile.error && this.restoreFile.error.kind !== 'session' && this.restoreFile.error.kind !== 'role') this.note = { ok: false, text: this.t('configPackage.restore_failed', { name: this.target.name, why: this.restoreFile.error.message }) }
		}
	},
	methods: {
		// a chip of the edited lines: when the lines are inside a stretch of equal lines that "only what changed" hides, the stretch is opened first; the chip stays marked until another is touched
		async goTo(r) {
			this.activeLine = r[0]
			if (!this.shownRows.some(x => x.n >= r[0] && x.n <= r[1])) {
				this.viewer.only = false
				await this.$nextTick()
			}
			this.$refs.reader.jumpToRange(r[0], r[1])
		},
		rangeLabel(r) {
			return this.tt(r[0] === r[1] ? 'range_one' : 'range_many', { n: r[0], from: r[0], to: r[1] })
		},
		blockText(id) {
			return this.t('sd_files.view_block', { id })
		},
		gapText(count) {
			return this.tc('sd_files.view_hidden', count, { count })
		},
		copyFile() {
			copyText(sv.copyText(this.viewer.view))
		},
		downloadFile() {
			saveText(String(this.viewer.path).split('/').pop() || 'file.txt', sv.copyText(this.viewer.view))
		},
		tt(key, p) {
			return this.t('sd_files.' + key, p)
		},
		tcc(key, n, p) {
			return this.tc('sd_files.' + key, n, p)
		},
		follow(e) {
			if (e && (e.ctrlKey || e.metaKey || e.shiftKey || e.altKey || e.button > 0)) return
			if (e && typeof e.preventDefault === 'function') e.preventDefault()
			this.nav.go({ s: 'setup', t: 'changes' })
		},
		restorable(f) {
			return canRestore(f)
		},
		usedBy(f) {
			return f.used_by && f.used_by.length ? f.used_by.join(', ') : this.t('sd_files.used_by_none')
		},
		kindText(f) {
			const k = kindKey(f)
			return k ? this.t('sd_files.' + k.replace(/^sd_files\./, '')) : f.kind
		},
		refusal(r) {
			const k = refusalKey(r.code)
			return k ? this.t('configPackage.' + k) : r.reason || r.code
		},
		diff(f) {
			const p = this.previews[f.path]
			return p ? diffLines(p.diff) : []
		},
		diffText(f) {
			const s = diffStats(this.previews[f.path].diff)
			return this.t('sd_files.diff_count', { del: this.tc('sd_files.diff_removed', s.del, { n: s.del }), add: this.tc('sd_files.diff_added', s.add, { n: s.add }) })
		},
		async togglePreview(f) {
			if (!this.mayRestore) return
			if (this.previews[f.path]) { this.$delete(this.previews, f.path); return }
			try {
				const r = await call('startup.integrity.restore.preview', { path: f.path }, { quiet: true })
				this.$set(this.previews, f.path, r.data || {})
			} catch (e) {
				this.note = { ok: false, text: this.t('configPackage.restore_failed', { name: f.name, why: e.message }) }
			}
		},
		askRestore(f) {
			const pv = this.previews[f.path]
			if (!pv || !pv.allowed) return
			this.note = null
			this.target = { name: f.name, dir: f.dir }
			this.restoreFile.run({ path: f.path, expected_sha: pv.expected_sha, apply: true })
		},
		async view(path) {
			const mine = { show: true, path, loading: true, view: null, error: '', only: false }
			this.viewer = mine
			try {
				const r = await call('startup.file.view', { path }, { quiet: true })
				if (this.viewer !== mine) return
				mine.view = r.data
				mine.only = sv.hasComparison(r.data) && sv.changedCount(r.data) > 0
			} catch (e) {
				if (this.viewer !== mine) return
				mine.error = sv.friendlyError(e, this.tt)
			}
			mine.loading = false
		}
	}
}
</script>
