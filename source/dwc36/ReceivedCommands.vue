<template>
	<v-card class="mb-3">
		<!-- History of received commands, redesign 2026-10-10 ("redesign that
		     history of received commands better"): by default only what CHANGES something
		     (the pages read all the time and covered what matters), quick ranges,
		     summary, grouped by hour and the detail with copy. -->
		<v-card-title class="d-flex align-center flex-wrap" style="gap:8px">
			<span><v-icon small class="mr-2 svx-ico">mdi-console-line</v-icon>{{ $t('plugins.WorkshopService.common.received_commands') }}</span>
			<span class="cmd-live" :title="inLive ? $t('plugins.WorkshopService.commandsReceived.updates_by_itself_with_each_new') : $t('plugins.WorkshopService.commandsReceived.paused_it_doesn_t_update_by')">
				<span class="cmd-point" :class="{ on: inLive }" />{{ inLive ? $t('plugins.WorkshopService.commandsReceived.live') : $t('plugins.WorkshopService.commandsReceived.paused') }}
			</span>
			<v-spacer />
			<v-btn small text @click="inLive = !inLive"><v-icon small left>{{ inLive ? 'mdi-pause' : 'mdi-play' }}</v-icon>{{ inLive ? $t('plugins.WorkshopService.common.pause') : $t('plugins.WorkshopService.common.follow') }}</v-btn>
			<v-btn small text :loading="loading" @click="load(0)"><v-icon small left>mdi-refresh</v-icon>{{ $t('plugins.WorkshopService.common.refresh') }}</v-btn>
		</v-card-title>
		<v-card-text>
			<!-- resumen del rango -->
			<div v-if="summary" class="cmd-summary">
				<div class="cmd-num">
					<div class="cmd-num-v">{{ summary.all - summary.readings }}</div>
					<div class="cmd-num-t"><v-icon x-small>mdi-pencil-outline</v-icon> {{ $t('plugins.WorkshopService.commandsReceived.change_something') }}</div>
				</div>
				<div class="cmd-num">
					<div class="cmd-num-v">{{ summary.readings }}</div>
					<div class="cmd-num-t"><v-icon x-small>mdi-eye-outline</v-icon> {{ $t('plugins.WorkshopService.commandsReceived.reads') }}</div>
				</div>
				<div class="cmd-num" :class="{ 'cmd-num-err': summary.errors }">
					<div class="cmd-num-v">{{ summary.errors }}</div>
					<div class="cmd-num-t"><v-icon x-small>mdi-alert-circle-outline</v-icon> {{ $t('plugins.WorkshopService.commandsReceived.with_error') }}</div>
				</div>
				<div class="cmd-num">
					<div class="cmd-num-v">{{ summary.ms_avg != null ? summary.ms_avg + ' ms' : '-' }}</div>
					<div class="cmd-num-t">{{ $t('plugins.WorkshopService.commandsReceived.average_time') }}<template v-if="summary.ms_max != null"> {{ $t('plugins.WorkshopService.commandsReceived.max_n', { n: summary.ms_max }) }}</template></div>
				</div>
			</div>

			<!-- last hour by origin (ring in the service's memory): tapping one filters -->
			<div v-if="lastHour && lastHour.total" class="cmd-hour-origin mt-3">
				<span class="text-caption grey--text">{{ $t('plugins.WorkshopService.commandsReceived.last_hour_n', { n: lastHour.total }) }}</span>
				<v-chip
					v-for="k in counters" :key="k.id" x-small label :outlined="kindOrigin !== k.id" :color="kindOrigin === k.id ? 'primary' : undefined"
					:title="$t('plugins.WorkshopService.commandsReceived.commands_last_hour_that_came_as', { x: k.text })" @click="kindOrigin = kindOrigin === k.id ? null : k.id; if (kindOrigin) kind = 0; load(0)"
				>
					<v-icon left x-small>{{ iconOrigin(k.id) }}</v-icon>{{ k.text }} {{ k.n }}
				</v-chip>
				<v-chip v-if="lastHour.result && lastHour.result.blocked" x-small label outlined color="warning" @click="result = result === 'blocked' ? null : 'blocked'; load(0)">
					<v-icon left x-small>mdi-cancel</v-icon>{{ $t('plugins.WorkshopService.commandsReceived.blocked_n', { n: lastHour.result.blocked }) }}
				</v-chip>
				<v-chip v-if="lastHour.result && lastHour.result.error" x-small label outlined color="error" @click="result = result === 'error' ? null : 'error'; load(0)">
					<v-icon left x-small>mdi-alert-circle-outline</v-icon>{{ $t('plugins.WorkshopService.commandsReceived.with_error_n', { n: lastHour.result.error }) }}
				</v-chip>
			</div>

			<!-- cuando -->
			<div class="d-flex align-center flex-wrap mt-3" style="gap:6px">
				<v-chip v-for="r in spans" :key="r.id" small :color="range === r.id ? 'primary' : undefined" :outlined="range !== r.id" @click="chooseSpan(r.id)">{{ r.text }}</v-chip>
				<v-menu v-model="datesMenu" :close-on-content-click="false" offset-y min-width="auto">
					<template v-slot:activator="{ on, attrs }">
						<v-chip small :color="range === 'other' ? 'primary' : undefined" :outlined="range !== 'other'" v-bind="attrs" v-on="on">
							<v-icon left small>mdi-calendar-range</v-icon>{{ range === 'other' ? textDates : $t('plugins.WorkshopService.commandsReceived.pick_dates') }}
						</v-chip>
					</template>
					<v-date-picker v-model="dates" range no-title color="primary" @input="onChooseDates" />
				</v-menu>
			</div>

			<!-- que -->
			<div class="d-flex align-center flex-wrap mt-3" style="gap:8px">
				<v-btn-toggle v-model="kind" mandatory dense color="primary" @change="load(0)">
					<v-btn small :value="1" :title="$t('plugins.WorkshopService.commandsReceived.what_changes_something_settings_jobs_the')"><v-icon left small>mdi-pencil-outline</v-icon>{{ $t('plugins.WorkshopService.common.change_something') }}</v-btn>
					<v-btn small :value="2" :title="$t('plugins.WorkshopService.commandsReceived.queries_that_only_read_pages_ask')"><v-icon left small>mdi-eye-outline</v-icon>{{ $t('plugins.WorkshopService.commandsReceived.readings') }}</v-btn>
					<v-btn small :value="0">{{ $t('plugins.WorkshopService.common.all') }}</v-btn>
				</v-btn-toggle>
				<v-select v-model="name" :items="optionsName" :label="$t('plugins.WorkshopService.commandsReceived.command')" dense hide-details clearable outlined class="cmd-field" @change="load(0)" />
				<v-select v-model="via" :items="optionsVia" :label="$t('plugins.WorkshopService.commandsReceived.came_through')" dense hide-details clearable outlined class="cmd-field" @change="load(0)" />
				<v-select v-model="channel" :items="optionsChannel" :label="$t('plugins.WorkshopService.commandsReceived.channel')" dense hide-details clearable outlined class="cmd-field" @change="load(0)" />
				<v-select v-model="kindOrigin" :items="optionsKindOrigin" :label="$t('plugins.WorkshopService.commandsReceived.origin')" dense hide-details clearable outlined class="cmd-field" @change="load(0)" />
				<v-select v-model="plugin" :items="optionsPlugin" :label="$t('plugins.WorkshopService.commandsReceived.plugin_or_page')" dense hide-details clearable outlined class="cmd-field" @change="load(0)" />
				<v-select v-model="result" :items="optionsResult" :label="$t('plugins.WorkshopService.commandsReceived.result')" dense hide-details clearable outlined class="cmd-field" @change="load(0)" />
				<v-text-field v-model="search" :label="$t('plugins.WorkshopService.common.find')" dense hide-details clearable outlined prepend-inner-icon="mdi-magnify" class="cmd-field" @keyup.enter="load(0)" @click:clear="search = ''; load(0)" />
				<v-switch v-model="onlyErrors" :label="$t('plugins.WorkshopService.commandsReceived.errors_only')" dense hide-details class="mt-0 pt-0" @change="load(0)" />
			</div>

			<div v-if="error" class="error--text text-body-2 mt-3">{{ error }}</div>
			<div v-else-if="!rows.length && !loading" class="cmd-empty mt-3">
				<v-icon color="grey">mdi-inbox-outline</v-icon>
				<div>{{ kind === 1 ? $t('plugins.WorkshopService.commandsReceived.no_command_that_changes_something_in') : $t('plugins.WorkshopService.commandsReceived.no_commands_in_this_range') }}</div>
				<div v-if="kind === 1 && summary && summary.readings" class="text-caption">{{ $t('plugins.WorkshopService.commandsReceived.there_are_n_reads', { n: summary.readings }) }} <a href="#" @click.prevent="kind = 2; load(0)">{{ $t('plugins.WorkshopService.commandsReceived.show_them') }}</a>.</div>
			</div>
			<div v-else class="cmd-list mt-3">
				<template v-for="g in groups">
					<div :key="'g' + g.key" class="cmd-group">{{ g.title }} <span class="grey--text">· {{ g.rows.length }}</span></div>
					<div v-for="f in g.rows" :key="f.id" class="cmd-row" :class="{ 'cmd-err': !f.ok, open: open === f.id }">
						<div class="cmd-cab" @click="open = open === f.id ? null : f.id">
							<v-icon small :color="f.ok ? 'success' : 'warning'" :title="f.ok ? $t('plugins.WorkshopService.commandsReceived.answered_ok') : $t('plugins.WorkshopService.commandsReceived.failed')">{{ f.ok ? 'mdi-check-circle' : 'mdi-alert-circle' }}</v-icon>
							<span class="cmd-hour">{{ f.ts.slice(11, 19) }}</span>
							<v-chip x-small label dark class="cmd-name" :color="style(f).color"><v-icon left x-small>{{ style(f).icon }}</v-icon>{{ f.name }}</v-chip>
							<v-icon x-small :color="f.reading ? 'grey' : 'orange darken-2'" :title="f.reading ? $t('plugins.WorkshopService.common.read_only') : $t('plugins.WorkshopService.common.changes_something')">{{ f.reading ? 'mdi-eye-outline' : 'mdi-pencil-outline' }}</v-icon>
							<code class="cmd-code">{{ withoutM(f.code) }}</code>
							<span v-if="f.origin && f.origin.kind" class="cmd-via" :title="$t('plugins.WorkshopService.commandsReceived.origin_x', { x: summaryOrigin(f) })">
								<v-icon x-small>{{ iconOrigin(f.origin.kind) }}</v-icon>{{ textOrigin(f.origin.kind) }}<template v-if="f.origin.plugin">: {{ f.origin.plugin }}</template>
							</span>
							<span v-else-if="f.via" class="cmd-via" :title="$t('plugins.WorkshopService.commandsReceived.came_through_x', { x: f.via })"><v-icon x-small>{{ iconVia(f.via) }}</v-icon>{{ f.via }}</span>
							<v-chip v-if="f.origin && f.origin.result === 'blocked'" x-small label outlined color="warning" class="cmd-lock" :title="f.origin.reason">{{ $t('plugins.WorkshopService.commandsReceived.blocked') }}</v-chip>
							<span class="cmd-ms" :title="f.ms != null ? $t('plugins.WorkshopService.commandsReceived.took_n_ms', { n: f.ms }) : ''">
								<span class="cmd-ms-bar"><i :style="{ width: bar(f.ms) + '%', background: f.ms > 2000 ? '#ffa726' : '#64b5f6' }" /></span>
								{{ f.ms != null ? f.ms + ' ms' : '' }}
							</span>
							<v-icon small class="cmd-arrow">{{ open === f.id ? 'mdi-chevron-up' : 'mdi-chevron-down' }}</v-icon>
						</div>
						<div v-if="open !== f.id && f.response" class="cmd-resp-short" @click="open = f.id">{{ f.response }}</div>
						<div v-if="open === f.id" class="cmd-detail">
							<div class="cmd-det-meta">
								<span><b>{{ $t('plugins.WorkshopService.commandsReceived.date') }}</b> {{ f.ts.replace('T', ' ') }}</span>
								<span v-if="f.via"><b>{{ $t('plugins.WorkshopService.commandsReceived.came_through') }}</b> {{ f.via }}</span>
								<span v-if="f.ms != null"><b>{{ $t('plugins.WorkshopService.commandsReceived.took') }}</b> {{ f.ms }} ms</span>
								<span><b>{{ $t('plugins.WorkshopService.commandsReceived.type') }}</b> {{ f.reading ? $t('plugins.WorkshopService.commandsReceived.read_only') : $t('plugins.WorkshopService.commandsReceived.changes_something') }}</span>
							</div>
							<div class="cmd-det-tit">{{ $t('plugins.WorkshopService.commandsReceived.origin') }}
								<v-btn x-small text @click="copy(detailText(f), 'o' + f.id)"><v-icon x-small left>{{ copied === 'o' + f.id ? 'mdi-check' : 'mdi-content-copy' }}</v-icon>{{ $t('plugins.WorkshopService.commandsReceived.copy_all') }}</v-btn>
							</div>
							<div v-if="fieldsOrigin(f).length" class="cmd-origin">
								<template v-for="c in fieldsOrigin(f)">
									<span :key="'k' + c[0]" class="cmd-o-k">{{ c[0] }}</span>
									<span :key="'v' + c[0]" class="cmd-o-v">{{ c[1] }}</span>
								</template>
							</div>
							<div v-else class="text-caption grey--text">{{ $t('plugins.WorkshopService.commandsReceived.no_origin_data_command_from_before') }}</div>
							<div class="cmd-det-tit">{{ $t('plugins.WorkshopService.commandsReceived.code') }}
								<v-btn x-small text @click="copy(f.code, 'c' + f.id)"><v-icon x-small left>{{ copied === 'c' + f.id ? 'mdi-check' : 'mdi-content-copy' }}</v-icon>{{ $t('plugins.WorkshopService.common.copy') }}</v-btn>
							</div>
							<pre class="cmd-pre">{{ f.code }}</pre>
							<div class="cmd-det-tit">{{ $t('plugins.WorkshopService.commandsReceived.response') }}
								<v-btn v-if="f.response" x-small text @click="copy(f.response, 'r' + f.id)"><v-icon x-small left>{{ copied === 'r' + f.id ? 'mdi-check' : 'mdi-content-copy' }}</v-icon>{{ $t('plugins.WorkshopService.common.copy') }}</v-btn>
							</div>
							<pre class="cmd-pre">{{ nice(f.response) }}</pre>
						</div>
					</div>
				</template>
			</div>

			<div class="d-flex align-center flex-wrap mt-3" style="gap:8px">
				<v-btn small text :disabled="offset === 0 || loading" @click="load(Math.max(0, offset - limit))"><v-icon small>mdi-chevron-left</v-icon>{{ $t('plugins.WorkshopService.commandsReceived.newest') }}</v-btn>
				<span class="text-caption grey--text">{{ total ? (offset + 1) + '-' + Math.min(total, offset + limit) + $t('plugins.WorkshopService.commandsReceived.of') + total : '' }}</span>
				<v-btn small text :disabled="offset + limit >= (total || 0) || loading" @click="load(offset + limit)">{{ $t('plugins.WorkshopService.commandsReceived.oldest') }}<v-icon small>mdi-chevron-right</v-icon></v-btn>
				<v-spacer />
				<span class="text-caption grey--text">{{ $t('plugins.WorkshopService.commandsReceived.kept_30_days_reads_1_day') }}</span>
				<v-btn small text :color="armed ? 'error' : 'grey'" :disabled="!total" @click="touchDelete()">
					<v-icon small left>mdi-delete-outline</v-icon>{{ armed ? $t('plugins.WorkshopService.commandsReceived.tap_again_delete_the_whole_range') : $t('plugins.WorkshopService.commandsReceived.delete_this_range') }}
				</v-btn>
			</div>
		</v-card-text>
	</v-card>
</template>

<script>
import i18n from '../../i18n'

'use strict'

import { mapActions } from 'vuex'
import { api } from './workshop-api.js'
import { copyText } from './copy.js'

function day(daysBack) {
	const d = new Date(Date.now() - (daysBack || 0) * 86400000);
	return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

const spans = [
	{ id: 'today', text: i18n.t('plugins.WorkshopService.commandsReceived.today'), since: 0, until: 0 },
	{ id: 'yesterday', text: i18n.t('plugins.WorkshopService.commandsReceived.yesterday'), since: 1, until: 1 },
	{ id: '7', text: i18n.t('plugins.WorkshopService.commandsReceived.7_days'), since: 6, until: 0 },
	{ id: '30', text: i18n.t('plugins.WorkshopService.commandsReceived.30_days'), since: 29, until: 0 }
];

const ORIGIN_TXT = {
	page: i18n.t('plugins.WorkshopService.commandsReceived.page'), console: i18n.t('plugins.WorkshopService.commandsReceived.console'), job_file: i18n.t('plugins.WorkshopService.commandsReceived.job_file'), macro: i18n.t('plugins.WorkshopService.commandsReceived.macro'), bridge: i18n.t('plugins.WorkshopService.commandsReceived.g_code_bridge'),
	service: i18n.t('plugins.WorkshopService.commandsReceived.service'), external: i18n.t('plugins.WorkshopService.commandsReceived.external_program'), daemon: 'daemon.g', trigger: i18n.t('plugins.WorkshopService.commandsReceived.event'), panel: i18n.t('plugins.WorkshopService.commandsReceived.board_display'),
	queue: i18n.t('plugins.WorkshopService.commandsReceived.queue'), plugin: i18n.t('plugins.WorkshopService.commandsReceived.another_plugin'), unknown: i18n.t('plugins.WorkshopService.commandsReceived.unknown')
};
const ORIGIN_ICON = {
	page: 'mdi-web', console: 'mdi-console', job_file: 'mdi-file-document-outline', macro: 'mdi-script-text-outline', bridge: 'mdi-lan',
	service: 'mdi-cog-outline', external: 'mdi-arrow-right-bold-outline', daemon: 'mdi-timer-outline', trigger: 'mdi-flash-outline',
	panel: 'mdi-monitor', queue: 'mdi-tray-full', plugin: 'mdi-puzzle-outline', unknown: 'mdi-help-circle-outline'
};
const RESULT_TXT = { ok: i18n.t('plugins.WorkshopService.commandsReceived.ok'), error: i18n.t('plugins.WorkshopService.commandsReceived.with_error_2'), blocked: i18n.t('plugins.WorkshopService.commandsReceived.blocked') };
// origin fields in the detail (in order)
const fields = [
	['kind', i18n.t('plugins.WorkshopService.commandsReceived.origin')], ['channel', i18n.t('plugins.WorkshopService.commandsReceived.channel')], ['label', i18n.t('plugins.WorkshopService.commandsReceived.channel_detail')], ['conn', i18n.t('plugins.WorkshopService.commandsReceived.connection')], ['plugin', i18n.t('plugins.WorkshopService.commandsReceived.plugin_or_page')],
	['tagged', i18n.t('plugins.WorkshopService.commandsReceived.with_own_tag')], ['client', i18n.t('plugins.WorkshopService.commandsReceived.bridge_client')], ['client_ip', i18n.t('plugins.WorkshopService.commandsReceived.bridge_client_ip')], ['addr', i18n.t('plugins.WorkshopService.commandsReceived.client_address')],
	['agent', i18n.t('plugins.WorkshopService.commandsReceived.browser_or_program')], ['referer', i18n.t('plugins.WorkshopService.commandsReceived.source_page')], ['session', i18n.t('plugins.WorkshopService.commandsReceived.dwc_session')], ['job_file', i18n.t('plugins.WorkshopService.commandsReceived.job_file_2')],
	['line', i18n.t('plugins.WorkshopService.commandsReceived.line')], ['file_pos', i18n.t('plugins.WorkshopService.commandsReceived.position_in_the_file')], ['macro', i18n.t('plugins.WorkshopService.commandsReceived.inside_a_macro')], ['result', i18n.t('plugins.WorkshopService.commandsReceived.result')], ['reason', i18n.t('plugins.WorkshopService.commandsReceived.reason')],
	['ms', i18n.t('plugins.WorkshopService.commandsReceived.took_ms')], ['wait_ms', i18n.t('plugins.WorkshopService.commandsReceived.waited_its_turn_ms')]
];

export default {
	props: {
		// (row) => { color, icon }: the same category as the API operations list
		colorOf: { type: Function, default: null },
		// changes with each received command: if today is being viewed, it reloads
		change: { type: String, default: '' }
	},
	data() {
		return {
			spans: spans,
			range: 'today',
			since: day(0),
			until: day(0),
			dates: [day(0), day(0)],
			datesMenu: false,
			kind: 1,
			name: null,
			via: null,
			channel: null,
			kindOrigin: null,
			plugin: null,
			result: null,
			lastHour: null,
			search: '',
			onlyErrors: false,
			rows: [],
			names: [],
			summary: null,
			total: null,
			offset: 0,
			limit: 50,
			loading: false,
			error: null,
			open: null,
			armed: false,
			armedTimer: null,
			inLive: true,
			copied: null
		};
	},
	computed: {
		optionsName() {
			const l = this.names.slice();
			if (this.name && !l.includes(this.name)) {
				l.unshift(this.name);
			}
			return l;
		},
		optionsVia() {
			const l = ((this.summary && this.summary.ways) || []).slice();
			if (this.via && !l.includes(this.via)) {
				l.unshift(this.via);
			}
			return l;
		},
		optionsChannel() {
			return this.optionsOf('channels', this.channel);
		},
		optionsKindOrigin() {
			const l = this.optionsOf('kinds', this.kindOrigin).map(k => ({ value: k, text: this.textOrigin(k) }));
			return l.concat([{ value: '-', text: i18n.t('plugins.WorkshopService.commandsReceived.no_data_older') }]);
		},
		optionsPlugin() {
			return this.optionsOf('plugins', this.plugin);
		},
		optionsResult() {
			return this.optionsOf('results', this.result).map(k => ({ value: k, text: RESULT_TXT[k] || k }));
		},
		// counters of the last hour by origin type
		counters() {
			const k = (this.lastHour && this.lastHour.kind) || {};
			return Object.keys(k).sort((a, b) => k[b] - k[a]).map(id => ({ id, n: k[id], text: this.textOrigin(id) }));
		},
		textDates() {
			const f = s => s.slice(8, 10) + '/' + s.slice(5, 7);
			return this.since === this.until ? f(this.since) : f(this.since) + ' - ' + f(this.until);
		},
		// agrupado por dia y hora: "Hoy 22:00", "09/10 14:00"
		groups() {
			const today = day(0), ayer = day(1);
			const out = [];
			this.rows.forEach(f => {
				const d = f.ts.slice(0, 10), h = f.ts.slice(11, 13);
				const key = d + 'T' + h;
				let g = out[out.length - 1];
				if (!g || g.key !== key) {
					const nd = d === today ? i18n.t('plugins.WorkshopService.commandsReceived.today') : d === ayer ? i18n.t('plugins.WorkshopService.commandsReceived.yesterday') : d.slice(8, 10) + '/' + d.slice(5, 7);
					g = { key: key, title: nd + ' ' + h + ':00', rows: [] };
					out.push(g);
				}
				g.rows.push(f);
			});
			return out;
		}
	},
	watch: {
		change() {
			// only live, on the first page of a range that includes today
			if (this.inLive && this.offset === 0 && this.until >= day(0) && !this.loading && this.open === null) {
				clearTimeout(this.reload);
				this.reload = setTimeout(() => this.load(0), 600);
			}
		}
	},
	mounted() {
		this.load(0);
	},
	beforeDestroy() {
		clearTimeout(this.armedTimer);
		clearTimeout(this.reload);
	},
	methods: {
		...mapActions('machine', ['sendCode']),
		style(f) {
			return (this.colorOf && this.colorOf(f)) || { color: 'grey darken-1', icon: 'mdi-console-line' };
		},
		iconVia(v) {
			v = String(v || '').toLowerCase();
			if (v.includes('http') || v.includes('page')) return 'mdi-web';
			if (v.includes('usb')) return 'mdi-usb';
			if (v.includes('red') || v.includes('telnet') || v.includes('sbc')) return 'mdi-lan';
			if (v.includes('job') || v.includes('file')) return 'mdi-file-document-outline';
			if (v.includes('macro') || v.includes('daemon')) return 'mdi-script-text-outline';
			return 'mdi-arrow-right-bold-outline';
		},
		optionsOf(key, current) {
			const l = ((this.summary && this.summary[key]) || []).slice();
			if (current && current !== '-' && !l.includes(current)) {
				l.unshift(current);
			}
			return l;
		},
		textOrigin(k) {
			return ORIGIN_TXT[k] || k;
		},
		iconOrigin(k) {
			return ORIGIN_ICON[k] || 'mdi-arrow-right-bold-outline';
		},
		// fields with a value of the origin, ready to show: [[name, value], ...]
		fieldsOrigin(f) {
			const o = f.origin || {};
			const out = [];
			fields.forEach(([k, nombre]) => {
				if (o[k] === undefined || o[k] === null || o[k] === '') return;
				let v = o[k];
				if (k === 'kind') v = this.textOrigin(v);
				else if (k === 'result') v = RESULT_TXT[v] || v;
				else if (typeof v === 'boolean') v = v ? i18n.t('plugins.WorkshopService.commandsReceived.yes') : i18n.t('plugins.WorkshopService.commandsReceived.no');
				out.push([nombre, String(v)]);
			});
			return out;
		},
		summaryOrigin(f) {
			const o = f.origin || {};
			return [this.textOrigin(o.kind), o.channel, o.plugin, o.addr || o.client].filter(Boolean).join(' · ');
		},
		// the whole record as text (to paste into a report)
		detailText(f) {
			const l = [i18n.t('plugins.WorkshopService.commandsReceived.date_2') + f.ts.replace('T', ' '), i18n.t('plugins.WorkshopService.commandsReceived.command_2') + f.name, i18n.t('plugins.WorkshopService.commandsReceived.code_2') + f.code];
			this.fieldsOrigin(f).forEach(c => l.push(c[0] + ': ' + c[1]));
			if (f.response) l.push(i18n.t('plugins.WorkshopService.commandsReceived.reply') + f.response);
			return l.join('\n');
		},
		withoutM(c) {
			return String(c || '');
		},
		bar(ms) {
			if (ms == null) return 0;
			return Math.min(100, Math.round(Math.log10(Math.max(1, ms)) / 4 * 100)); // 1 ms .. 10 s
		},
		nice(r) {
			if (!r) return i18n.t('plugins.WorkshopService.common.no_response');
			const s = String(r).trim();
			if (s[0] === '{' || s[0] === '[') {
				try {
					return JSON.stringify(JSON.parse(s), null, 2);
				} catch (e) {
					/* texto tal cual */
				}
			}
			return s;
		},
		copy(text, key) {
			const ready = () => {
				this.copied = key;
				setTimeout(() => { if (this.copied === key) this.copied = null; }, 1500);
			};
			copyText(text).then(ok => { if (ok) ready(); });
		},
		chooseSpan(id) {
			const r = spans.find(x => x.id === id);
			this.range = id;
			this.since = day(r.since);
			this.until = day(r.until);
			this.dates = [this.since, this.until];
			this.load(0);
		},
		onChooseDates(v) {
			if (!v || v.length < 2) return;
			const [a, b] = v.slice().sort();
			this.range = 'other';
			this.since = a;
			this.until = b;
			this.datesMenu = false;
			this.load(0);
		},
		clean(s) {
			return String(s || '').replace(/"/g, "'");
		},
		async load(offset) {
			this.loading = true;
			this.error = null;
			try {
				// API history.list of WorkshopService
				const a = { from: this.since, to: this.until, limit: this.limit, offset, rw: Number(this.kind) || 0 };
				if (this.name) {
					a.name = String(this.name);
				}
				if (this.via) {
					a.via = String(this.via);
				}
				if (this.channel) {
					a.channel = String(this.channel);
				}
				if (this.kindOrigin) {
					a.kind = String(this.kindOrigin);
				}
				if (this.plugin) {
					a.plugin = String(this.plugin);
				}
				if (this.result) {
					a.result = String(this.result);
				}
				if (this.onlyErrors) {
					a.errors = true;
				}
				if (this.search) {
					a.query = String(this.search);
				}
				const r = await api('history.list', a);
				if (r.error) {
					throw new Error(r.error);
				}
				this.rows = r.rows || [];
				this.total = r.total;
				this.names = r.names || [];
				this.summary = r.summary || null;
				this.lastHour = r.last_hour || null;
				this.offset = offset;
			} catch (e) {
				// a refusal of the roles (login / forbidden) is not an old service: only the other errors get that hint
				const refused = e && (e.code === 'login_required' || e.code === 'forbidden');
				this.error = i18n.t('plugins.WorkshopService.commandsReceived.' + (refused ? 'could_not_read_the_history_refused' : 'could_not_read_the_history_x'), { x: e.message || e });
			} finally {
				this.loading = false;
			}
		},
		touchDelete() {
			if (!this.armed) {
				this.armed = true;
				clearTimeout(this.armedTimer);
				this.armedTimer = setTimeout(() => { this.armed = false; }, 4000);
				return;
			}
			this.armed = false;
			this.remove();
		},
		async remove() {
			try {
				await api('history.delete', { from: this.since, to: this.until });
			} finally {
				this.load(0);
			}
		}
	}
};
</script>

<style scoped>
.cmd-live {
	font-size: 12px;
	font-weight: normal;
	color: var(--tp-faint, #9e9e9e);
	display: inline-flex;
	align-items: center;
	gap: 5px;
}
.cmd-point {
	width: 8px;
	height: 8px;
	border-radius: 50%;
	background: #9e9e9e;
}
.cmd-point.on {
	background: var(--wf-ok);
}
.cmd-summary {
	display: grid;
	grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));
	gap: 8px;
}
.cmd-num {
	border: 1px solid var(--wf-line);
	border-radius: 8px;
	padding: 6px 10px;
}
.cmd-num-v {
	font-size: 20px;
	font-weight: 500;
	font-variant-numeric: tabular-nums;
}
.cmd-num-t {
	font-size: 12px;
	color: var(--tp-faint, #9e9e9e);
}
.cmd-num-err {
	border-color: var(--wf-warn);
}
.cmd-num-err .cmd-num-v {
	color: var(--wf-warn);
}
.cmd-field {
	max-width: 190px;
}
.cmd-empty {
	text-align: center;
	padding: 18px;
	color: var(--tp-faint, #9e9e9e);
	border: 1px dashed rgba(128, 128, 128, 0.3);
	border-radius: 8px;
}
.cmd-list {
	max-height: 560px;
	overflow-y: auto;
	border: 1px solid var(--wf-line);
	border-radius: 8px;
}
.cmd-group {
	position: sticky;
	top: 0;
	z-index: 1;
	font-size: 12px;
	font-weight: 600;
	padding: 4px 10px;
	background: var(--wf-surface);
	border-bottom: 1px solid var(--wf-line);
}
.cmd-row {
	border-bottom: 1px solid var(--wf-line);
}
.cmd-row:hover {
	background: rgba(128, 128, 128, 0.06);
}
.cmd-row.open {
	background: var(--wf-soft);
}
.cmd-cab {
	display: flex;
	align-items: center;
	gap: 6px;
	min-width: 0;
	padding: 6px 10px;
	cursor: pointer;
}
.cmd-hour {
	font-size: 12px;
	color: var(--tp-faint, #9e9e9e);
	font-variant-numeric: tabular-nums;
	white-space: nowrap;
}
.cmd-name {
	flex: none;
}
.cmd-code {
	flex: 1 1 auto;
	font-size: 12px;
	white-space: nowrap;
	overflow: hidden;
	text-overflow: ellipsis;
	min-width: 0;
}
.cmd-via {
	font-size: 11px;
	white-space: nowrap;
	color: var(--tp-faint, #9e9e9e);
	display: inline-flex;
	align-items: center;
	gap: 3px;
}
.cmd-ms {
	font-size: 12px;
	white-space: nowrap;
	font-variant-numeric: tabular-nums;
	display: inline-flex;
	align-items: center;
	gap: 5px;
	min-width: 92px;
	justify-content: flex-end;
}
.cmd-ms-bar {
	display: inline-block;
	width: 36px;
	height: 4px;
	border-radius: 2px;
	background: rgba(128, 128, 128, 0.2);
	overflow: hidden;
}
.cmd-ms-bar i {
	display: block;
	height: 100%;
}
.cmd-arrow {
	flex: none;
}
.cmd-resp-short {
	font-size: 12px;
	color: var(--tp-faint, #9e9e9e);
	white-space: nowrap;
	overflow: hidden;
	text-overflow: ellipsis;
	padding: 0 10px 6px 36px;
	cursor: pointer;
}
.cmd-detail {
	padding: 4px 10px 10px 36px;
}
.cmd-det-meta {
	display: flex;
	flex-wrap: wrap;
	gap: 4px 14px;
	font-size: 12px;
	margin-bottom: 6px;
}
.cmd-det-meta b {
	font-weight: 500;
	color: var(--tp-faint, #9e9e9e);
	margin-right: 3px;
}
.cmd-det-tit {
	font-size: 12px;
	font-weight: 500;
	display: flex;
	align-items: center;
	gap: 6px;
	margin-top: 4px;
}
.cmd-pre {
	font-size: 12px;
	font-family: monospace;
	white-space: pre-wrap;
	word-break: break-all;
	margin: 2px 0 4px 0;
	padding: 6px 8px;
	border-radius: 4px;
	background: rgba(0, 0, 0, 0.25);
	max-height: 260px;
	overflow: auto;
}
.cmd-hour-origin {
	display: flex;
	flex-wrap: wrap;
	align-items: center;
	gap: 6px;
}
.cmd-lock {
	flex: none;
}
.cmd-origin {
	display: grid;
	grid-template-columns: max-content 1fr;
	gap: 2px 12px;
	font-size: 12px;
	margin: 2px 0 4px 0;
}
.cmd-o-k {
	color: var(--tp-faint, #9e9e9e);
}
.cmd-o-v {
	word-break: break-all;
}
@media (max-width: 700px) {
	.cmd-via,
	.cmd-ms-bar {
		display: none;
	}
	.cmd-field {
		max-width: none;
		flex: 1 1 140px;
	}
}
</style>
