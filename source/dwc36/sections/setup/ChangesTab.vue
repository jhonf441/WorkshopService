<template>
	<!-- Setup > Changes: what the workshop wants to change in the files of this SD card, as a plan with a box for each change. Nothing is applied by
	     itself: the person ticks, opens the differences of each safety file, confirms, and an administrator applies with a level 3 dialog (and with
	     the board idle: it is said BEFORE). Under it, the result file by file, and the history of what was applied. Prop: active. -->
	<div class="sv-setup-changes">
		<section class="sv-card" aria-labelledby="sv-sc-title" data-card="plan">
			<div class="sv-card-head">
				<h2 id="sv-sc-title"><span class="mdi mdi-file-compare sv-ico" aria-hidden="true" />{{ t('setup.changes_title') }}</h2>
				<span v-if="plan.data" class="sv-chip" :data-level="items.length ? 'warn' : null">{{ items.length ? tc('startup_wizard.sum_pending', items.length, { n: items.length }) : t('startup_wizard.sum_none') }}</span>
			</div>
			<p class="sv-lead">{{ t('startup_wizard.intro') }}</p>
			<state-legend kind="levels" />
			<sv-zone :status="status" :error="plan.error" :lock="plan.lock" :updated="updated" refreshable :empty-title="t('startup_wizard.none')" @retry="plan.reload()" @refresh="plan.reload()" @sign-in="signIn">
				<div v-if="plan.data && plan.data.sd_empty" class="sv-note" data-level="info" role="note"><span class="mdi mdi-information-outline sv-ico" aria-hidden="true" /><span>{{ t('startup_wizard.new_install') }}</span></div>
				<div v-if="blockers.length" class="sv-note" data-level="warn" role="note" data-part="busy"><span class="mdi mdi-alert-outline sv-ico" aria-hidden="true" /><span>{{ t('startup_wizard.busy') }} <small v-for="b in blockers" :key="b.code + b.detail">{{ b.reason }} </small></span></div>
				<div v-if="items.length" class="sv-tools">
					<button type="button" class="sv-btn" data-act="mark-all" :disabled="!tools.canAll" @click="markAll">{{ t('startup_wizard.mark_all') }}</button>
					<button type="button" class="sv-btn sv-text" data-act="clear" :disabled="!tools.canClear" @click="clearMarks">{{ t('startup_wizard.clear_all') }}</button>
				</div>
				<details v-for="g in groups" :key="g.id" class="sv-fold" open :data-group="g.id">
					<summary>
						<span class="mdi mdi-chevron-right sv-ico sv-chev" aria-hidden="true" />
						<span class="sv-fold-name">{{ t('startup_wizard.group_' + g.id, { n: g.items.length }) }}</span>
					</summary>
					<div class="sv-fold-body">
						<p class="sv-quiet">{{ t('startup_wizard.group_' + g.id + '_help') }}</p>
						<ul class="sv-rows">
							<sv-action-row v-for="it in g.items" :key="it.id" icon="mdi-file-edit-outline" :name="it.path" :desc="reasonText(it)" :data-item="it.id">
								<template #control>
									<label class="sv-check"><input type="checkbox" :data-item="it.id" :checked="!!sel.ticked[it.id]" :disabled="!it.selectable || !mayApply || stale" :aria-label="t('startup_wizard.accept') + ': ' + it.path" @change="tick(it.id, $event.target.checked)"><span>{{ t('startup_wizard.kind_' + it.kind) }}</span></label>
									<button type="button" class="sv-btn sv-text" data-act="diff" @click="toggleDiff(it.id)">{{ t(open[it.id] ? 'startup_wizard.hide_diff' : 'startup_wizard.show_diff') }}</button>
								</template>
								<p v-if="!it.selectable" class="sv-field-error" role="status"><span class="mdi mdi-alert-outline sv-ico sv-ico-s" aria-hidden="true" />{{ blockedText(it) }}</p>
								<p v-if="it.safety" class="sv-row-desc" data-part="safety"><span class="sv-tag">{{ t('startup_wizard.safety_chip') }}</span> {{ t('startup_wizard.safety_' + it.safety) }}</p>
								<template v-if="it.safety && sel.ticked[it.id]">
									<button v-if="needsDiff(it)" type="button" class="sv-btn" data-act="open-diff" @click="openDiff(it.id)">{{ t('startup_wizard.open_diff_btn') }}</button>
									<label v-else class="sv-check"><input type="checkbox" :checked="!!sel.safe[it.id]" data-act="safe" @change="safe(it.id, $event.target.checked)"><span>{{ t('startup_wizard.safety_confirm', { path: it.path, why: t('startup_wizard.safety_' + it.safety) }) }}</span></label>
									<p v-if="needsDiff(it)" class="sv-quiet">{{ t('startup_wizard.safety_open_diff') }}</p>
								</template>
								<template v-if="open[it.id]">
									<p class="sv-quiet">{{ diffText(it) }}</p>
									<pre class="sv-diff"><span v-for="(l, i) in lines(it)" :key="i" :class="'d-' + l.cls">{{ l.text }}
</span></pre>
								</template>
							</sv-action-row>
						</ul>
					</div>
				</details>
				<details v-if="info.length" class="sv-fold" data-part="info">
					<summary><span class="mdi mdi-chevron-right sv-ico sv-chev" aria-hidden="true" /><span class="sv-fold-name">{{ t('startup_wizard.info_title', { n: info.length }) }}</span></summary>
					<div class="sv-fold-body"><p class="sv-quiet">{{ t('startup_wizard.info_help') }}</p><ul class="sv-rows"><li v-for="i in info" :key="i.id" class="sv-row"><div class="sv-row-main"><div><div class="sv-row-name">{{ i.path }}</div><div class="sv-row-desc">{{ i.reason }}</div></div></div></li></ul></div>
				</details>
				<div v-if="items.length" class="sv-apply" data-part="apply">
					<label v-if="risky.length" class="sv-check"><input type="checkbox" :checked="sel.machineOff" data-act="machine-off" @change="off($event.target.checked)"><span>{{ t('startup_wizard.machine_off') }}</span></label>
					<p v-if="block && picked.length" class="sv-quiet" role="status" data-part="block">{{ t('startup_wizard.block_' + block) }}</p>
					<p v-else-if="!picked.length" class="sv-quiet">{{ t('startup_wizard.block_none') }}</p>
					<button type="button" class="sv-btn sv-main" data-act="apply" :disabled="!mayApply || stale || !!block || applyChanges.busy()" @click="apply">{{ tc('startup_wizard.apply', picked.length, { n: picked.length }) }}</button>
				</div>
				<sv-reason :lock="lockOf(['startup.apply'])" @sign-in="signIn" />
			</sv-zone>
			<div v-if="applyChanges.state === 'error' && applyChanges.error && applyChanges.error.kind !== 'session' && applyChanges.error.kind !== 'role'" class="sv-row-out" data-kind="error" role="alert" data-part="apply-error"><span class="mdi mdi-close-circle-outline sv-ico sv-ico-s" aria-hidden="true" />{{ applyChanges.error.message }}</div>
		</section>

		<section v-if="result" class="sv-card" aria-labelledby="sv-sc-result" data-card="result">
			<div class="sv-card-head"><h2 id="sv-sc-result"><span class="mdi mdi-clipboard-check-outline sv-ico" aria-hidden="true" />{{ t('startup_wizard.result_title') }}</h2><span class="sv-quiet">{{ resultSummary }}</span></div>
			<ul class="sv-rows">
				<li v-for="r in resultRows" :key="r.id" class="sv-row" :data-result="r.ok ? 'ok' : 'failed'">
					<div class="sv-row-main"><span class="mdi sv-ico" :class="r.ok ? 'mdi-check-circle-outline' : 'mdi-close-circle-outline'" aria-hidden="true" />
						<div><div class="sv-row-name">{{ r.path }}</div><div class="sv-row-desc">{{ r.ok ? t('startup_wizard.done_' + r.code) + (r.backup ? ' · ' + t('startup_wizard.backup_in', { path: r.backup }) : '') : t('startup_wizard.err_' + errCode(r.code)) }}</div></div></div>
				</li>
			</ul>
		</section>

		<section class="sv-card" aria-labelledby="sv-sc-hist" data-card="history">
			<div class="sv-card-head"><h2 id="sv-sc-hist"><span class="mdi mdi-history sv-ico" aria-hidden="true" />{{ t('configPackage.history_title') }}</h2></div>
			<sv-zone :status="runs.status" :error="runs.error" :lock="runs.lock" :empty-title="t('configPackage.history_empty')" @retry="runs.reload()" @sign-in="signIn">
				<ul class="sv-rows">
					<li v-for="r in runs.rows" :key="r.run_id" class="sv-row" :data-run="r.run_id">
						<div class="sv-row-main"><span class="mdi mdi-history sv-ico" aria-hidden="true" />
							<div>
								<div class="sv-row-name">{{ r.ts }} · {{ triggerText(r) }}<span v-if="r.dry_run" class="sv-tag">{{ t('configPackage.run_dry') }}</span></div>
								<div class="sv-row-desc">{{ r.actor || '–' }} ({{ r.role ? t('api.role_' + r.role) : '–' }})</div>
								<div class="sv-row-desc" data-part="counts"><span class="sv-state" data-level="ok">{{ t('configPackage.run_applied', { n: counts(r).applied }) }}</span> <span class="sv-state" :data-level="counts(r).skipped ? 'warn' : 'rest'">{{ t('configPackage.run_skipped', { n: counts(r).skipped }) }}</span><span v-if="counts(r).unchanged" class="sv-state" data-level="rest">{{ t('configPackage.run_unchanged', { n: counts(r).unchanged }) }}</span></div>
								<p v-if="counts(r).skipped" class="sv-hint">{{ t('configPackage.run_skipped_help') }}</p>
							</div>
						</div>
						<div class="sv-row-ctl"><button type="button" class="sv-btn sv-text" data-act="run" @click="toggleRun(r.run_id)">{{ t(details[r.run_id] ? 'configPackage.run_hide' : 'configPackage.run_show') }}</button></div>
						<div v-if="details[r.run_id]" class="sv-row-body" data-part="body">
							<ul class="sv-effects" data-part="run-detail"><li v-for="a in split(r).done" :key="a.id"><code class="sv-code">{{ a.path }}</code> - {{ actionText(a.action) }}<template v-if="a.reason"> ({{ a.reason }})</template></li></ul>
							<details v-if="split(r).skipped.length" class="sv-fold" data-part="skipped">
								<summary><span class="mdi mdi-chevron-right sv-ico sv-ico-s sv-chev" aria-hidden="true" /><span class="sv-fold-name">{{ t('configPackage.run_skipped_fold', { n: split(r).skipped.length }) }}</span><span class="sv-fold-sum">{{ split(r).reasons.map(x => actionText(x.action) + ': ' + x.n).join(' · ') }}</span></summary>
								<div class="sv-fold-body"><ul class="sv-effects"><li v-for="a in split(r).skipped" :key="a.id"><code class="sv-code">{{ a.path }}</code></li></ul></div>
							</details>
						</div>
					</li>
				</ul>
				<p v-if="runs.total > runs.rows.length" class="sv-quiet">{{ t('configPackage.history_more', { n: runs.rows.length, total: runs.total }) }}
					<button v-if="runs.hasMore" type="button" class="sv-btn sv-text" data-act="more" :disabled="runs.more" @click="runs.loadMore()">{{ t('kit.load_more') }}</button></p>
			</sv-zone>
		</section>

		<sv-confirm-dialog :confirm="applyChanges.confirm" :title="t('setup.apply_title')" :text="t('setup.apply_text')" :object="{ name: tc('startup_wizard.apply', picked.length, { n: picked.length }), context: t('setup.apply_context') }" :effects="effects"
			:verb="tc('startup_wizard.apply', picked.length, { n: picked.length })" @accept="applyChanges.accept()" @cancel="applyChanges.cancel()" />
	</div>
</template>

<script>
import { call } from '../../core/api/call.js'
import { locale } from '../../core/dwc.js'
import { startupPlan, startupRuns } from '../../core/resources.js'
import { want } from '../../core/store/session.js'
import { applyChanges } from '../../core/actions/setup.js'
import { rowsMixin } from '../../core/rows-mixin.js'
import { time } from '../../core/format/dates.js'
import { runCounts, splitActions } from '../../package-view.js'
import { applyBlock, buildPayload, byGroup, chosen, chosenSafety, clearAll, diffLines, diffStats, emptySelection, errCode, needsDiffOpen, openableIds, resultRows, runAction, selectAll, setMachineOff, setSafe, setSeen, setTicked, toolbarState } from '../../package-wizard.js'
import StateLegend from './StateLegend.vue'
import SvActionRow from '../../ui/SvActionRow.vue'
import SvConfirmDialog from '../../ui/SvConfirmDialog.vue'
import SvReason from '../../ui/SvReason.vue'
import SvZone from '../../ui/SvZone.vue'
import { BLOCKED, TRIGGERS, WHY } from './view.js'

export default {
	name: 'ChangesTab',
	components: { StateLegend, SvActionRow, SvConfirmDialog, SvReason, SvZone },
	mixins: [rowsMixin],
	props: { active: { type: Boolean, default: false } },
	data() {
		return { plan: startupPlan, runs: startupRuns, applyChanges, sel: emptySelection(), open: {}, result: null, sent: [], details: {} }
	},
	computed: {
		items() {
			return (this.plan.data && this.plan.data.items) || []
		},
		info() {
			return (this.plan.data && this.plan.data.info) || []
		},
		blockers() {
			return (this.plan.data && this.plan.data.blockers) || []
		},
		groups() {
			return byGroup(this.items)
		},
		tools() {
			return toolbarState(this.items, this.sel)
		},
		picked() {
			return chosen(this.items, this.sel)
		},
		risky() {
			return chosenSafety(this.items, this.sel)
		},
		block() {
			return applyBlock(this.items, this.sel, this.blockers)
		},
		effects() {
			return this.picked.map(i => i.path)
		},
		status() {
			return this.plan.status === 'ready' && !this.items.length && !this.info.length ? 'empty' : this.plan.status
		},
		updated() {
			return this.plan.loadedAt ? time(this.plan.loadedAt, locale()).slice(0, 5) : ''
		},
		mayApply() {
			return this.perm('startup.apply').state === 'ok'
		},
		resultRows() {
			return this.result ? resultRows(this.sent, this.result) : []
		},
		resultSummary() {
			const ok = this.resultRows.filter(r => r.ok).length
			return this.t('startup_wizard.result_summary', { ok: this.tc('startup_wizard.result_ok', ok, { n: ok }), bad: this.tc('startup_wizard.result_bad', this.resultRows.length - ok, { n: this.resultRows.length - ok }) })
		}
	},
	watch: {
		active: { immediate: true, handler(on) { if (on) this.show(); else this.hide() } },
		// a new plan: the ticks belonged to the old one
		'plan.loadedAt'() { this.sel = emptySelection(); this.open = {} },
		'applyChanges.state'(now) {
			if (now === 'done') { this.result = this.applyChanges.data; this.sel = Object.assign({}, this.sel, { safe: {}, machineOff: false }) }
		}
	},
	methods: {
		errCode,
		show() {
			want(['startup.plan', 'startup.apply', 'startup.runs.list'])
			this.plan.show()
			this.runs.show()
		},
		hide() {
			this.plan.hide()
			this.runs.hide()
		},
		reasonText(it) {
			return WHY.indexOf(it.reason) >= 0 ? this.t('startup_wizard.why_' + it.reason) : it.reason
		},
		blockedText(it) {
			return BLOCKED.indexOf(it.blocked) >= 0 ? this.t('startup_wizard.blocked_' + it.blocked) : it.reason
		},
		lines(it) {
			return diffLines(it.diff)
		},
		diffText(it) {
			const s = diffStats(it.diff)
			return this.t('startup_wizard.diff_count', { add: this.tc('startup_wizard.diff_added', s.add, { n: s.add }), del: this.tc('startup_wizard.diff_removed', s.del, { n: s.del }) })
		},
		toggleDiff(id) {
			this.$set(this.open, id, !this.open[id])
			if (this.open[id]) this.sel = setSeen(this.sel, id)
		},
		openDiff(id) {
			this.$set(this.open, id, true)
			this.sel = setSeen(this.sel, id)
		},
		needsDiff(it) {
			return needsDiffOpen(this.sel, it)
		},
		markAll() {
			openableIds(this.items).forEach(id => this.$set(this.open, id, true))
			this.sel = selectAll(this.sel, this.items)
		},
		clearMarks() {
			this.sel = clearAll(this.sel)
		},
		tick(id, v) {
			this.sel = setTicked(this.sel, this.items, id, !!v)
		},
		safe(id, v) {
			this.sel = setSafe(this.sel, id, !!v)
		},
		off(v) {
			this.sel = setMachineOff(this.sel, !!v)
		},
		apply() {
			if (!this.mayApply || this.block) return
			this.sent = this.items.slice()
			this.result = null
			this.applyChanges.run(buildPayload(this.items, this.sel))
		},
		triggerText(r) {
			return TRIGGERS.indexOf(r.trigger) >= 0 ? this.t('configPackage.trigger_' + r.trigger) : r.trigger
		},
		actionText(action) {
			const r = runAction(action)
			const text = r.key ? this.t('startup_wizard.run_action_' + r.key) : r.base
			return r.would ? this.t('startup_wizard.run_would', { action: text }) : text
		},
		counts(r) {
			return runCounts(r.summary)
		},
		split(r) {
			return splitActions((this.details[r.run_id] || {}).actions)
		},
		async toggleRun(id) {
			if (this.details[id]) { this.$delete(this.details, id); return }
			try {
				const r = await call('startup.runs.get', { run_id: id }, { quiet: true })
				this.$set(this.details, id, r.data || { actions: [] })
			} catch (e) {
				this.$set(this.details, id, { actions: [{ id: 'err', path: '', action: 'failed', reason: e.message }] })
			}
		}
	}
}
</script>
