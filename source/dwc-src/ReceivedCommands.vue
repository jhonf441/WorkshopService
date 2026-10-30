<template>
	<v-card class="mb-3">
		<!-- History of received commands, redesign 2026-10-10 ("redesign that
		     history of received commands better"): by default only what CHANGES something
		     (the pages read all the time and covered what matters), quick ranges,
		     summary, grouped by hour and the detail with copy. -->
		<v-card-title class="d-flex align-center flex-wrap" style="gap:8px">
			<span><v-icon size="small" class="mr-2 svx-ico">mdi-console-line</v-icon>{{ $t('plugins.WorkshopService.common.received_commands') }}</span>
			<span class="cmd-live" :title="inLive ? $t('plugins.WorkshopService.commandsReceived.updates_by_itself_with_each_new') : $t('plugins.WorkshopService.commandsReceived.paused_it_doesn_t_update_by')">
				<span class="cmd-point" :class="{ on: inLive }" />{{ inLive ? $t('plugins.WorkshopService.commandsReceived.live') : $t('plugins.WorkshopService.commandsReceived.paused') }}
			</span>
			<v-spacer />
			<v-btn size="small" variant="text" @click="inLive = !inLive"><v-icon size="small" start>{{ inLive ? 'mdi-pause' : 'mdi-play' }}</v-icon>{{ inLive ? $t('plugins.WorkshopService.common.pause') : $t('plugins.WorkshopService.common.follow') }}</v-btn>
			<v-btn size="small" variant="text" :loading="loading" @click="load(0)"><v-icon size="small" start>mdi-refresh</v-icon>{{ $t('plugins.WorkshopService.common.refresh') }}</v-btn>
		</v-card-title>
		<v-card-text>
			<!-- resumen del rango -->
			<div v-if="summary" class="cmd-summary">
				<div class="cmd-num">
					<div class="cmd-num-v">{{ summary.all - summary.readings }}</div>
					<div class="cmd-num-t"><v-icon size="x-small">mdi-pencil-outline</v-icon> {{ $t('plugins.WorkshopService.commandsReceived.change_something') }}</div>
				</div>
				<div class="cmd-num">
					<div class="cmd-num-v">{{ summary.readings }}</div>
					<div class="cmd-num-t"><v-icon size="x-small">mdi-eye-outline</v-icon> {{ $t('plugins.WorkshopService.commandsReceived.reads') }}</div>
				</div>
				<div class="cmd-num" :class="{ 'cmd-num-err': summary.errors }">
					<div class="cmd-num-v">{{ summary.errors }}</div>
					<div class="cmd-num-t"><v-icon size="x-small">mdi-alert-circle-outline</v-icon> {{ $t('plugins.WorkshopService.commandsReceived.with_error') }}</div>
				</div>
				<div class="cmd-num">
					<div class="cmd-num-v">{{ summary.ms_avg != null ? summary.ms_avg + ' ms' : '-' }}</div>
					<div class="cmd-num-t">{{ $t('plugins.WorkshopService.commandsReceived.average_time') }}<template v-if="summary.ms_max != null"> {{ $t('plugins.WorkshopService.commandsReceived.max_n', { n: summary.ms_max }) }}</template></div>
				</div>
			</div>

			<!-- last hour by origin (ring in the service's memory): tapping one filters -->
			<div v-if="lastHour && lastHour.total" class="cmd-hour-origin mt-3">
				<span class="text-body-small text-medium-emphasis">{{ $t('plugins.WorkshopService.commandsReceived.last_hour_n', { n: lastHour.total }) }}</span>
				<v-chip
					v-for="k in counters" :key="k.id" size="x-small" label :variant="kindOrigin === k.id ? 'flat' : 'outlined'" :color="kindOrigin === k.id ? 'primary' : undefined"
					:title="$t('plugins.WorkshopService.commandsReceived.commands_last_hour_that_came_as', { x: k.text })" @click="kindOrigin = kindOrigin === k.id ? null : k.id; if (kindOrigin) kind = 0"
				>
					<v-icon start size="x-small">{{ iconOrigin(k.id) }}</v-icon>{{ k.text }} {{ k.n }}
				</v-chip>
				<v-chip v-if="lastHour.result && lastHour.result.blocked" size="x-small" label variant="outlined" color="warning" @click="result = result === 'blocked' ? null : 'blocked'">
					<v-icon start size="x-small">mdi-cancel</v-icon>{{ $t('plugins.WorkshopService.commandsReceived.blocked_n', { n: lastHour.result.blocked }) }}
				</v-chip>
				<v-chip v-if="lastHour.result && lastHour.result.error" size="x-small" label variant="outlined" color="error" @click="result = result === 'error' ? null : 'error'">
					<v-icon start size="x-small">mdi-alert-circle-outline</v-icon>{{ $t('plugins.WorkshopService.commandsReceived.with_error_n', { n: lastHour.result.error }) }}
				</v-chip>
			</div>

			<!-- cuando -->
			<div class="d-flex align-center flex-wrap mt-3" style="gap:6px">
				<v-chip v-for="r in spans" :key="r.id" size="small" :color="range === r.id ? 'primary' : undefined" :variant="range === r.id ? 'flat' : 'outlined'" @click="chooseSpan(r.id)">{{ r.text }}</v-chip>
				<v-menu v-model="datesMenu" :close-on-content-click="false">
					<template #activator="{ props: activator }">
						<v-chip size="small" :color="range === 'other' ? 'primary' : undefined" :variant="range === 'other' ? 'flat' : 'outlined'" v-bind="activator">
							<v-icon start size="small">mdi-calendar-range</v-icon>{{ range === 'other' ? textDates : $t('plugins.WorkshopService.commandsReceived.pick_dates') }}
						</v-chip>
					</template>
					<v-card class="pa-3" min-width="260">
						<v-text-field v-model="dates[0]" type="date" :label="$t('plugins.WorkshopService.commandsReceived.date_from')" density="compact" variant="outlined" hide-details class="mb-2" />
						<v-text-field v-model="dates[1]" type="date" :label="$t('plugins.WorkshopService.commandsReceived.date_to')" density="compact" variant="outlined" hide-details class="mb-2" />
						<v-btn size="small" color="primary" block @click="applyDates">{{ $t('plugins.WorkshopService.commandsReceived.apply_dates') }}</v-btn>
					</v-card>
				</v-menu>
			</div>

			<!-- que -->
			<div class="d-flex align-center flex-wrap mt-3" style="gap:8px">
				<v-btn-toggle v-model="kind" mandatory density="compact" color="primary">
					<v-btn size="small" :value="1" :title="$t('plugins.WorkshopService.commandsReceived.what_changes_something_settings_jobs_the')"><v-icon start size="small">mdi-pencil-outline</v-icon>{{ $t('plugins.WorkshopService.common.change_something') }}</v-btn>
					<v-btn size="small" :value="2" :title="$t('plugins.WorkshopService.commandsReceived.queries_that_only_read_pages_ask')"><v-icon start size="small">mdi-eye-outline</v-icon>{{ $t('plugins.WorkshopService.commandsReceived.readings') }}</v-btn>
					<v-btn size="small" :value="0">{{ $t('plugins.WorkshopService.common.all') }}</v-btn>
				</v-btn-toggle>
				<v-select v-model="name" :items="optionsName" :label="$t('plugins.WorkshopService.commandsReceived.command')" density="compact" hide-details clearable variant="outlined" class="cmd-field" />
				<v-select v-model="via" :items="optionsVia" :label="$t('plugins.WorkshopService.commandsReceived.came_through')" density="compact" hide-details clearable variant="outlined" class="cmd-field" />
				<v-select v-model="channel" :items="optionsChannel" :label="$t('plugins.WorkshopService.commandsReceived.channel')" density="compact" hide-details clearable variant="outlined" class="cmd-field" />
				<v-select v-model="kindOrigin" :items="optionsKindOrigin" item-title="text" item-value="value" :label="$t('plugins.WorkshopService.commandsReceived.origin')" density="compact" hide-details clearable variant="outlined" class="cmd-field" />
				<v-select v-model="plugin" :items="optionsPlugin" :label="$t('plugins.WorkshopService.commandsReceived.plugin_or_page')" density="compact" hide-details clearable variant="outlined" class="cmd-field" />
				<v-select v-model="result" :items="optionsResult" item-title="text" item-value="value" :label="$t('plugins.WorkshopService.commandsReceived.result')" density="compact" hide-details clearable variant="outlined" class="cmd-field" />
				<v-text-field v-model="search" :label="$t('plugins.WorkshopService.common.find')" density="compact" hide-details clearable variant="outlined" prepend-inner-icon="mdi-magnify" class="cmd-field" @keyup.enter="load(0)" @click:clear="search = ''; load(0)" />
				<v-switch v-model="onlyErrors" :label="$t('plugins.WorkshopService.commandsReceived.errors_only')" density="compact" hide-details color="primary" />
			</div>

			<div v-if="error" class="text-error text-body-medium mt-3">{{ error }}</div>
			<div v-else-if="!rows.length && !loading" class="cmd-empty mt-3">
				<v-icon color="grey">mdi-inbox-outline</v-icon>
				<div>{{ kind === 1 ? $t('plugins.WorkshopService.commandsReceived.no_command_that_changes_something_in') : $t('plugins.WorkshopService.commandsReceived.no_commands_in_this_range') }}</div>
				<div v-if="kind === 1 && summary && summary.readings" class="text-body-small">{{ $t('plugins.WorkshopService.commandsReceived.there_are_n_reads', { n: summary.readings }) }} <a href="#" @click.prevent="kind = 2">{{ $t('plugins.WorkshopService.commandsReceived.show_them') }}</a>.</div>
			</div>
			<div v-else class="cmd-list mt-3">
				<template v-for="g in groups" :key="g.key">
					<div class="cmd-group">{{ g.title }} <span class="text-medium-emphasis">· {{ g.rows.length }}</span></div>
					<div v-for="f in g.rows" :key="f.id" class="cmd-row" :class="{ 'cmd-err': !f.ok, open: open === f.id }">
						<div class="cmd-cab" @click="open = open === f.id ? null : f.id">
							<v-icon size="small" :color="f.ok ? 'success' : 'warning'" :title="f.ok ? $t('plugins.WorkshopService.commandsReceived.answered_ok') : $t('plugins.WorkshopService.commandsReceived.failed')">{{ f.ok ? 'mdi-check-circle' : 'mdi-alert-circle' }}</v-icon>
							<span class="cmd-hour">{{ f.ts.slice(11, 19) }}</span>
							<v-chip size="x-small" label variant="flat" class="cmd-name" :color="style(f).color"><v-icon start size="x-small">{{ style(f).icon }}</v-icon>{{ f.name }}</v-chip>
							<v-icon size="x-small" :color="f.reading ? 'grey' : 'orange-darken-2'" :title="f.reading ? $t('plugins.WorkshopService.common.read_only') : $t('plugins.WorkshopService.common.changes_something')">{{ f.reading ? 'mdi-eye-outline' : 'mdi-pencil-outline' }}</v-icon>
							<code class="cmd-code">{{ withoutM(f.code) }}</code>
							<span v-if="f.origin && f.origin.kind" class="cmd-via" :title="$t('plugins.WorkshopService.commandsReceived.origin_x', { x: summaryOrigin(f) })">
								<v-icon size="x-small">{{ iconOrigin(f.origin.kind) }}</v-icon>{{ textOrigin(f.origin.kind) }}<template v-if="f.origin.plugin">: {{ f.origin.plugin }}</template>
							</span>
							<span v-else-if="f.via" class="cmd-via" :title="$t('plugins.WorkshopService.commandsReceived.came_through_x', { x: f.via })"><v-icon size="x-small">{{ iconVia(f.via) }}</v-icon>{{ f.via }}</span>
							<v-chip v-if="f.origin && f.origin.result === 'blocked'" size="x-small" label variant="outlined" color="warning" class="cmd-lock" :title="f.origin.reason">{{ $t('plugins.WorkshopService.commandsReceived.blocked') }}</v-chip>
							<span class="cmd-ms" :title="f.ms != null ? $t('plugins.WorkshopService.commandsReceived.took_n_ms', { n: f.ms }) : ''">
								<span class="cmd-ms-bar"><i :style="{ width: bar(f.ms) + '%', background: f.ms > 2000 ? '#ffa726' : '#64b5f6' }" /></span>
								{{ f.ms != null ? f.ms + ' ms' : '' }}
							</span>
							<v-icon size="small" class="cmd-arrow">{{ open === f.id ? 'mdi-chevron-up' : 'mdi-chevron-down' }}</v-icon>
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
								<v-btn size="x-small" variant="text" @click="copy(detailText(f), 'o' + f.id)"><v-icon size="x-small" start>{{ copied === 'o' + f.id ? 'mdi-check' : 'mdi-content-copy' }}</v-icon>{{ $t('plugins.WorkshopService.commandsReceived.copy_all') }}</v-btn>
							</div>
							<div v-if="fieldsOrigin(f).length" class="cmd-origin">
								<template v-for="c in fieldsOrigin(f)" :key="c[0]">
									<span class="cmd-o-k">{{ c[0] }}</span>
									<span class="cmd-o-v">{{ c[1] }}</span>
								</template>
							</div>
							<div v-else class="text-body-small text-medium-emphasis">{{ $t('plugins.WorkshopService.commandsReceived.no_origin_data_command_from_before') }}</div>
							<div class="cmd-det-tit">{{ $t('plugins.WorkshopService.commandsReceived.code') }}
								<v-btn size="x-small" variant="text" @click="copy(f.code, 'c' + f.id)"><v-icon size="x-small" start>{{ copied === 'c' + f.id ? 'mdi-check' : 'mdi-content-copy' }}</v-icon>{{ $t('plugins.WorkshopService.common.copy') }}</v-btn>
							</div>
							<pre class="cmd-pre">{{ f.code }}</pre>
							<div class="cmd-det-tit">{{ $t('plugins.WorkshopService.commandsReceived.response') }}
								<v-btn v-if="f.response" size="x-small" variant="text" @click="copy(f.response, 'r' + f.id)"><v-icon size="x-small" start>{{ copied === 'r' + f.id ? 'mdi-check' : 'mdi-content-copy' }}</v-icon>{{ $t('plugins.WorkshopService.common.copy') }}</v-btn>
							</div>
							<pre class="cmd-pre">{{ nice(f.response) }}</pre>
						</div>
					</div>
				</template>
			</div>

			<div class="d-flex align-center flex-wrap mt-3" style="gap:8px">
				<v-btn size="small" variant="text" :disabled="offset === 0 || loading" @click="load(Math.max(0, offset - limit))"><v-icon size="small">mdi-chevron-left</v-icon>{{ $t('plugins.WorkshopService.commandsReceived.newest') }}</v-btn>
				<span class="text-body-small text-medium-emphasis">{{ total ? (offset + 1) + '-' + Math.min(total, offset + limit) + $t('plugins.WorkshopService.commandsReceived.of') + total : '' }}</span>
				<v-btn size="small" variant="text" :disabled="offset + limit >= (total || 0) || loading" @click="load(offset + limit)">{{ $t('plugins.WorkshopService.commandsReceived.oldest') }}<v-icon size="small">mdi-chevron-right</v-icon></v-btn>
				<v-spacer />
				<span class="text-body-small text-medium-emphasis">{{ $t('plugins.WorkshopService.commandsReceived.kept_30_days_reads_1_day') }}</span>
				<v-btn size="small" variant="text" :color="armed ? 'error' : 'grey'" :disabled="!total" @click="touchDelete()">
					<v-icon size="small" start>mdi-delete-outline</v-icon>{{ armed ? $t('plugins.WorkshopService.commandsReceived.tap_again_delete_the_whole_range') : $t('plugins.WorkshopService.commandsReceived.delete_this_range') }}
				</v-btn>
			</div>
		</v-card-text>
	</v-card>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { i18n } from './dwc-host.js'
import { api } from './workshop-api.js'
import { copyText } from './copy.js'

function day(daysBack) {
	const d = new Date(Date.now() - (daysBack || 0) * 86400000)
	return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

const spans = [
	{ id: 'today', text: i18n.t('plugins.WorkshopService.commandsReceived.today'), since: 0, until: 0 },
	{ id: 'yesterday', text: i18n.t('plugins.WorkshopService.commandsReceived.yesterday'), since: 1, until: 1 },
	{ id: '7', text: i18n.t('plugins.WorkshopService.commandsReceived.7_days'), since: 6, until: 0 },
	{ id: '30', text: i18n.t('plugins.WorkshopService.commandsReceived.30_days'), since: 29, until: 0 }
]

const ORIGIN_TXT = {
	page: i18n.t('plugins.WorkshopService.commandsReceived.page'), console: i18n.t('plugins.WorkshopService.commandsReceived.console'), job_file: i18n.t('plugins.WorkshopService.commandsReceived.job_file'), macro: i18n.t('plugins.WorkshopService.commandsReceived.macro'), bridge: i18n.t('plugins.WorkshopService.commandsReceived.g_code_bridge'),
	service: i18n.t('plugins.WorkshopService.commandsReceived.service'), external: i18n.t('plugins.WorkshopService.commandsReceived.external_program'), daemon: 'daemon.g', trigger: i18n.t('plugins.WorkshopService.commandsReceived.event'), panel: i18n.t('plugins.WorkshopService.commandsReceived.board_display'),
	queue: i18n.t('plugins.WorkshopService.commandsReceived.queue'), plugin: i18n.t('plugins.WorkshopService.commandsReceived.another_plugin'), unknown: i18n.t('plugins.WorkshopService.commandsReceived.unknown')
}
const ORIGIN_ICON = {
	page: 'mdi-web', console: 'mdi-console', job_file: 'mdi-file-document-outline', macro: 'mdi-script-text-outline', bridge: 'mdi-lan',
	service: 'mdi-cog-outline', external: 'mdi-arrow-right-bold-outline', daemon: 'mdi-timer-outline', trigger: 'mdi-flash-outline',
	panel: 'mdi-monitor', queue: 'mdi-tray-full', plugin: 'mdi-puzzle-outline', unknown: 'mdi-help-circle-outline'
}
const RESULT_TXT = { ok: i18n.t('plugins.WorkshopService.commandsReceived.ok'), error: i18n.t('plugins.WorkshopService.commandsReceived.with_error_2'), blocked: i18n.t('plugins.WorkshopService.commandsReceived.blocked') }
// origin fields in the detail (in order)
const fields = [
	['kind', i18n.t('plugins.WorkshopService.commandsReceived.origin')], ['channel', i18n.t('plugins.WorkshopService.commandsReceived.channel')], ['label', i18n.t('plugins.WorkshopService.commandsReceived.channel_detail')], ['conn', i18n.t('plugins.WorkshopService.commandsReceived.connection')], ['plugin', i18n.t('plugins.WorkshopService.commandsReceived.plugin_or_page')],
	['tagged', i18n.t('plugins.WorkshopService.commandsReceived.with_own_tag')], ['client', i18n.t('plugins.WorkshopService.commandsReceived.bridge_client')], ['client_ip', i18n.t('plugins.WorkshopService.commandsReceived.bridge_client_ip')], ['addr', i18n.t('plugins.WorkshopService.commandsReceived.client_address')],
	['agent', i18n.t('plugins.WorkshopService.commandsReceived.browser_or_program')], ['referer', i18n.t('plugins.WorkshopService.commandsReceived.source_page')], ['session', i18n.t('plugins.WorkshopService.commandsReceived.dwc_session')], ['job_file', i18n.t('plugins.WorkshopService.commandsReceived.job_file_2')],
	['line', i18n.t('plugins.WorkshopService.commandsReceived.line')], ['file_pos', i18n.t('plugins.WorkshopService.commandsReceived.position_in_the_file')], ['macro', i18n.t('plugins.WorkshopService.commandsReceived.inside_a_macro')], ['result', i18n.t('plugins.WorkshopService.commandsReceived.result')], ['reason', i18n.t('plugins.WorkshopService.commandsReceived.reason')],
	['ms', i18n.t('plugins.WorkshopService.commandsReceived.took_ms')], ['wait_ms', i18n.t('plugins.WorkshopService.commandsReceived.waited_its_turn_ms')]
]

const props = defineProps({
	// (row) => { color, icon }: the same category as the API operations list
	colorOf: { type: Function, default: null },
	// changes with each received command: if today is being viewed, it reloads
	change: { type: String, default: '' }
})

const range = ref('today')
const since = ref(day(0))
const until = ref(day(0))
const dates = ref([day(0), day(0)])
const datesMenu = ref(false)
const kind = ref(1)
const name = ref(null)
const via = ref(null)
const channel = ref(null)
const kindOrigin = ref(null)
const plugin = ref(null)
const result = ref(null)
const lastHour = ref(null)
const search = ref('')
const onlyErrors = ref(false)
const rows = ref([])
const names = ref([])
const summary = ref(null)
const total = ref(null)
const offset = ref(0)
const limit = 50
const loading = ref(false)
const error = ref(null)
const open = ref(null)
const armed = ref(false)
const inLive = ref(true)
const copied = ref(null)
let armedTimer = null
let reload = null

const optionsName = computed(() => {
	const l = names.value.slice()
	if (name.value && !l.includes(name.value)) l.unshift(name.value)
	return l
})
const optionsVia = computed(() => {
	const l = ((summary.value && summary.value.ways) || []).slice()
	if (via.value && !l.includes(via.value)) l.unshift(via.value)
	return l
})
const optionsChannel = computed(() => optionsOf('channels', channel.value))
const optionsKindOrigin = computed(() => {
	const l = optionsOf('kinds', kindOrigin.value).map(k => ({ value: k, text: textOrigin(k) }))
	return l.concat([{ value: '-', text: i18n.t('plugins.WorkshopService.commandsReceived.no_data_older') }])
})
const optionsPlugin = computed(() => optionsOf('plugins', plugin.value))
const optionsResult = computed(() => optionsOf('results', result.value).map(k => ({ value: k, text: RESULT_TXT[k] || k })))
// counters of the last hour by origin type
const counters = computed(() => {
	const k = (lastHour.value && lastHour.value.kind) || {}
	return Object.keys(k).sort((a, b) => k[b] - k[a]).map(id => ({ id, n: k[id], text: textOrigin(id) }))
})
const textDates = computed(() => {
	const f = s => s.slice(8, 10) + '/' + s.slice(5, 7)
	return since.value === until.value ? f(since.value) : f(since.value) + ' - ' + f(until.value)
})
// grouped by day and hour: "Today 22:00", "09/10 14:00"
const groups = computed(() => {
	const today = day(0), yesterday = day(1)
	const out = []
	rows.value.forEach(f => {
		const d = f.ts.slice(0, 10), h = f.ts.slice(11, 13)
		const key = d + 'T' + h
		let g = out[out.length - 1]
		if (!g || g.key !== key) {
			const nd = d === today ? i18n.t('plugins.WorkshopService.commandsReceived.today') : d === yesterday ? i18n.t('plugins.WorkshopService.commandsReceived.yesterday') : d.slice(8, 10) + '/' + d.slice(5, 7)
			g = { key: key, title: nd + ' ' + h + ':00', rows: [] }
			out.push(g)
		}
		g.rows.push(f)
	})
	return out
})

// a filter changed (typed in a field, picked from a chip or cleared): one reload from the first page. The watcher batches
// several changes made together (a chip sets the origin and the kind at once).
watch([kind, name, via, channel, kindOrigin, plugin, result, onlyErrors], () => load(0))

watch(() => props.change, () => {
	// only live, on the first page of a range that includes today
	if (inLive.value && offset.value === 0 && until.value >= day(0) && !loading.value && open.value === null) {
		clearTimeout(reload)
		reload = setTimeout(() => load(0), 600)
	}
})

onMounted(() => { load(0) })
onBeforeUnmount(() => {
	clearTimeout(armedTimer)
	clearTimeout(reload)
})

function style(f) {
	return (props.colorOf && props.colorOf(f)) || { color: 'grey-darken-1', icon: 'mdi-console-line' }
}
function iconVia(v) {
	v = String(v || '').toLowerCase()
	if (v.includes('http') || v.includes('page')) return 'mdi-web'
	if (v.includes('usb')) return 'mdi-usb'
	if (v.includes('red') || v.includes('telnet') || v.includes('sbc')) return 'mdi-lan'
	if (v.includes('job') || v.includes('file')) return 'mdi-file-document-outline'
	if (v.includes('macro') || v.includes('daemon')) return 'mdi-script-text-outline'
	return 'mdi-arrow-right-bold-outline'
}
function optionsOf(key, current) {
	const l = ((summary.value && summary.value[key]) || []).slice()
	if (current && current !== '-' && !l.includes(current)) l.unshift(current)
	return l
}
function textOrigin(k) {
	return ORIGIN_TXT[k] || k
}
function iconOrigin(k) {
	return ORIGIN_ICON[k] || 'mdi-arrow-right-bold-outline'
}
// fields with a value of the origin, ready to show: [[name, value], ...]
function fieldsOrigin(f) {
	const o = f.origin || {}
	const out = []
	fields.forEach(([k, label]) => {
		if (o[k] === undefined || o[k] === null || o[k] === '') return
		let v = o[k]
		if (k === 'kind') v = textOrigin(v)
		else if (k === 'result') v = RESULT_TXT[v] || v
		else if (typeof v === 'boolean') v = v ? i18n.t('plugins.WorkshopService.commandsReceived.yes') : i18n.t('plugins.WorkshopService.commandsReceived.no')
		out.push([label, String(v)])
	})
	return out
}
function summaryOrigin(f) {
	const o = f.origin || {}
	return [textOrigin(o.kind), o.channel, o.plugin, o.addr || o.client].filter(Boolean).join(' · ')
}
// the whole record as text (to paste into a report)
function detailText(f) {
	const l = [i18n.t('plugins.WorkshopService.commandsReceived.date_2') + f.ts.replace('T', ' '), i18n.t('plugins.WorkshopService.commandsReceived.command_2') + f.name, i18n.t('plugins.WorkshopService.commandsReceived.code_2') + f.code]
	fieldsOrigin(f).forEach(c => l.push(c[0] + ': ' + c[1]))
	if (f.response) l.push(i18n.t('plugins.WorkshopService.commandsReceived.reply') + f.response)
	return l.join('\n')
}
function withoutM(c) {
	return String(c || '')
}
function bar(ms) {
	if (ms == null) return 0
	return Math.min(100, Math.round(Math.log10(Math.max(1, ms)) / 4 * 100)) // 1 ms .. 10 s
}
function nice(r) {
	if (!r) return i18n.t('plugins.WorkshopService.common.no_response')
	const s = String(r).trim()
	if (s[0] === '{' || s[0] === '[') {
		try {
			return JSON.stringify(JSON.parse(s), null, 2)
		} catch (e) {
			/* text as it is */
		}
	}
	return s
}
function copy(text, key) {
	const ready = () => {
		copied.value = key
		setTimeout(() => { if (copied.value === key) copied.value = null }, 1500)
	}
	copyText(text).then(ok => { if (ok) ready() })
}
function chooseSpan(id) {
	const r = spans.find(x => x.id === id)
	range.value = id
	since.value = day(r.since)
	until.value = day(r.until)
	dates.value = [since.value, until.value]
	load(0)
}
// the two dates of the menu were typed: the range is those days (in order)
function applyDates() {
	const v = dates.value
	if (!v || !v[0] || !v[1]) return
	const [a, b] = v.slice().sort()
	range.value = 'other'
	since.value = a
	until.value = b
	datesMenu.value = false
	load(0)
}
async function load(from) {
	loading.value = true
	error.value = null
	try {
		// API history.list of WorkshopService
		const a = { from: since.value, to: until.value, limit, offset: from, rw: Number(kind.value) || 0 }
		if (name.value) a.name = String(name.value)
		if (via.value) a.via = String(via.value)
		if (channel.value) a.channel = String(channel.value)
		if (kindOrigin.value) a.kind = String(kindOrigin.value)
		if (plugin.value) a.plugin = String(plugin.value)
		if (result.value) a.result = String(result.value)
		if (onlyErrors.value) a.errors = true
		if (search.value) a.query = String(search.value)
		const r = await api('history.list', a)
		if (r.error) throw new Error(r.error)
		rows.value = r.rows || []
		total.value = r.total
		names.value = r.names || []
		summary.value = r.summary || null
		lastHour.value = r.last_hour || null
		offset.value = from
	} catch (e) {
		// a refusal of the roles (login / forbidden) is not an old service: only the other errors get that hint
		const refused = e && (e.code === 'login_required' || e.code === 'forbidden')
		error.value = i18n.t('plugins.WorkshopService.commandsReceived.' + (refused ? 'could_not_read_the_history_refused' : 'could_not_read_the_history_x'), { x: e.message || e })
	} finally {
		loading.value = false
	}
}
function touchDelete() {
	if (!armed.value) {
		armed.value = true
		clearTimeout(armedTimer)
		armedTimer = setTimeout(() => { armed.value = false }, 4000)
		return
	}
	armed.value = false
	remove()
}
async function remove() {
	try {
		await api('history.delete', { from: since.value, to: until.value })
	} finally {
		load(0)
	}
}
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
