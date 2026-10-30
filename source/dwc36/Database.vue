<template>
	<v-card class="mb-3">
		<!-- Database and backups (2026-10-11). API of WorkshopService:
		     db.status / backup / places / folder / delete_previous /
		     settings / keep. Phone notices send here ("open System
		     service > Database"). Nothing is deleted or summarized without notice. -->
		<v-card-title class="d-flex align-center flex-wrap" style="gap:8px">
			<span><v-icon small class="mr-2 svx-ico">mdi-database</v-icon>{{ $t('plugins.WorkshopService.database.database') }}</span>
			<v-chip v-if="b" small dark :color="stateBase.color"><v-icon left x-small>{{ stateBase.icon }}</v-icon>{{ stateBase.text }}</v-chip>
			<v-chip v-if="r" small dark :color="stateResp.color"><v-icon left x-small>{{ stateResp.icon }}</v-icon>{{ stateResp.text }}</v-chip>
			<v-spacer />
			<v-btn small text :loading="loading" @click="read()"><v-icon small left>mdi-refresh</v-icon>{{ $t('plugins.WorkshopService.common.refresh') }}</v-btn>
			<v-btn small color="primary" :loading="backingup" :disabled="!b || (r && r.busy)" @click="backup()"><v-icon small left>mdi-content-save-outline</v-icon>{{ $t('plugins.WorkshopService.database.back_up_now') }}</v-btn>
		</v-card-title>
		<v-card-text>
			<div v-if="error" class="error--text text-body-2 mb-2">{{ error }}</div>
			<div v-if="msg" class="text-body-2 mb-2" :class="msgOk ? 'success--text' : 'error--text'">{{ msg }}</div>
			<div v-if="!b && !error" class="grey--text">{{ $t('plugins.WorkshopService.database.reading') }}</div>
			<template v-if="b">
				<!-- what is going to be deleted by itself: the same as in Timelapses -->
				<div v-if="r && r.per_delete && r.per_delete.length" class="bd-notice mb-3">
					<div class="font-weight-medium"><v-icon small color="orange">mdi-alert</v-icon> {{ $t('plugins.WorkshopService.database.will_auto_delete_n_backups', { n: r.per_delete.length }) }}</div>
					<div class="text-caption">{{ $t('plugins.WorkshopService.database.copy_limits_exceeded') }}</div>
					<div v-for="p in r.per_delete" :key="p.file" class="d-flex align-center flex-wrap mt-1" style="gap:8px">
						<code class="bd-arch">{{ p.file }}</code>
						<span class="text-caption">{{ $t('plugins.WorkshopService.database.deleted_on_d', { d: dateEpoch(p.until) }) }}</span>
						<v-btn x-small outlined @click="keep(p.file, true)">{{ $t('plugins.WorkshopService.database.keep') }}</v-btn>
					</div>
				</div>

				<v-row dense>
					<!-- la base -->
					<v-col cols="12" md="5">
						<div class="bd-tit">{{ $t('plugins.WorkshopService.database.the_database') }}</div>
						<div class="bd-nums">
							<div><div class="bd-v">{{ b.mb }} MB</div><div class="bd-t">{{ $t('plugins.WorkshopService.database.file_size') }}</div></div>
							<div><div class="bd-v">{{ rows }}</div><div class="bd-t">{{ $t('plugins.WorkshopService.database.rows') }}</div></div>
							<div><div class="bd-v">{{ hour(b.modified) }}</div><div class="bd-t">{{ $t('plugins.WorkshopService.database.last_write') }}</div></div>
						</div>
						<div class="text-caption mt-2">
							<v-icon x-small>{{ b.location === 'sd' ? 'mdi-sd' : 'mdi-folder-alert-outline' }}</v-icon>
							<code>{{ b.file }}</code>
						</div>
						<div v-if="b.location === 'sd'" class="text-caption grey--text">{{ $t('plugins.WorkshopService.database.on_the_system_s_card_outside') }}</div>
						<div v-else class="text-caption warning--text">{{ $t('plugins.WorkshopService.database.still_inside_the_plugin_folder_uninstalling') }}</div>
						<v-simple-table dense class="mt-2">
							<thead><tr><th>{{ $t('plugins.WorkshopService.database.what_it_stores') }}</th><th class="text-right">{{ $t('plugins.WorkshopService.database.rows_2') }}</th><th>{{ $t('plugins.WorkshopService.database.from') }}</th><th>{{ $t('plugins.WorkshopService.database.to') }}</th></tr></thead>
							<tbody>
								<tr v-for="tb in tables" :key="tb.name">
									<td>{{ nameTable(tb.name) }}</td>
									<td class="text-right">{{ tb.rows }}</td>
									<td class="text-no-wrap">{{ date(tb.since) }}</td>
									<td class="text-no-wrap">{{ date(tb.until) }}</td>
								</tr>
							</tbody>
						</v-simple-table>
						<div class="text-caption grey--text mt-1">
							{{ $t('plugins.WorkshopService.database.sqlite_check_x', { x: b.check }) }}<template v-if="b.version_schema != null"> &middot; {{ $t('plugins.WorkshopService.database.schema_v', { v: b.version_schema }) }}</template><template v-if="b.mode_daily"> &middot; {{ $t('plugins.WorkshopService.database.journal_x', { x: b.mode_daily }) }}</template>
						</div>
						<!-- lecturas viejas del medidor -->
						<div v-if="hasPower" class="bd-box mt-2">
							<v-switch dense hide-details class="mt-0" :input-value="!!(r && r.summarize_consumption)" :loading="saving === 'R'"
								:label="$t('plugins.WorkshopService.database.summarize_old_meter_readings')" @change="v => settings({ summarize: !!v }, 'R')" />
							<div class="text-caption grey--text">
								{{ $t('plugins.WorkshopService.database.readings_older_than_n_days', { n: b.consumption_detail_days || 90 }) }}
							</div>
							<div v-if="r && r.prune_pending" class="text-caption orange--text mt-1">
								{{ $t('plugins.WorkshopService.database.will_summarize_n_readings', { n: r.prune_pending.rows, from: dateEpoch(r.prune_pending.since), to: dateEpoch(r.prune_pending.until), on: dateEpoch(r.prune_pending.limit) }) }}
							</div>
						</div>
					</v-col>

					<!-- respaldos -->
					<v-col v-if="r" cols="12" md="7">
						<div class="bd-tit">{{ $t('plugins.WorkshopService.database.automatic_backups') }}</div>
						<div class="bd-nums">
							<div><div class="bd-v">{{ r.last ? does(r.last.ts) : $t('plugins.WorkshopService.database.never') }}</div><div class="bd-t">{{ $t('plugins.WorkshopService.database.last') }}<template v-if="r.last"> ({{ r.last.mb }} MB)</template></div></div>
							<div><div class="bd-v">{{ r.active ? hourEpoch(r.next) : $t('plugins.WorkshopService.database.off') }}</div><div class="bd-t">{{ $t('plugins.WorkshopService.database.next') }}</div></div>
							<div><div class="bd-v">{{ r.amount }}</div><div class="bd-t">{{ $t('plugins.WorkshopService.database.copies_mb', { mb: r.mb_total }) }}</div></div>
							<div><div class="bd-v">{{ r.free_gb != null ? r.free_gb + ' GB' : '-' }}</div><div class="bd-t">{{ $t('plugins.WorkshopService.database.free_where_they_re_stored') }}</div></div>
						</div>
						<div class="text-caption mt-2"><v-icon x-small>mdi-folder-outline</v-icon> <code>{{ r.folder }}</code></div>
						<div class="text-caption grey--text">{{ $t('plugins.WorkshopService.database.one_compressed_copy_per_day', { d: r.daily, w: r.weekly }) }}</div>
						<div v-if="r.includes" class="text-caption grey--text">
							{{ $t('plugins.WorkshopService.database.each_copy_includes_x', { x: r.includes.join(', ') }) }}
						</div>

						<!-- 2026-10-11: "what happens if the USB is removed" -->
						<div v-if="r.folder_disconnected" class="bd-notice mt-2">
							<div class="font-weight-medium"><v-icon small color="orange">mdi-usb-flash-drive-outline</v-icon> {{ $t('plugins.WorkshopService.database.the_backup_usb_stick_is_not') }}</div>
							<div class="text-caption">{{ $t('plugins.WorkshopService.database.meanwhile_they_re_saved_on_the') }}<code>{{ r.saving_en }}</code>{{ $t('plugins.WorkshopService.database.when_you_plug_it_back_in') }}</div>
						</div>
						<div v-if="r.mirror_disconnected" class="bd-notice mt-2">
							<div class="font-weight-medium"><v-icon small color="orange">mdi-usb-flash-drive-outline</v-icon> {{ $t('plugins.WorkshopService.database.the_copy_to_another_place_is') }}</div>
							<div class="text-caption">{{ $t('plugins.WorkshopService.database.the_stick') }}<code>{{ r.mirror_seen }}</code>{{ $t('plugins.WorkshopService.database.is_not_plugged_in_when_you') }}</div>
						</div>
						<!-- 2026-10-11: "the database and the backup should not share the same path" -->
						<div v-if="r.same_card && r.active" class="bd-notice mt-2">
							<div class="font-weight-medium"><v-icon small color="orange">mdi-sd</v-icon> {{ $t('plugins.WorkshopService.database.the_database_and_its_backups_are') }}</div>
							<div class="text-caption">{{ $t('plugins.WorkshopService.database.if_the_system_s_card_fails') }}</div>
						</div>

						<div class="bd-box mt-2">
							<div class="d-flex align-center flex-wrap" style="gap:10px">
								<v-switch dense hide-details class="mt-0" :input-value="!!r.active" :loading="saving === 'A'" :label="$t('plugins.WorkshopService.database.backups_on')" @change="v => settings({ auto: !!v }, 'A')" />
								<v-select v-model="nDaily" :items="[3, 7, 14, 30, 60]" :label="$t('plugins.WorkshopService.database.daily')" dense hide-details outlined class="bd-sel" @change="settings({ daily: nDaily }, 'N')" />
								<v-select v-model="nWeekly" :items="[0, 2, 4, 8, 12, 26, 52]" :label="$t('plugins.WorkshopService.database.weekly')" dense hide-details outlined class="bd-sel" @change="settings({ weekly: nWeekly }, 'W')" />
							</div>
						</div>

						<!-- copia en otro lugar (espejo) -->
						<div class="bd-box mt-2">
							<div class="d-flex align-center flex-wrap" style="gap:10px">
								<span class="text-body-2">{{ $t('plugins.WorkshopService.database.copy_to_another_place') }}</span>
								<v-select :value="r.mirror_mode" :items="optionsMirror" :label="$t('plugins.WorkshopService.database.copy_every_backup_to')" dense hide-details outlined class="bd-sel-width"
									:loading="saving === 'E'" @focus="!places && readPlaces()" @change="v => settings({ extra_copy: String(v || '') }, 'E')" />
							</div>
							<div v-if="r.mirror" class="text-caption mt-1">
								<v-icon x-small>{{ /media|mnt/.test(r.mirror) ? 'mdi-usb-flash-drive' : 'mdi-sd' }}</v-icon>
								<code>{{ r.mirror }}</code> &middot; {{ $t('plugins.WorkshopService.database.n_copies', { n: r.mirror_amount }) }}<template v-if="r.mirror_last">{{ $t('plugins.WorkshopService.database.the_last_one_t', { t: does(r.mirror_last.ts) }) }}</template><template v-if="r.mirror_free_gb != null"> &middot; {{ $t('plugins.WorkshopService.database.n_gb_free', { n: r.mirror_free_gb }) }}</template>
							</div>
							<div v-else-if="r.mirror_mode === 'auto'" class="text-caption grey--text mt-1">{{ $t('plugins.WorkshopService.database.no_usb_stick_is_plugged_in') }}</div>
							<div v-else-if="r.mirror_mode !== 'no'" class="text-caption warning--text mt-1">{{ $t('plugins.WorkshopService.database.that_place_is_not_connected_nothing') }}</div>
							<div v-if="r.mirror_error" class="text-caption error--text mt-1">{{ r.mirror_error }}</div>
						</div>

						<!-- donde se guardan -->
						<div class="bd-box mt-2">
							<div class="d-flex align-center flex-wrap" style="gap:8px">
								<span class="text-body-2">{{ $t('plugins.WorkshopService.database.where_they_re_stored') }}</span>
								<v-btn x-small outlined :loading="readingPlaces" @click="readPlaces()">{{ $t('plugins.WorkshopService.database.choose_another_place') }}</v-btn>
							</div>
							<div v-if="places" class="mt-2">
								<div v-for="l in places" :key="l.folder" class="d-flex align-center flex-wrap bd-place" style="gap:8px">
									<v-icon small>{{ /media|mnt/.test(l.folder) ? 'mdi-usb-flash-drive' : 'mdi-sd' }}</v-icon>
									<span>{{ l.name }}</span>
									<code class="bd-arch">{{ l.folder }}</code>
									<span class="text-caption grey--text">{{ $t('plugins.WorkshopService.database.n_gb_free', { n: l.free_gb }) }}</span>
									<v-chip v-if="l.folder === r.folder" x-small color="primary">{{ $t('plugins.WorkshopService.database.in_use') }}</v-chip>
									<v-btn v-else x-small :color="armed === 'c' + l.folder ? 'amber darken-3' : undefined" :dark="armed === 'c' + l.folder" :disabled="l.writable === false"
										@click="double('c' + l.folder, () => changeFolder(l.folder))">
										{{ armed === 'c' + l.folder ? $t('plugins.WorkshopService.database.tap_again_copy_there') : $t('plugins.WorkshopService.database.use_this_one') }}
									</v-btn>
									<span v-if="l.writable === false" class="text-caption error--text">{{ $t('plugins.WorkshopService.database.can_t_write') }}</span>
								</div>
								<!-- 2026-10-11 ("when I choose another place it does nothing"): without a USB drive the list is only the card, which is already in use -->
								<div v-if="!places.some(l => l.folder !== r.folder)" class="text-caption warning--text mt-1">
									<v-icon x-small color="warning">mdi-usb-flash-drive-outline</v-icon> {{ $t('plugins.WorkshopService.database.there_is_no_other_place_the') }}
								</div>
								<div v-else class="text-caption grey--text mt-1">{{ $t('plugins.WorkshopService.database.when_you_change_it_the_existing') }}</div>
							</div>
							<div v-if="r.folder_previous && r.previous" class="text-caption mt-2">
								{{ $t('plugins.WorkshopService.database.in_the_previous_folder') }} (<code>{{ r.folder_previous }}</code>) {{ $t('plugins.WorkshopService.database.n_backups_left_already_copied', { n: r.previous }) }}
								<v-btn x-small text :color="armed === 'borrarAnt' ? 'error' : 'grey'" @click="double('borrarAnt', deletePrevious)">
									{{ armed === 'borrarAnt' ? $t('plugins.WorkshopService.database.tap_again_delete_them') : $t('plugins.WorkshopService.database.delete_them') }}
								</v-btn>
							</div>
						</div>

						<!-- copias -->
						<div v-if="r.list && r.list.length" class="mt-2">
							<div class="text-body-2">{{ $t('plugins.WorkshopService.database.copies') }}</div>
							<div v-for="c in r.list" :key="c.file" class="d-flex align-center flex-wrap bd-copy" :class="{ 'bd-per-delete': perDelete(c.file) }" style="gap:8px">
								<code class="bd-arch">{{ c.file }}</code>
								<span class="text-caption grey--text">{{ c.mb }} MB &middot; {{ date(c.date) }}</span>
								<span v-if="perDelete(c.file)" class="wf-state warn">{{ $t('plugins.WorkshopService.database.deleted_on_d', { d: dateEpoch(perDelete(c.file).until) }) }}</span>
								<v-chip v-if="kept(c.file)" x-small color="success" outlined>{{ $t('plugins.WorkshopService.database.kept') }}</v-chip>
								<v-btn x-small text @click="keep(c.file, !kept(c.file))">{{ kept(c.file) ? $t('plugins.WorkshopService.common.release') : $t('plugins.WorkshopService.database.keep') }}</v-btn>
								<v-btn v-if="pathSd(r.folder)" x-small text :loading="lowering === c.file" @click="download(c.file)"><v-icon x-small left>mdi-download</v-icon>{{ $t('plugins.WorkshopService.common.download') }}</v-btn>
							</div>
						</div>
						<div v-if="r.failures && r.failures.length" class="mt-2">
							<div class="text-body-2 error--text">{{ $t('plugins.WorkshopService.database.failures') }}</div>
							<div v-for="(f, i) in r.failures" :key="i" class="text-caption error--text">{{ date(f.date) }}: {{ f.text }}</div>
						</div>
					</v-col>
					<v-col v-else cols="12" md="7" class="grey--text text-body-2">
						{{ $t('plugins.WorkshopService.database.service_does_not_back_up_yet') }}
					</v-col>
				</v-row>
			</template>
		</v-card-text>
	</v-card>
</template>

<script>
import i18n from '../../i18n'

'use strict'

import { api } from './workshop-api.js'
import { pluginActive } from './workshop-ids.js'

const names = { activity: i18n.t('plugins.WorkshopService.database.activity_jobs_modes_alerts'), consumption: i18n.t('plugins.WorkshopService.database.energy_meter_readings'), commands: i18n.t('plugins.WorkshopService.common.received_commands') };

export default {
	data() {
		return {
			b: null,
			error: null,
			msg: '',
			msgOk: true,
			loading: false,
			backingup: false,
			saving: null,
			places: null,
			readingPlaces: false,
			armed: null,
			armedTimer: null,
			nDaily: 7,
			nWeekly: 4,
			lowering: null,
		};
	},
	computed: {
		r() { return (this.b && this.b.backup) || null; },
		// the old-readings option is about the Power Usage plugin: nothing about it when that plugin is absent
		hasPower() { return pluginActive(this.$store, 'consumption'); },
		tables() { return ((this.b && this.b.tables) || []).filter(x => x.name !== 'presets' && x.name !== 'sqlite_sequence'); },
		rows() { return this.tables.reduce((s, x) => s + (x.rows || 0), 0); },
		optionsMirror() {
			const o = [{ text: i18n.t('plugins.WorkshopService.database.automatic_the_usb_stick_that_is'), value: 'auto' }, { text: i18n.t('plugins.WorkshopService.database.don_t_copy'), value: 'no' }];
			(this.places || []).forEach(l => { if (this.r && l.folder !== this.r.folder) o.push({ text: l.name + ' (' + l.folder + ')', value: l.folder }); });
			const e = this.r && this.r.mirror_mode;
			if (e && !o.some(x => x.value === e)) o.push({ text: e, value: e });
			return o;
		},
		stateBase() {
			if (this.b.error) return { text: i18n.t('plugins.WorkshopService.common.no_data'), color: 'grey', icon: 'mdi-help-circle' };
			return this.b.check === 'ok' ? { text: i18n.t('plugins.WorkshopService.database.healthy'), color: 'success', icon: 'mdi-check-circle' } : { text: i18n.t('plugins.WorkshopService.database.check'), color: 'warning', icon: 'mdi-alert' };
		},
		stateResp() {
			const r = this.r;
			if (!r.active) return { text: i18n.t('plugins.WorkshopService.database.backups_off'), color: 'grey', icon: 'mdi-content-save-off-outline' };
			if (r.failures && r.failures.length) return { text: i18n.t('plugins.WorkshopService.database.backups_failing'), color: 'error', icon: 'mdi-alert-circle' };
			if (r.late) return { text: i18n.t('plugins.WorkshopService.database.backup_overdue'), color: 'orange darken-2', icon: 'mdi-clock-alert-outline' };
			if (!r.last) return { text: i18n.t('plugins.WorkshopService.database.first_backup_pending'), color: 'blue', icon: 'mdi-timer-sand' };
			return { text: i18n.t('plugins.WorkshopService.database.backups_on_2'), color: 'success', icon: 'mdi-shield-check' };
		}
	},
	mounted() {
		this.read();
		// only with the page in view (DWC keeps it alive with keep-alive when going to another)
		this.timer = setInterval(() => { if (!document.hidden && this.$el && this.$el.isConnected !== false) this.read(true); }, 15000);
	},
	beforeDestroy() {
		clearInterval(this.timer);
		clearTimeout(this.armedTimer);
	},
	methods: {
		// API of WorkshopService: db.<op> (the result is the JSON of the service)
		async base(op, args) {
			const r = await api('db.' + op, args || {});
			if (!r || typeof r !== 'object') throw new Error(String(r || '') || i18n.t('plugins.WorkshopService.database.no_response'));
			return r;
		},
		notice(t, ok) {
			this.msg = t;
			this.msgOk = ok !== false;
			clearTimeout(this.msgTimer);
			this.msgTimer = setTimeout(() => { this.msg = ''; }, 8000);
		},
		async read(silencioso) {
			if (!silencioso) this.loading = true;
			try {
				const d = await this.base('status');
				if (d.error && !d.tables) throw new Error(d.error);
				this.b = d;
				this.error = null;
				if (d.backup) {
					this.nDaily = d.backup.daily;
					this.nWeekly = d.backup.weekly;
				}
			} catch (e) {
				this.error = i18n.t('plugins.WorkshopService.database.could_not_read_the_database_x', { x: e.message || e });
			} finally {
				this.loading = false;
			}
		},
		async backup() {
			this.backingup = true;
			try {
				const d = await this.base('backup');
				this.notice(d.ok ? i18n.t('plugins.WorkshopService.database.backup_done', { file: d.file, mb: d.mb }) : i18n.t('plugins.WorkshopService.common.couldn_t_x', { x: d.error || '' }), d.ok);
			} catch (e) {
				this.notice(i18n.t('plugins.WorkshopService.common.couldn_t_x', { x: e.message || e }), false);
			}
			this.backingup = false;
			this.read(true);
		},
		async settings(p, key) {
			this.saving = key;
			try {
				const d = await this.base('settings', p);
				if (d && d.ok === false) throw new Error(d.error || '');
				this.notice(i18n.t('plugins.WorkshopService.database.saved'));
			} catch (e) {
				this.notice(i18n.t('plugins.WorkshopService.common.could_not_save_x', { x: e.message || e }), false);
			}
			this.saving = null;
			this.read(true);
		},
		async readPlaces() {
			this.readingPlaces = true;
			try {
				const d = await this.base('places');
				this.places = Array.isArray(d) ? d : (d.places || []);
			} catch (e) {
				this.notice(i18n.t('plugins.WorkshopService.database.could_not_read_the_places_x', { x: e.message || e }), false);
			}
			this.readingPlaces = false;
		},
		async changeFolder(c) {
			try {
				const d = await this.base('folder', { path: String(c) });
				this.notice(d.ok ? i18n.t('plugins.WorkshopService.database.done_backups_in', { c }) + (d.copied != null ? i18n.t('plugins.WorkshopService.database.n_copied', { n: d.copied }) : '') + '.' : i18n.t('plugins.WorkshopService.common.couldn_t_x', { x: d.error || '' }), d.ok);
				if (d.ok) this.places = null;
			} catch (e) {
				this.notice(i18n.t('plugins.WorkshopService.common.couldn_t_x', { x: e.message || e }), false);
			}
			this.read(true);
		},
		async deletePrevious() {
			try {
				const d = await this.base('delete_previous');
				this.notice(d.ok ? i18n.t('plugins.WorkshopService.database.deleted_n_backups_previous', { n: d.deleted }) : i18n.t('plugins.WorkshopService.common.couldn_t_x', { x: d.error || '' }), d.ok);
			} catch (e) {
				this.notice(i18n.t('plugins.WorkshopService.common.couldn_t_x', { x: e.message || e }), false);
			}
			this.read(true);
		},
		async keep(archivo, si) {
			try {
				const d = await this.base('keep', { file: String(archivo), keep: !!si });
				this.notice(d.ok ? (si ? i18n.t('plugins.WorkshopService.database.kept_it_won_t_be_deleted') : i18n.t('plugins.WorkshopService.database.no_longer_kept')) : i18n.t('plugins.WorkshopService.common.couldn_t_x', { x: d.error || '' }), d.ok);
			} catch (e) {
				this.notice(i18n.t('plugins.WorkshopService.common.couldn_t_x', { x: e.message || e }), false);
			}
			this.read(true);
		},
		perDelete(a) { return ((this.r && this.r.per_delete) || []).find(p => p.file === a) || null; },
		kept(a) { return ((this.r && this.r.kept) || []).includes(a); },
		// system folder -> DSF path (0:/...); null if it is a USB drive (the web does not serve it)
		pathSd(c) { return /^\/opt\/dsf\/sd\//.test(c || '') ? '0:/' + c.slice('/opt/dsf/sd/'.length) : null; },
		async download(file) {
			this.lowering = file;
			try {
				const h = {};
				if (window.__workshopSession) h['X-Session-Key'] = window.__workshopSession;
				const res = await fetch('/machine/file/' + encodeURIComponent(this.pathSd(this.r.folder) + '/' + file), { headers: h, cache: 'no-store' });
				if (!res.ok) throw new Error('HTTP ' + res.status);
				const url = URL.createObjectURL(await res.blob());
				const a = document.createElement('a');
				a.href = url;
				a.download = file;
				document.body.appendChild(a);
				a.click();
				a.remove();
				setTimeout(() => URL.revokeObjectURL(url), 10000);
			} catch (e) {
				this.notice(i18n.t('plugins.WorkshopService.database.could_not_download_x', { x: e.message || e }), false);
			}
			this.lowering = null;
		},
		// doble toque (nivel 2, DISENO.md 5): ambar, 4 s para confirmar
		double(key, fn) {
			if (this.armed === key) {
				this.armed = null;
				clearTimeout(this.armedTimer);
				fn();
				return;
			}
			this.armed = key;
			clearTimeout(this.armedTimer);
			this.armedTimer = setTimeout(() => { this.armed = null; }, 4000);
		},
		nameTable(n) { return names[n] || n; },
		date(ts) {
			const s = String(ts || '');
			return /^\d{4}-\d\d-\d\dT\d\d:\d\d/.test(s) ? s.slice(8, 10) + '/' + s.slice(5, 7) + ' ' + s.slice(11, 16) : '-';
		},
		dateEpoch(t) {
			if (!t) return '-';
			const d = new Date(t * 1000);
			const p = n => String(n).padStart(2, '0');
			return p(d.getDate()) + '/' + p(d.getMonth() + 1) + ' ' + p(d.getHours()) + ':' + p(d.getMinutes());
		},
		hourEpoch(t) {
			if (!t) return '-';
			const d = new Date(t * 1000), today = new Date();
			const p = n => String(n).padStart(2, '0');
			return (d.toDateString() === today.toDateString() ? '' : p(d.getDate()) + '/' + p(d.getMonth() + 1) + ' ') + p(d.getHours()) + ':' + p(d.getMinutes());
		},
		hour(ts) {
			const s = String(ts || '');
			const today = new Date();
			const d = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, '0')}-${String(today.getDate()).padStart(2, '0')}`;
			return s.slice(0, 10) === d ? s.slice(11, 16) : this.date(s);
		},
		does(ts) {
			if (!ts) return '-';
			const s = Math.max(0, Date.now() / 1000 - ts);
			if (s < 3600) return i18n.t('plugins.WorkshopService.database.ago_n_min', { n: Math.max(1, Math.round(s / 60)) });
			if (s < 86400) return i18n.t('plugins.WorkshopService.database.ago_n_h', { n: Math.round(s / 3600) });
			return i18n.t('plugins.WorkshopService.database.ago_n_days', { n: Math.round(s / 86400) });
		}
	}
};
</script>

<style scoped>
.bd-tit {
	font-size: 13px;
	font-weight: 500;
	margin-bottom: 4px;
}
.bd-nums {
	display: flex;
	flex-wrap: wrap;
	gap: 6px 20px;
}
.bd-v {
	font-size: 18px;
	font-weight: 500;
	white-space: nowrap;
	font-variant-numeric: tabular-nums;
}
.bd-t {
	font-size: 12px;
	color: var(--tp-faint, #9e9e9e);
}
.bd-box {
	border: 1px solid var(--wf-line);
	border-radius: 8px;
	padding: 8px 10px;
}
.bd-sel {
	max-width: 120px;
}
.bd-sel-width {
	max-width: 360px;
}
@media (max-width: 599px) {
	.bd-sel-width { max-width: 100%; min-width: 0; }
}
.bd-arch {
	font-size: 12px;
	word-break: break-all;
}
.bd-per-delete { color: var(--wf-warn); }
.bd-copy {
	padding: 3px 0;
	border-bottom: 1px solid rgba(128, 128, 128, 0.12);
}
.bd-notice {
	border: 1px solid var(--wf-warn);
	border-radius: 10px;
	padding: 8px 10px;
}
</style>
