<template>
	<!-- Data > Backups: when the last copy was made and when the next one is, the notices that explain a problem next to what they explain, a
	     copy now, the settings (saved by block, never on change), the copies with what happens to each, and where they are kept (moving them
	     is a level 3 dialog). A visitor reads it as state. Prop: active (this tab is in view). -->
	<div class="sv-data-backups">
		<div v-for="n in notes" :key="n.id" class="sv-note" :data-level="n.level" :role="n.level === 'error' ? 'alert' : 'note'" :data-note="n.id">
			<span class="mdi sv-ico" :class="n.level === 'error' ? 'mdi-close-circle-outline' : n.level === 'info' ? 'mdi-information-outline' : 'mdi-alert-outline'" aria-hidden="true" />
			<span>{{ t('data.note_' + n.id) }}<template v-if="n.id === 'failing' || n.id === 'late'"> <a class="sv-btn sv-text" :href="nav.href({ s: 'health', t: 'processes' })" @click="follow($event, { s: 'health', t: 'processes' })">{{ t('data.note_see_process') }}</a></template></span>
		</div>

		<section class="sv-card" aria-labelledby="sv-db-title" data-card="copies">
			<div class="sv-card-head"><h2 id="sv-db-title"><span class="mdi mdi-database-arrow-down-outline sv-ico" aria-hidden="true" />{{ t('data.copies_title') }}</h2></div>
			<sv-zone :status="status.status" :error="status.error" :lock="status.lock" :updated="updated" refreshable :empty-title="t('data.db_none')" @retry="status.reload()" @refresh="status.reload()" @sign-in="signIn">
				<div class="sv-stats">
					<div class="sv-stat" data-stat="last" :data-level="r.late ? 'warn' : null"><b>{{ lastText }}</b><span>{{ lastNote }}</span></div>
					<div class="sv-stat" data-stat="next"><b>{{ nextText }}</b><span>{{ t('data.stat_next') }}</span></div>
					<div class="sv-stat" data-stat="amount"><b>{{ r.amount || 0 }}</b><span>{{ t('data.stat_amount', { mb: r.mb_total || 0 }) }}</span></div>
					<div class="sv-stat" data-stat="free"><b>{{ r.free_gb === undefined || r.free_gb === null ? '–' : r.free_gb + ' GB' }}</b><span>{{ t('data.stat_free') }}</span></div>
				</div>
				<ul class="sv-rows">
					<sv-action-row icon="mdi-database-arrow-down-outline" :name="t('data.now_name')" :desc="t('data.now_desc')" :action="dbBackup" :permission="perm('db.backup')" :stale="stale" :label="t('data.now_label')" @run="dbBackup.run()" @retry="dbBackup.run()">
						<p v-if="dbBackup.state === 'done' && dbBackup.data" class="sv-row-desc" role="status" data-part="backup-done">{{ t('data.now_done', { file: dbBackup.data.file, mb: dbBackup.data.mb }) }}</p>
						<template #help><sv-help v-bind="help('now', 'data')" /></template>
					</sv-action-row>
				</ul>
				<sv-reason :lock="lockOf(['db.backup'])" @sign-in="signIn" />
			</sv-zone>
		</section>

		<section v-if="status.data && status.data.backup" class="sv-card" aria-labelledby="sv-db-set" data-card="settings">
			<div class="sv-card-head"><h2 id="sv-db-set"><span class="mdi mdi-cog-outline sv-ico" aria-hidden="true" />{{ t('data.settings_title') }}</h2></div>
			<form class="sv-fgrid" @submit.prevent="save">
				<div class="sv-fcell sv-fcell-wide">
					<sv-switch :checked="draft.auto" :word="t(draft.auto ? 'data.auto_on' : 'data.auto_off')" :label="t('data.auto_label')" :disabled="!mayEdit" @toggle="draft.auto = !draft.auto" />
				</div>
				<div class="sv-fcell" data-field="daily">
					<label class="sv-label" for="sv-db-daily">{{ t('data.daily_label') }}</label>
					<sv-select id="sv-db-daily" v-model="draft.daily" :options="dailyOptions" :disabled="!mayEdit" />
				</div>
				<div class="sv-fcell" data-field="weekly">
					<label class="sv-label" for="sv-db-weekly">{{ t('data.weekly_label') }}</label>
					<sv-select id="sv-db-weekly" v-model="draft.weekly" :options="weeklyOptions" :disabled="!mayEdit" />
				</div>
				<p class="sv-hint sv-fcell-wide" data-part="weekly-hint">{{ t('data.weekly_hint') }}</p>
				<div class="sv-fcell sv-fcell-wide" data-field="mirror">
					<label class="sv-label" for="sv-db-mirror">{{ t('data.mirror_label') }}</label>
					<sv-select id="sv-db-mirror" v-model="draft.mirror" :options="mirrorOptions" :disabled="!mayEdit" @focusin.native="readPlaces" />
				</div>
				<div class="sv-fbar sv-fcell-wide">
					<button type="submit" class="sv-btn sv-main" :class="{ 'sv-save-hot': hasUnsaved }" data-act="save-settings" :disabled="!mayEdit || stale || dbSettings.busy() || !dirty">{{ t('data.settings_save') }}</button>
					<span class="sv-quiet">{{ t(hasUnsaved ? 'data.settings_unsaved' : 'data.settings_nothing') }}</span>
				</div>
				<p v-if="problem" class="sv-field-error" role="alert" data-part="settings-problem"><span class="mdi mdi-alert-outline sv-ico sv-ico-s" aria-hidden="true" />{{ t('data.settings_invalid') }}</p>
				<div v-if="dbSettings.state === 'done'" class="sv-row-out" data-kind="done" role="status"><span class="mdi mdi-check-circle-outline sv-ico sv-ico-s" aria-hidden="true" />{{ t('data.settings_done') }}</div>
				<div v-else-if="dbSettings.state === 'error' && dbSettings.error && dbSettings.error.kind !== 'session' && dbSettings.error.kind !== 'role'" class="sv-row-out" data-kind="error" role="alert"><span class="mdi mdi-close-circle-outline sv-ico sv-ico-s" aria-hidden="true" />{{ t('data.not_saved') }} {{ dbSettings.error.message }}</div>
			</form>
			<sv-reason :lock="lockOf(['db.settings'])" @sign-in="signIn" />
		</section>

		<section v-if="status.data && status.data.backup" class="sv-card" aria-labelledby="sv-db-list" data-card="list">
			<div class="sv-card-head"><h2 id="sv-db-list"><span class="mdi mdi-file-multiple-outline sv-ico" aria-hidden="true" />{{ t('data.list_title') }}</h2><span class="sv-quiet">{{ t('data.list_count', { shown: copies.length, total: r.amount || 0 }) }}</span></div>
			<p v-if="!copies.length" class="sv-quiet" role="status" data-part="no-copies">{{ t('data.list_none') }}</p>
			<table v-else class="sv-table">
				<caption class="sv-vh">{{ t('data.list_title') }}</caption>
				<thead><tr><th scope="col">{{ t('data.col_file') }}</th><th scope="col">{{ t('data.col_date') }}</th><th scope="col" class="sv-num">{{ t('data.col_size') }}</th><th scope="col">{{ t('data.col_state') }}</th><th scope="col">{{ t('data.col_actions') }}</th></tr></thead>
				<tbody>
					<tr v-for="c in copies" :key="c.file" :data-copy="c.file">
						<th scope="row" :data-label="t('data.col_file')"><code class="sv-code">{{ c.file }}</code></th>
						<td :data-label="t('data.col_date')">{{ dateOf(c.date) }}</td>
						<td class="sv-num" :data-label="t('data.col_size')">{{ c.mb }} MB</td>
						<td :data-label="t('data.col_state')"><span class="sv-word" :data-level="c.state === 'kept' ? 'ok' : c.state === 'goes' ? 'warn' : 'rest'">{{ stateText(c) }}</span></td>
						<td :data-label="t('data.col_actions')">
							<div class="sv-row-ctl">
								<button type="button" class="sv-btn" data-act="keep" :disabled="!mayKeep || stale || dbKeep.busy()" :aria-label="t(c.kept ? 'data.release_of' : 'data.keep_of', { file: c.file })" @click="dbKeep.run({ file: c.file, keep: !c.kept })">{{ t(c.kept ? 'data.release' : 'data.keep') }}</button>
								<button v-if="downloadable" type="button" class="sv-btn" data-act="download" :disabled="downloading === c.file" :aria-label="t('data.download_of', { file: c.file })" @click="download(c.file)"><span class="mdi mdi-download sv-ico sv-ico-s" aria-hidden="true" /></button>
							</div>
						</td>
					</tr>
				</tbody>
			</table>
			<p v-if="r.amount > copies.length" class="sv-quiet" data-part="list-note">{{ t('data.list_note', { n: copies.length }) }}</p>
			<div v-if="dbKeep.state === 'error' && dbKeep.error && dbKeep.error.kind !== 'session' && dbKeep.error.kind !== 'role'" class="sv-row-out" data-kind="error" role="alert"><span class="mdi mdi-close-circle-outline sv-ico sv-ico-s" aria-hidden="true" />{{ t('data.not_done') }} {{ dbKeep.error.message }}</div>
			<div v-if="downloadError" class="sv-row-out" data-kind="error" role="alert" data-part="download-error"><span class="mdi mdi-close-circle-outline sv-ico sv-ico-s" aria-hidden="true" />{{ t('data.download_failed') }}</div>
			<sv-reason :lock="lockOf(['db.keep'])" @sign-in="signIn" />
		</section>

		<section v-if="status.data && status.data.backup" class="sv-card" aria-labelledby="sv-db-where" data-card="where">
			<div class="sv-card-head"><h2 id="sv-db-where"><span class="mdi mdi-folder-outline sv-ico" aria-hidden="true" />{{ t('data.where_title') }}</h2></div>
			<ul class="sv-rows">
				<sv-action-row icon="mdi-folder-outline" :name="t('data.folder_name')" :desc="t('data.folder_desc')" :action="dbFolder" :permission="perm('db.folder')" :stale="stale" :label="t('data.folder_change')" @run="openPlaces" @retry="openPlaces">
					<span class="sv-value"><code class="sv-code" data-part="folder">{{ r.folder }}</code></span>
					<template #help><sv-help v-bind="help('folder', 'data')" /></template>
				</sv-action-row>
				<sv-action-row v-if="r.previous > 0" icon="mdi-delete-outline" :name="t('data.previous_name')" :desc="tc('data.previous_desc', r.previous, { n: r.previous, folder: r.folder_previous || '' })" :action="dbDeletePrevious" :permission="perm('db.delete_previous')" :stale="stale" :label="t('data.previous_delete')" danger @run="dbDeletePrevious.run()" @retry="dbDeletePrevious.run()" />
			</ul>
			<div v-if="choosing" class="sv-places" data-part="places">
				<p class="sv-quiet">{{ t('data.places_pick') }}</p>
				<p v-if="places.status === 'loading'" class="sv-quiet" role="status">{{ t('data.places_reading') }}</p>
				<p v-else-if="!moves.length" class="sv-quiet" role="status" data-part="no-places">{{ t('data.places_none') }}</p>
				<div v-for="p in moves" :key="p.folder" class="sv-row-ctl">
					<span class="sv-value"><b>{{ p.name }}</b> <code class="sv-code">{{ p.folder }}</code> <span class="sv-quiet">{{ t('data.places_free', { gb: p.free_gb }) }}</span></span>
					<button type="button" class="sv-btn" data-act="move" :data-path="p.folder" @click="move(p)">{{ t('data.places_move') }}</button>
				</div>
				<button type="button" class="sv-btn sv-text" @click="choosing = false">{{ t('kit.cancel') }}</button>
			</div>
			<div v-if="dbFolder.state === 'done'" class="sv-row-out" data-kind="done" role="status" data-part="moved"><span class="mdi mdi-check-circle-outline sv-ico sv-ico-s" aria-hidden="true" />{{ tc('data.moved', copied, { n: copied }) }}</div>
			<sv-reason :lock="lockOf(['db.folder', 'db.delete_previous'])" @sign-in="signIn" />
		</section>

		<sv-confirm-dialog :confirm="dbFolder.confirm" :title="t('data.move_title')" :text="t('data.move_text', { n: r.amount || 0 })" :object="{ name: target, context: targetContext }" :verb="t('data.move_verb')" @accept="dbFolder.accept()" @cancel="dbFolder.cancel()" />
		<sv-confirm-dialog :confirm="dbDeletePrevious.confirm" :title="t('data.previous_title')" :text="t('data.previous_text', { folder: r.folder_previous || '' })" :object="{ name: r.folder_previous || '', context: tc('data.previous_desc_short', r.previous || 0, { n: r.previous || 0 }) }" :verb="t('data.previous_delete')" danger @accept="dbDeletePrevious.accept()" @cancel="dbDeletePrevious.cancel()" />
	</div>
</template>

<script>
import { downloadFile, locale } from '../../core/dwc.js'
import { dbPlaces, dbStatus } from '../../core/resources.js'
import { dbBackup, dbDeletePrevious, dbFolder, dbKeep, dbSettings } from '../../core/actions/data.js'
import { want } from '../../core/store/session.js'
import { rowsMixin } from '../../core/rows-mixin.js'
import { unsavedMixin } from '../../ui/unsaved-mixin.js'
import { saveWithAction } from '../../ui/unsaved-guard.js'
import { dateTime, time, toMs } from '../../core/format/dates.js'
import { durationText } from '../../core/format/duration.js'
import { timeNow } from '../../core/clock.js'
import SvActionRow from '../../ui/SvActionRow.vue'
import SvConfirmDialog from '../../ui/SvConfirmDialog.vue'
import SvHelp from '../../ui/SvHelp.vue'
import SvReason from '../../ui/SvReason.vue'
import SvSwitch from '../../ui/SvSwitch.vue'
import SvSelect from '../../ui/SvSelect.vue'
import SvZone from '../../ui/SvZone.vue'
import { changed, copyRows, draftOf, mirrorChoices, moveChoices, notesOf, parseCount, sdPath } from './view.js'

const DAILY = [3, 7, 14, 30]
const WEEKLY = [0, 4, 8, 12]
const withCurrent = (base, v) => (typeof v === 'number' && base.indexOf(v) < 0 ? base.concat([v]).sort((a, b) => a - b) : base)

export default {
	name: 'BackupsTab',
	components: { SvActionRow, SvConfirmDialog, SvHelp, SvReason, SvSelect, SvSwitch, SvZone },
	mixins: [rowsMixin, unsavedMixin],
	inject: { nav: { from: 'svNav', default: () => ({ go() {}, href: () => '#' }) } },
	props: { active: { type: Boolean, default: false } },
	data() {
		return { status: dbStatus, places: dbPlaces, dbBackup, dbSettings, dbKeep, dbFolder, dbDeletePrevious, draft: draftOf(null), tried: false, choosing: false, target: '', targetContext: '', downloading: '', downloadError: false }
	},
	computed: {
		r() {
			return (this.status.data && this.status.data.backup) || {}
		},
		notes() {
			return notesOf(this.status.data && this.status.data.backup)
		},
		copies() {
			return copyRows(this.status.data && this.status.data.backup)
		},
		mayEdit() {
			return this.perm('db.settings').state === 'ok'
		},
		mayKeep() {
			return this.perm('db.keep').state === 'ok'
		},
		dailyOptions() {
			return this.dailyChoices.map(n => ({ value: String(n), label: String(n) }))
		},
		weeklyOptions() {
			return this.weeklyChoices.map(n => ({ value: String(n), label: String(n) }))
		},
		mirrorOptions() {
			return this.mirrors.map(c => ({ value: c.value, label: this.mirrorText(c) }))
		},
		dailyChoices() {
			return withCurrent(DAILY, this.r.daily)
		},
		weeklyChoices() {
			return withCurrent(WEEKLY, this.r.weekly)
		},
		mirrors() {
			return mirrorChoices(this.places.data, this.r.folder, this.r.mirror_mode)
		},
		moves() {
			return moveChoices(this.places.data, this.r.folder)
		},
		dirty() {
			return changed(this.draft, this.r)
		},
		problem() {
			return (this.tried || this.dirty) && (parseCount(this.draft.daily) === null || parseCount(this.draft.weekly) === null)
		},
		updated() {
			return this.status.loadedAt ? time(this.status.loadedAt, locale()).slice(0, 5) : ''
		},
		lastText() {
			const ms = toMs(this.r.last && this.r.last.ts)
			if (ms === null) return this.t('data.never')
			return this.t('data.ago', { t: durationText(Math.max(0, (timeNow() - ms) / 1000), (k, p) => this.t('kit.' + k, p)) })
		},
		lastNote() {
			return this.r.last ? this.t('data.stat_last', { mb: this.r.last.mb }) : this.t('data.stat_last_none')
		},
		nextText() {
			const ms = toMs(this.r.next)
			return ms === null ? '–' : dateTime(ms, locale())
		},
		// how many copies the service moved (it says; else the ones that were listed)
		copied() {
			const d = this.dbFolder.data
			return d && typeof d.copied === 'number' ? d.copied : this.r.amount || 0
		},
		downloadable() {
			return !!sdPath(this.r.folder)
		}
	},
	watch: {
		active: { immediate: true, handler(on) { if (on) { want(['db.status', 'db.backup', 'db.settings', 'db.keep', 'db.folder', 'db.delete_previous', 'db.places']); this.status.show() } else this.status.hide() } },
		// what the service holds is what the form shows, until the person starts changing it
		'status.loadedAt'() {
			if (!this.dirty && this.status.data) this.draft = draftOf(this.r)
		}
	},
	methods: {
		// unsaved changes (unsaved-mixin.js): the form against what the service holds
		unsavedPair() {
			return [this.draft, draftOf(this.r)]
		},
		saveBeforeLeaving() {
			if (parseCount(this.draft.daily) === null || parseCount(this.draft.weekly) === null) return false
			return saveWithAction(this.dbSettings, () => this.save())
		},
		discardUnsaved() {
			this.draft = draftOf(this.r)
		},
		follow(e, place) {
			if (e && (e.ctrlKey || e.metaKey || e.shiftKey || e.altKey || e.button > 0)) return
			if (e && typeof e.preventDefault === 'function') e.preventDefault()
			this.nav.go(place)
		},
		dateOf(iso) {
			const ms = toMs(iso)
			return ms === null ? '–' : dateTime(ms, locale())
		},
		stateText(c) {
			if (c.state === 'kept') return this.t('data.state_kept')
			if (c.state === 'goes') return this.t('data.state_goes', { date: this.dateOf(c.until) })
			return this.t('data.state_normal')
		},
		mirrorText(c) {
			if (c.value === 'auto') return this.t('data.mirror_auto')
			if (c.value === 'no') return this.t('data.mirror_no')
			return c.name ? c.name + ' (' + c.folder + ')' : c.folder
		},
		readPlaces() {
			if (this.mayEdit) this.places.show()
		},
		save() {
			this.tried = true
			const daily = parseCount(this.draft.daily)
			const weekly = parseCount(this.draft.weekly)
			if (daily === null || weekly === null || !this.dirty) return
			this.dbSettings.run({ auto: !!this.draft.auto, daily, weekly, extra_copy: this.draft.mirror })
			this.tried = false
		},
		openPlaces() {
			this.choosing = true
			this.places.show()
		},
		move(p) {
			this.target = p.folder
			this.targetContext = this.t('data.places_free', { gb: p.free_gb })
			this.choosing = false
			this.dbFolder.run({ path: p.folder })
		},
		async download(file) {
			this.downloading = file
			this.downloadError = false
			const ok = await downloadFile(sdPath(this.r.folder) + '/' + file, file)
			this.downloadError = !ok
			this.downloading = ''
		}
	}
}
</script>
