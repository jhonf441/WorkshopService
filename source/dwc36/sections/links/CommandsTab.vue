<template>
	<!-- Connections > Commands received: what asked the service to do something, when and from where. By default only what CHANGES something (the
	     pages read all the time and would cover what matters). Quick ranges, the figures of the range, the filters folded away, a table of five
	     columns that opens the detail of a command (origin, code, response, with copy), "load more", and deleting a range (administrator, level 3).
	     Updates by itself with each new command unless it is paused. Prop: active (this tab is in view). -->
	<div class="sv-links-commands">
		<section class="sv-card" aria-labelledby="sv-lc-title" data-card="commands">
			<div class="sv-card-head">
				<h2 id="sv-lc-title"><span class="mdi mdi-console-line sv-ico" aria-hidden="true" />{{ t('common.received_commands') }}</h2>
				<span class="sv-age" data-part="live" :title="t(live ? 'commandsReceived.updates_by_itself_with_each_new' : 'commandsReceived.paused_it_doesn_t_update_by')"><span class="mdi sv-ico sv-ico-s" :class="live ? 'mdi-record-circle-outline' : 'mdi-pause-circle-outline'" aria-hidden="true" />{{ t(live ? 'commandsReceived.live' : 'commandsReceived.paused') }}</span>
				<button type="button" class="wf-btn sv-btn sv-text" data-act="live" @click="live = !live">{{ t(live ? 'common.pause' : 'common.follow') }}</button>
				<button type="button" class="wf-btn sv-btn" data-act="refresh" @click="load(0)"><span class="mdi mdi-refresh sv-ico sv-ico-s" aria-hidden="true" />{{ t('common.refresh') }}</button>
			</div>
			<wf-zone class="sv-zone-host" :status="zone" :error="error" :lock="zoneLock(lock)" :empty-title="t('commandsReceived.no_commands_in_this_range')" @retry="load(0)" @sign-in="signIn">
				<div v-if="fig" class="sv-stats" data-part="figures">
					<div class="sv-stat" data-stat="changes"><b>{{ fig.changes }}</b><span>{{ t('commandsReceived.change_something') }}</span></div>
					<div class="sv-stat" data-stat="reads"><b>{{ fig.readings }}</b><span>{{ t('commandsReceived.reads') }}</span></div>
					<div class="sv-stat" data-stat="errors" :data-level="fig.errors ? 'error' : null"><b>{{ fig.errors }}</b><span>{{ t('commandsReceived.with_error') }}</span></div>
					<div class="sv-stat" data-stat="time"><b>{{ fig.avg === null ? '–' : fig.avg + ' ms' }}</b><span>{{ t('commandsReceived.average_time') }}<template v-if="fig.max !== null"> {{ t('commandsReceived.max_n', { n: fig.max }) }}</template></span></div>
				</div>
				<div class="sv-tools">
					<span class="sv-seg" role="group" :aria-label="t('links.when_label')">
						<button v-for="s in SPANS" :key="s.id" type="button" :aria-pressed="span === s.id ? 'true' : 'false'" :data-span="s.id" @click="pickSpan(s.id)">{{ t('commandsReceived.' + s.key) }}</button>
					</span>
					<!-- the range picker of the family: quick ranges, "the last N" and from-to; it always shows the dates in use -->
					<span class="sv-picker" data-part="dates"><range-picker :value="picker" @input="applyPicker" /></span>
					<span class="sv-seg" role="group" :aria-label="t('links.class_label')">
						<button v-for="c in CLASSES" :key="c.id" type="button" :aria-pressed="q.rw === c.id ? 'true' : 'false'" :data-class="c.id" @click="pickClass(c.id)">{{ t(c.id === 0 ? 'common.all' : c.id === 1 ? 'common.change_something' : 'commandsReceived.readings') }}</button>
					</span>
				</div>
				<details class="sv-fold" data-part="filters">
					<summary><span class="mdi mdi-chevron-right sv-ico sv-ico-s sv-chev" aria-hidden="true" /><span class="sv-fold-name">{{ t('links.more_filters') }}</span><span class="sv-fold-sum">{{ filtersOn ? t('links.filters_on', { n: filtersOn }) : '' }}</span></summary>
					<div class="sv-fold-body">
						<div class="sv-tools">
							<sv-select v-for="f in FILTERS" :key="f" v-model="draft[f]" :options="filterOptions(f)" :aria-label="filterName(f)" />
							<label class="sv-field"><span class="mdi mdi-magnify sv-ico sv-ico-s" aria-hidden="true" /><input v-model="draft.query" type="search" :placeholder="t('common.find')" :aria-label="t('common.find')" @keyup.enter="applyFilters"></label>
							<label class="sv-check"><input v-model="draft.errors" type="checkbox"><span>{{ t('commandsReceived.errors_only') }}</span></label>
						</div>
						<div class="sv-row-ctl"><button type="button" class="wf-btn sv-btn wf-main" data-act="apply" @click="applyFilters">{{ t('links.apply') }}</button><button type="button" class="wf-btn sv-btn sv-text" data-act="clear" @click="clearFilters">{{ t('links.clear') }}</button></div>
					</div>
				</details>
				<p v-if="!rows.length" class="sv-quiet" role="status" data-part="none">{{ t(q.rw === 1 ? 'commandsReceived.no_command_that_changes_something_in' : 'commandsReceived.no_commands_in_this_range') }}
					<button v-if="q.rw === 1 && fig && fig.readings" type="button" class="wf-btn sv-btn sv-text" data-act="see-reads" @click="pickClass(2)">{{ tc('commandsReceived.there_are_n_reads', fig.readings, { n: fig.readings }) }} {{ t('commandsReceived.show_them') }}</button></p>
				<div v-else class="sv-scroll"><table class="sv-table">
					<caption class="sv-vh">{{ t('common.received_commands') }}</caption>
					<thead><tr><th scope="col">{{ t('links.col_when') }}</th><th scope="col">{{ t('links.col_who') }}</th><th scope="col">{{ t('links.col_op') }}</th><th scope="col">{{ t('commandsReceived.result') }}</th><th scope="col" class="sv-num">{{ t('links.col_time') }}</th></tr></thead>
					<tbody>
						<template v-for="r in rows">
							<tr :key="r.id" :data-command="r.id" :data-open="open === r.id ? '' : null">
								<td :data-label="t('links.col_when')"><button type="button" class="wf-btn sv-btn sv-text" data-act="open" :aria-expanded="open === r.id ? 'true' : 'false'" @click="open = open === r.id ? null : r.id">{{ hour(r.ts) }}</button></td>
								<td :data-label="t('links.col_who')">{{ who(r) }}</td>
								<td :data-label="t('links.col_op')"><b>{{ r.name }}</b> <code class="sv-code">{{ r.code }}</code></td>
								<td :data-label="t('commandsReceived.result')"><span class="sv-word" :data-level="r.ok ? 'ok' : 'warn'"><span class="mdi sv-ico sv-ico-s" :class="r.ok ? 'mdi-check-circle-outline' : 'mdi-alert-outline'" aria-hidden="true" />{{ t(r.ok ? 'commandsReceived.answered_ok' : 'commandsReceived.failed') }}</span><span v-if="r.origin && r.origin.result === 'blocked'" class="sv-tag">{{ t('commandsReceived.blocked') }}</span></td>
								<td class="sv-num" :data-label="t('links.col_time')">{{ r.ms === null || r.ms === undefined ? '' : r.ms + ' ms' }}</td>
							</tr>
							<tr v-if="open === r.id" :key="r.id + 'd'" class="sv-detail" data-part="detail"><td colspan="5">
								<p class="sv-quiet">{{ t('commandsReceived.date') }} {{ r.ts.replace('T', ' ') }}<template v-if="r.via"> · {{ t('commandsReceived.came_through') }} {{ r.via }}</template> · {{ t(r.reading ? 'commandsReceived.read_only' : 'commandsReceived.changes_something') }}</p>
								<dl v-if="fields(r).length" class="sv-facts"><template v-for="f in fields(r)"><dt :key="f.field + 'k'">{{ t('commandsReceived.' + f.key) }}</dt><dd :key="f.field + 'v'">{{ fieldValue(f) }}</dd></template></dl>
								<p v-else class="sv-quiet">{{ t('commandsReceived.no_origin_data_command_from_before') }}</p>
								<div class="sv-row-ctl"><span class="sv-quiet">{{ t('commandsReceived.code') }}</span><sv-copy-button kind="code" :done="copied === r.id + 'c'" @copy="copy(r.code, r.id + 'c')" /></div>
								<pre class="sv-diff">{{ r.code }}</pre>
								<div class="sv-row-ctl"><span class="sv-quiet">{{ t('commandsReceived.response') }}</span><sv-copy-button v-if="r.response" kind="response" :done="copied === r.id + 'r'" @copy="copy(r.response, r.id + 'r')" /></div>
								<pre class="sv-diff">{{ nice(r.response) }}</pre>
							</td></tr>
						</template>
					</tbody>
				</table></div>
				<div class="sv-row-ctl">
					<span class="sv-quiet" data-part="count">{{ total ? t('links.shown_of', { shown: rows.length, total: total }) : '' }}</span>
					<button v-if="rows.length < total" type="button" class="wf-btn sv-btn" data-act="more" :disabled="loading" @click="load(rows.length)">{{ t('kit.load_more') }}</button>
				</div>
				<ul class="sv-rows">
					<sv-action-row icon="mdi-delete-outline" :name="t('commandsReceived.delete_this_range')" :desc="t('commandsReceived.kept_30_days_reads_1_day')" :action="deleteCommands" :permission="perm('history.delete')" :stale="stale" :label="t('commandsReceived.delete_this_range')" danger @run="deleteCommands.run({ from: range.from, to: range.to })" @retry="deleteCommands.run({ from: range.from, to: range.to })" />
				</ul>
				<lock-reason class="sv-lock" :lock="lockOf(['history.delete'])" />
			</wf-zone>
		</section>
		<wf-confirm :confirm="deleteCommands.confirm" :title="t('links.delete_title')" :text="t('links.delete_text')" :object="{ name: range.from + ' → ' + range.to, context: tc('links.delete_count', total || 0, { n: total || 0 }) }" :verb="t('commandsReceived.delete_this_range')" danger
			@accept="deleteCommands.accept()" @cancel="deleteCommands.cancel()" />
	</div>
</template>

<script>
import { call } from '../../core/api/call.js'
import { can, session, want } from '../../core/store/session.js'
import { lastCommandStamp } from '../../core/live/published.js'
import { timeNow } from '../../core/clock.js'
import { locale } from '../../core/dwc.js'
import { deleteCommands } from '../../core/actions/links.js'
import { rowsMixin } from '../../core/rows-mixin.js'
import { copyText } from '../../copy.js'
import SvActionRow from '../../ui/SvActionRow.vue'
import WfConfirm from '../../WfConfirm.vue'
import RangePicker from '../../RangePicker.vue'
import { absolute, resolve } from '../../range-picker.js'
import LockReason from '../../LockReason.vue'
import SvCopyButton from '../../ui/SvCopyButton.vue'
import WfZone from '../../WfZone.vue'
import SvSelect from '../../ui/SvSelect.vue'
import { CLASSES, FILTERS, PAGE, SPANS, activeFilters, argsOf, emptyQuestion, fieldsOf, figuresOf, hourOf, niceResponse, originKey, rangeFrom, rangeOf, RESULT_KEYS } from './commands-view.js'

const OP = 'history.list'
const FILTER_KEY = { name: 'command', via: 'came_through', channel: 'channel', kind: 'origin', plugin: 'plugin_or_page', result: 'result' }
const SUMMARY_LIST = { via: 'ways', channel: 'channels', kind: 'kinds', plugin: 'plugins', result: 'results' }

export default {
	name: 'CommandsTab',
	components: { RangePicker, SvCopyButton, SvActionRow, WfConfirm, LockReason, SvSelect, WfZone },
	mixins: [rowsMixin],
	props: { active: { type: Boolean, default: false } },
	data() {
		return { session, seenGen: session.generation, SPANS, CLASSES, FILTERS, deleteCommands, span: 'today', range: rangeOf('today', Date.now()), picker: absolute(rangeOf('today', Date.now()).from + 'T00:00', rangeOf('today', Date.now()).to + 'T23:59'), q: emptyQuestion(), draft: emptyQuestion(), rows: [], total: 0, names: [], summary: null, loading: false, loaded: false, error: null, open: null, copied: '', live: true, mine: 0 }
	},
	computed: {
		lang() {
			return String(locale() || 'es').toLowerCase().indexOf('en') === 0 ? 'en' : 'es'
		},
		ready() {
			return can(OP).state === 'ok'
		},
		lock() {
			const c = can(OP)
			return c.state === 'session' || c.state === 'role' ? c : null
		},
		zone() {
			if (this.lock) return 'locked'
			if (this.error && !this.rows.length) return 'error'
			return this.loaded ? 'ready' : 'loading'
		},
		fig() {
			return figuresOf(this.summary)
		},
		filtersOn() {
			return activeFilters(this.q)
		},
		stamp() {
			return lastCommandStamp()
		}
	},
	watch: {
		active: { immediate: true, handler(on) { if (on) { want([OP, 'history.delete']); this.load(0) } } },
		// the person changed: what was read belonged to the one who left
		'session.generation'(g) { if (g === this.seenGen) return; this.seenGen = g; this.rows = []; this.total = 0; this.summary = null; this.loaded = false; if (this.active) this.load(0) },
		// the session was still being checked when the tab opened: read when it says yes
		ready(on) { if (on && this.active && !this.loaded) this.load(0) },
		// a new command arrived: read again from the top, unless the person is reading a detail or paused it
		stamp() {
			if (this.live && this.active && this.open === null && !this.loading && this.range.to >= rangeOf('today', timeNow()).to) this.load(0)
		},
		'deleteCommands.state'(now) { if (now === 'done') { this.deleteCommands.reset(); this.load(0) } }
	},
	methods: {
		async load(offset) {
			if (this.lock || !this.ready) return    // nothing is asked until the session and the role say so (no 401 / 403 by mounting)
			const mine = ++this.mine
			this.loading = true
			try {
				const r = await call(OP, argsOf(this.q, this.range, offset, PAGE), { quiet: true })
				if (mine !== this.mine) return
				const d = r.data || {}
				this.rows = offset ? this.rows.concat(d.rows || []) : d.rows || []
				this.total = d.total || 0
				this.names = d.names || []
				this.summary = d.summary || null
				this.error = null
				this.loaded = true
			} catch (e) {
				if (mine !== this.mine) return
				this.error = e
				this.loaded = true
			}
			if (mine === this.mine) this.loading = false
		},
		pickSpan(id) {
			this.span = id
			this.range = rangeOf(id, timeNow())
			this.picker = absolute(this.range.from + 'T00:00', this.range.to + 'T23:59')
			this.load(0)
		},
		// the range picker of the family gave a range (relative: the last N; absolute: from and to): the search asks for DAYS
		applyPicker(value) {
			const r = resolve(value, new Date())
			if (!r) return
			const day = d => d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0')
			this.applyRange({ from: day(r.from), to: day(r.to) }, value)
		},
		applyRange(r, value) {
			const ok = rangeFrom(r.from, r.to)
			if (!ok) return
			this.span = 'other'
			this.range = ok
			this.picker = value || absolute(ok.from + 'T00:00', ok.to + 'T23:59')
			this.load(0)
		},
		pickClass(id) {
			this.q = Object.assign({}, this.q, { rw: id })
			this.draft.rw = id
			this.load(0)
		},
		applyFilters() {
			this.q = Object.assign({}, this.draft, { rw: this.q.rw })
			this.load(0)
		},
		clearFilters() {
			this.draft = Object.assign(emptyQuestion(), { rw: this.q.rw })
			this.applyFilters()
		},
		filterName(f) {
			return this.t('commandsReceived.' + FILTER_KEY[f])
		},
		// what each filter offers: what the range holds (the service lists it), and the one in use
		// the list of a filter as SvSelect wants it: its own name first (= no filter), then what the range holds
		filterOptions(f) {
			return [{ value: '', label: this.filterName(f) }].concat(this.options(f).map(o => ({ value: o.value, label: o.text })))
		},
		options(f) {
			let list = f === 'name' ? this.names : (this.summary && this.summary[SUMMARY_LIST[f]]) || []
			list = list.slice()
			if (this.q[f] && list.indexOf(this.q[f]) < 0) list.unshift(this.q[f])
			return list.map(v => ({ value: v, text: f === 'kind' ? this.originText(v) : f === 'result' ? this.resultText(v) : v }))
		},
		originText(kind) {
			const k = originKey(kind)
			return k ? this.t('commandsReceived.' + k) : kind
		},
		resultText(v) {
			return RESULT_KEYS[v] ? this.t('commandsReceived.' + RESULT_KEYS[v]) : v
		},
		hour: hourOf,
		nice: niceResponse,
		who(r) {
			const o = r.origin
			if (o && o.kind) return this.originText(o.kind) + (o.plugin ? ': ' + o.plugin : '')
			return r.via || '–'
		},
		fields(r) {
			return fieldsOf(r.origin)
		},
		fieldValue(f) {
			if (f.field === 'kind') return this.originText(f.value)
			if (f.field === 'result') return this.resultText(f.value)
			if (typeof f.value === 'boolean') return this.t('commandsReceived.' + (f.value ? 'yes' : 'no'))
			return String(f.value)
		},
		async copy(text, id) {
			if (!(await copyText(text))) return
			this.copied = id
			setTimeout(() => { if (this.copied === id) this.copied = '' }, 1500)
		}
	}
}
</script>
