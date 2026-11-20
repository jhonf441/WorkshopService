<template>
	<!-- Diagnostics > Processes: how many run well, the ones that need a look first (open), the healthy ones folded; and, under them,
	     the one thing that affects them all: restarting the whole service.
	     Props: active (this tab is in view), anchor (svc-proc-<id> opens and marks that row; sv-service goes to the restart card). -->
	<div class="sv-health-proc">
		<section class="sv-card" aria-labelledby="sv-hp-title">
			<div class="sv-card-head">
				<h2 id="sv-hp-title"><span class="mdi mdi-cogs sv-ico" aria-hidden="true" />{{ t('health.proc_title') }}</h2>
				<span v-if="ageText" class="sv-age" :data-old="old ? '' : null"><span class="mdi mdi-clock-outline sv-ico sv-ico-s" aria-hidden="true" />{{ ageText }}</span>
			</div>
			<p v-if="!hasData" class="sv-quiet" role="status">{{ t(running ? 'health.no_data' : 'health.stopped_note') }}</p>
			<template v-else>
				<div class="sv-stats" :class="{ 'sv-stale': stale }">
					<div class="sv-stat sv-stat-ico" data-stat="fine" data-tone="ok"><span class="mdi mdi-check-circle-outline sv-ico" aria-hidden="true" /><b>{{ n.fine }}</b><span>{{ t('health.stat_fine') }}</span></div>
					<div class="sv-stat sv-stat-ico" data-stat="notice" data-tone="warn" :data-level="n.notice ? 'warn' : null"><span class="mdi mdi-alert-outline sv-ico" aria-hidden="true" /><b>{{ n.notice }}</b><span>{{ t('health.stat_notice') }}</span></div>
					<div class="sv-stat sv-stat-ico" data-stat="stopped" data-tone="error" :data-level="n.stopped ? 'error' : null"><span class="mdi mdi-close-circle-outline sv-ico" aria-hidden="true" /><b>{{ n.stopped }}</b><span>{{ t('health.stat_stopped') }}</span></div>
					<div class="sv-stat sv-stat-ico" data-stat="resting" data-tone="rest"><span class="mdi mdi-sleep sv-ico" aria-hidden="true" /><b>{{ n.resting }}</b><span>{{ t('health.stat_resting') }}</span></div>
				</div>
				<div class="sv-tools">
					<span class="sv-seg" role="group" :aria-label="t('health.filter_label')">
						<button v-for="f in FILTERS" :key="f" type="button" :aria-pressed="shownFilter === f ? 'true' : 'false'" :data-filter="f" @click="filter = f">{{ t('health.filter_' + f) }}</button>
					</span>
					<label class="sv-field"><span class="mdi mdi-magnify sv-ico sv-ico-s" aria-hidden="true" /><input v-model="query" type="search" :placeholder="t('health.search')" :aria-label="t('health.search')"></label>
				</div>
				<p v-if="!groups.length" class="sv-quiet" role="status" data-part="none">{{ t(query ? 'health.none_found' : 'health.none_filter') }}
					<button v-if="query || shownFilter !== 'all'" type="button" class="sv-btn sv-text" @click="clearFilters">{{ t('health.show_all') }}</button></p>
				<details v-for="g in groups" :key="g.id" class="sv-fold" :open="groupOpen(g)" :data-open="groupOpen(g) ? '' : null" :data-group="g.id" @toggle="setGroup(g, $event.target.open)">
					<summary>
						<span class="mdi mdi-chevron-right sv-ico sv-chev" aria-hidden="true" />
						<span class="sv-fold-name">{{ t('plugins.WorkshopService.procDocs.ui_group_' + (g.id === 'separate' ? 'ext' : g.id)) }}</span>
						<span class="sv-fold-sum">{{ g.look ? tc('health.group_look', g.look, { total: g.total }) : tc('health.group_fine', g.total) }}</span>
						<span class="sv-minis" data-part="minis"><span v-for="m in mix(g)" :key="m.level" class="sv-mini" :data-level="m.level" :title="m.title"><i aria-hidden="true" />{{ m.n }}<span class="sv-vh">{{ m.title }}</span></span></span>
						<span class="sv-state" :data-level="WORD_LEVEL[g.word]">{{ t('health.gword_' + g.word) }}</span>
					</summary>
					<div class="sv-fold-body">
						<process-item v-for="i in g.items" :key="i.id" :item="i" :open="!!openItems[i.id]" :marked="marked === i.id" :stale="stale" :vision="i.id === 'vision' ? visionState : null"
							@toggle="on => setItem(i.id, on)" @sign-in="signIn" />
					</div>
				</details>
			</template>
		</section>

		<section id="sv-service" class="sv-card" aria-labelledby="sv-hs-title">
			<div class="sv-card-head"><h2 id="sv-hs-title"><span class="mdi mdi-restart-alert sv-ico" aria-hidden="true" />{{ t('health.service_title') }}</h2></div>
			<p v-if="watch.active" class="sv-quiet" role="status" data-part="restarting"><span class="sv-spin" aria-hidden="true" />{{ t('health.service_restarting') }}</p>
			<p v-else-if="watch.outcome === 'back'" class="sv-session-note" role="status" data-part="back"><span class="mdi mdi-check-circle-outline sv-ico sv-ico-s" aria-hidden="true" />{{ t('health.service_back') }}</p>
			<p v-else-if="watch.outcome === 'not-restarted'" class="sv-field-error" role="alert" data-part="not-restarted"><span class="mdi mdi-alert-outline sv-ico sv-ico-s" aria-hidden="true" />{{ t('health.service_not_restarted', { since: watch.since.slice(0, 16) }) }}</p>
			<ul class="sv-rows">
				<sv-action-row icon="mdi-restart" :name="t('health.service_restart_name')" :desc="t('health.service_restart_desc')" :action="serviceRestart" :permission="perm" :stale="stale || watch.active" danger
					:label="t('health.service_restart')" :error-text="reasons.length ? t('health.service_blocked') : ''" @run="restartService" @retry="restartService">
					<ul v-if="reasons.length" class="sv-effects" data-part="reasons"><li v-for="(r, k) in reasons" :key="k">{{ r }}</li></ul>
				</sv-action-row>
			</ul>
			<sv-reason :lock="perm" @sign-in="signIn" />
		</section>
		<sv-confirm-dialog :confirm="serviceRestart.confirm" :title="t('health.service_confirm_title')" :text="t('health.service_restart_desc')" :object="{ name: t('health.service_object'), context: serviceLine }"
			:verb="t('health.service_restart')" danger @accept="serviceRestart.accept()" @cancel="serviceRestart.cancel()" />
	</div>
</template>

<script>
import { t, tc, te } from '../../core/dwc.js'
import { clock, every } from '../../core/clock.js'
import { get, guardWatches, processes, receivedAt, serviceRunning, serviceVersion } from '../../core/live/published.js'
import { pageState } from '../../core/page-state.js'
import { can, signIn } from '../../core/store/session.js'
import { createResource } from '../../core/store/resource.js'
import { call } from '../../core/api/call.js'
import { serviceRestart } from '../../core/actions/processes.js'
import { clearRestartNote, restartWatch } from '../../core/actions/service-restart.js'
import { ageSeconds, durationText } from '../../core/format/duration.js'
import { serviceText } from '../../service-text.js'
import SvActionRow from '../../ui/SvActionRow.vue'
import SvConfirmDialog from '../../ui/SvConfirmDialog.vue'
import SvReason from '../../ui/SvReason.vue'
import ProcessItem from './ProcessItem.vue'
import { FILTERS, counts, defaultFilter, groupsOf, itemsOf, readableId } from './view.js'

const AGE_SHOWN_S = 45
const VISION_EVERY_S = 30
const WORD_LEVEL = { fine: 'ok', notice: 'warn', stopped: 'error', paused: 'rest' }
const DOCS = 'plugins.WorkshopService.procDocs.'

// the detail of Vision (its own server): asked only with a session, only while this tab is in view
const vision = createResource({
	key: 'vision-state', needs: 'vision.get', staleMs: VISION_EVERY_S * 1000,
	load: async () => (await call('vision.get', { path: '/state' }, { quiet: true })).data || null
})

export default {
	name: 'ProcessesTab',
	components: { ProcessItem, SvActionRow, SvConfirmDialog, SvReason },
	props: { active: { type: Boolean, default: false }, anchor: { type: String, default: '' } },
	data() {
		return { FILTERS, WORD_LEVEL, serviceRestart, watch: restartWatch, vision, filter: '', query: '', openGroups: {}, openItems: {}, marked: '' }
	},
	computed: {
		running() {
			return serviceRunning()
		},
		internal() {
			return get('servicesInternal') || null
		},
		hasData() {
			return !!this.internal
		},
		stale() {
			return !this.running || pageState.restarting
		},
		items() {
			const health = get('healthPi') || {}
			return itemsOf({ processes: processes(), modules: (this.internal && this.internal.modules) || {}, watches: guardWatches(), services: health.services, base: health.base })
		},
		n() {
			return counts(this.items)
		},
		// the filter the person chose; until they choose, "attention" when something needs a look
		shownFilter() {
			return this.filter || defaultFilter(this.items)
		},
		// the groups with something to look at go first (the order inside each kind is the fixed one)
		groups() {
			const all = groupsOf(this.items, this.shownFilter, this.query, this.textOf)
			return all.filter(g => g.look > 0).concat(all.filter(g => !(g.look > 0)))
		},
		ageS() {
			return ageSeconds(receivedAt('servicesInternal'), clock.now)
		},
		old() {
			return this.stale || (this.ageS !== null && this.ageS > AGE_SHOWN_S)
		},
		ageText() {
			if (this.ageS === null || (!this.old && this.ageS <= AGE_SHOWN_S)) return ''
			return t('home.fact_age', { t: durationText(this.ageS, (k, p) => t('kit.' + k, p)) })
		},
		visionState() {
			return { status: this.vision.status, data: this.vision.data, error: this.vision.error }
		},
		perm() {
			return can('service.restart')
		},
		// the reasons the service gave for not restarting now (409): a list, never a way to force it
		reasons() {
			const e = this.serviceRestart.state === 'error' && this.serviceRestart.error
			const list = e && e.extra && Array.isArray(e.extra.reasons) ? e.extra.reasons : []
			return list.map(r => (r && typeof r === 'object' ? String(r.message || '') : String(r || ''))).filter(Boolean)
		},
		serviceLine() {
			const v = serviceVersion()
			return v ? t('home.fact_version', { v }) : ''
		}
	},
	watch: {
		active: { immediate: true, handler(on) { this.live(on) } },
		anchor: { immediate: true, handler() { this.arrive() } }
	},
	beforeDestroy() {
		this.live(false)
	},
	methods: {
		t,
		tc,
		signIn,
		live(on) {
			if (this.offVision) this.offVision()
			this.offVision = null
			if (!on) return this.vision.hide()
			this.vision.show()
			this.offVision = every(VISION_EVERY_S, () => { if (this.vision.status !== 'locked') this.vision.reload() })
		},
		// what a person may type to find a row: its name, what it does, its id and the words of its group
		textOf(i) {
			const g = DOCS + 'ui_group_' + (i.group === 'separate' ? 'ext' : i.group)
			return [i.title ? serviceText(i.title) : readableId(i.id), i.description ? serviceText(i.description) : '', i.id, te(g) ? t(g) : '', i.kind === 'separate' ? t('health.sep_' + i.id) : ''].join(' ')
		},
		// the states of a group in numbers: [{ level, n, title }] for ok / warn / error / rest (the same four colours as everywhere)
		mix(g) {
			const level = i => (i.level >= 2 ? 'error' : i.level === 1 ? 'warn' : i.word === 'paused' || i.word === 'resting' || i.word === 'unchecked' ? 'rest' : 'ok')
			const names = { ok: 'health.stat_fine', warn: 'health.stat_notice', error: 'health.stat_stopped', rest: 'health.stat_resting' }
			const n = { ok: 0, warn: 0, error: 0, rest: 0 }
			g.items.forEach(i => { n[level(i)] += 1 })
			return ['ok', 'warn', 'error', 'rest'].filter(l => l === 'ok' || n[l] > 0).map(l => ({ level: l, n: n[l], title: t(names[l]) }))
		},
		groupOpen(g) {
			const mine = this.openGroups[g.id]
			return mine === undefined ? g.look > 0 || !!this.query : mine
		},
		setGroup(g, on) {
			if (on !== this.groupOpen(g)) this.$set(this.openGroups, g.id, on)
		},
		setItem(id, on) {
			if (!!this.openItems[id] !== on) this.$set(this.openItems, id, on)
		},
		clearFilters() {
			this.filter = 'all'
			this.query = ''
		},
		// the address points at one row: every filter off, its group and the row open, the row marked and brought into view once
		arrive() {
			const m = /^svc-proc-(.+)$/.exec(this.anchor || '')
			const id = m ? m[1] : ''
			const target = id ? this.items.find(i => i.id === id) : null
			if (target) {
				this.clearFilters()
				this.$set(this.openGroups, target.group, true)
				this.$set(this.openItems, id, true)
				this.marked = id
			}
			const el = target ? 'svc-proc-' + id : this.anchor === 'sv-service' ? 'sv-service' : ''
			if (el && typeof document !== 'undefined') this.$nextTick(() => { const node = document.getElementById(el); if (node && node.scrollIntoView) node.scrollIntoView({ block: 'start' }) })
		},
		restartService() {
			clearRestartNote()
			this.serviceRestart.run()
		}
	}
}
</script>
