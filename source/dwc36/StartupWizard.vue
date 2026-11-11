<template>
	<v-card :flat="embedded" :class="embedded ? 'svc-wiz' : 'mb-3 svc-wiz'">
		<!-- Start-up wizard ("Puesta en marcha"): what the workshop wants to change on THIS SD, shown to every person on every install before a file
		     is touched. Nothing is applied by itself: each change is ticked on purpose, the diff is one touch away, and the files that run on their
		     own (pause, cancel, homing, laser guard, start-up) ask for their own confirmation and a machine that is off. -->
		<v-card-title v-if="!embedded" class="d-flex align-center flex-wrap" style="gap:8px">
			<span><v-icon small class="mr-2 svx-ico">mdi-clipboard-check-outline</v-icon>{{ $t(T + 'title') }}</span>
			<v-chip v-if="plan" small outlined :color="plan.items.length ? 'warning' : 'success'">{{ plan.items.length ? $t(T + 'sum_pending', { n: plan.items.length }) : $t(T + 'sum_none') }}</v-chip>
			<v-spacer />
			<v-btn small text class="svc-wiz-touch" :loading="loading" :disabled="!seePlan" @click="read()"><v-icon small left>mdi-refresh</v-icon>{{ $t(T + 'refresh') }}</v-btn>
		</v-card-title>
		<v-card-text :class="{ 'pa-0': embedded }">
			<div class="text-body-2 mb-3 svc-wiz-intro">{{ $t(T + 'intro') }}</div>
			<session-notice v-if="needsLogin" kind="session" variant="section" />
			<lock-reason v-else-if="!seePlan" min="technician" />
			<v-alert v-else-if="error" dense text type="error" class="mb-2">{{ error }}</v-alert>

			<template v-if="plan">
				<v-alert v-if="plan.sd_empty" dense text type="info" class="mb-3">{{ $t(T + 'new_install') }}</v-alert>
				<v-alert v-if="plan.blockers.length" dense text type="warning" class="mb-3">
					{{ $t(T + 'busy') }}
					<div v-for="b in plan.blockers" :key="b.code + b.detail" class="text-caption">{{ b.reason }}</div>
				</v-alert>
				<div v-if="!plan.items.length && !plan.info.length" class="text-body-2 svc-wiz-none">{{ $t(T + 'none') }}</div>

				<div v-if="plan.items.length" class="d-flex flex-wrap align-center mt-2" style="gap:8px">
					<v-btn small outlined class="svc-wiz-touch svc-wiz-all" :disabled="!tools.canAll" @click="markAll"><v-icon small left>mdi-checkbox-multiple-marked-outline</v-icon>{{ $t(T + 'mark_all') }}</v-btn>
					<v-btn small text class="svc-wiz-touch svc-wiz-none-btn" :disabled="!tools.canClear" @click="clearMarks"><v-icon small left>mdi-checkbox-multiple-blank-outline</v-icon>{{ $t(T + 'clear_all') }}</v-btn>
					<span class="text-caption svc-wiz-help">{{ $t(T + 'mark_all_help') }}</span>
				</div>

				<section v-for="g in groups" :key="g.id" class="svc-wiz-group">
					<div class="svc-wiz-head"><span>{{ $t(T + 'group_' + g.id, { n: g.items.length }) }}</span></div>
					<div class="text-caption svc-wiz-help">{{ $t(T + 'group_' + g.id + '_help') }}</div>
					<div v-for="it in g.items" :key="it.id" class="svc-wiz-item" :class="{ 'is-ticked': sel.ticked[it.id], 'is-locked': !it.selectable }">
						<div class="svc-wiz-row">
							<v-checkbox :input-value="!!sel.ticked[it.id]" :disabled="!it.selectable" hide-details dense class="svc-wiz-check mt-0 pt-0"
								:label="$t(T + (sel.ticked[it.id] ? 'accepted' : 'accept'))" @change="v => tick(it.id, v)" />
							<div class="svc-wiz-main">
								<code class="svc-wiz-path">{{ it.path }}<template v-if="it.new_path"> &rarr; {{ it.new_path }}</template></code>
								<v-chip x-small label class="ml-1">{{ $t(T + 'kind_' + it.kind) }}</v-chip>
								<v-chip v-if="it.safety" x-small label color="warning" class="ml-1"><v-icon x-small left>mdi-shield-alert-outline</v-icon>{{ $t(T + 'safety_chip') }}</v-chip>
								<div class="svc-wiz-reason">{{ it.blocked ? $t(T + 'blocked_' + it.blocked) : reasonText(it) }}</div>
								<div v-if="!it.selectable" class="text-caption svc-wiz-why svc-wiz-locked">{{ $t(T + 'locked_hint') }}</div>
								<div v-for="w in it.warnings" :key="w" class="svc-wiz-reason warning--text">{{ w }}</div>
							</div>
							<v-btn small text class="svc-wiz-touch" @click="toggleDiff(it.id)"><v-icon small left>{{ open[it.id] ? 'mdi-chevron-up' : 'mdi-chevron-down' }}</v-icon>{{ open[it.id] ? $t(T + 'hide_diff') : $t(T + 'show_diff') }}</v-btn>
						</div>
						<div v-if="open[it.id]" class="svc-wiz-diffbox">
							<div class="text-caption mb-1">{{ $t(T + 'diff_count', stats(it)) }}</div>
							<pre class="svc-wiz-diff"><span v-for="(l, n) in lines(it)" :key="n" :class="'d-' + l.cls">{{ l.text }}
</span></pre>
						</div>
						<!-- a file that runs on its own: its own confirmation, apart from the tick -->
						<div v-if="it.safety && sel.ticked[it.id]" class="svc-wiz-safety">
							<v-checkbox :input-value="!!sel.safe[it.id]" :disabled="!sel.seen[it.id]" hide-details dense class="mt-0 pt-0" color="warning" @change="v => safe(it.id, v)"
								:label="$t(T + 'safety_confirm', { path: it.path, why: $t(T + 'safety_' + it.safety) })" />
							<div v-if="needsDiff(it)" class="d-flex align-center flex-wrap" style="gap:8px">
								<v-btn small outlined color="warning" class="svc-wiz-touch svc-wiz-opendiff" @click="openDiff(it.id)"><v-icon small left>mdi-chevron-down</v-icon>{{ $t(T + 'open_diff_btn') }}</v-btn>
								<span class="text-caption svc-wiz-why">{{ $t(T + 'safety_open_diff') }}</span>
							</div>
						</div>
					</div>
				</section>

				<section v-if="plan.info.length" class="svc-wiz-group">
					<div class="svc-wiz-head"><span>{{ $t(T + 'info_title', { n: plan.info.length }) }}</span></div>
					<div class="text-caption svc-wiz-help">{{ $t(T + 'info_help') }}</div>
					<div v-for="i in plan.info" :key="i.id" class="svc-wiz-item is-locked">
						<code class="svc-wiz-path">{{ i.path }}</code>
						<div class="svc-wiz-reason">{{ i.reason }}</div>
						<pre v-if="i.diff" class="svc-wiz-diff"><span v-for="(l, n) in infoLines(i)" :key="n" :class="'d-' + l.cls">{{ l.text }}
</span></pre>
					</div>
				</section>

				<div v-if="plan.items.length" class="svc-wiz-foot">
					<v-checkbox v-if="risky.length" :input-value="sel.machineOff" hide-details dense class="mt-0 pt-0 mb-2" color="warning" :label="$t(T + 'machine_off')" @change="v => off(v)" />
					<!-- locked-in-place style: the lock is inside the control; the reason shows only after the person touches it -->
					<div class="svc-wiz-apply" @click="touchLocked">
						<v-btn color="primary" class="svc-wiz-touch" :loading="applying" :disabled="!isAdmin || !!block" @click="apply">
							<v-icon v-if="!isAdmin" small left>mdi-lock-outline</v-icon>{{ $t(T + 'apply', { n: picked.length }) }}
						</v-btn>
						<span v-if="isAdmin && block" class="text-caption ml-2 svc-wiz-why">{{ $t(T + 'block_' + block) }}</span>
					</div>
					<lock-reason v-if="touched && !isAdmin" op="startup.apply" need="admin" class="mt-2" />
				</div>
			</template>

			<!-- what was done: the report of this run, with the detail of install_runs one touch away -->
			<div v-if="result" class="svc-wiz-result mt-3">
				<div class="svc-wiz-head"><span>{{ $t(T + 'result_title') }}</span></div>
				<div class="text-body-2 mb-1">{{ $t(T + 'result_summary', { ok: result.applied.length, bad: result.failed.length }) }}</div>
				<div v-for="r in rows" :key="r.id + r.ok" class="svc-wiz-reason" :class="r.ok ? 'success--text' : 'error--text'">
					<v-icon x-small :color="r.ok ? 'success' : 'error'">{{ r.ok ? 'mdi-check' : 'mdi-alert-circle-outline' }}</v-icon>
					<code>{{ r.path }}</code>
					<span v-if="r.ok"> - {{ $t(T + 'done_' + r.code) }}<template v-if="r.backup"> ({{ $t(T + 'backup_in', { path: r.backup }) }})</template></span>
					<span v-else> - {{ $t(T + 'err_' + code(r.code)) }}</span>
				</div>
				<div v-if="result.run_id" class="mt-2">
					<v-btn small outlined class="svc-wiz-touch" :loading="runLoading" @click="toggleRun">{{ run ? $t(T + 'run_hide') : $t(T + 'run_open', { id: result.run_id }) }}</v-btn>
				</div>
				<div v-if="run" class="svc-wiz-run mt-2">
					<div class="text-caption mb-1">{{ run.ts }} - {{ run.actor || '-' }} ({{ run.role || '-' }})</div>
					<div v-for="a in run.actions" :key="a.id" class="svc-wiz-reason"><code>{{ a.path }}</code> - {{ a.action }}<template v-if="a.reason"> ({{ a.reason }})</template><template v-if="a.error"> - {{ a.error }}</template></div>
				</div>
			</div>
		</v-card-text>
	</v-card>
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
import { byGroup, selectAll, clearAll, openableIds, toolbarState, needsDiffOpen, emptySelection, setTicked, setSafe, setSeen, setMachineOff, afterApply, chosen, chosenSafety, applyBlock, buildPayload, diffLines, diffStats, resultRows, errCode } from './startup-wizard.js'

export default {
	components: { SessionNotice, LockReason },
	mixins: [roleMixin],
	// embedded: drawn inside the one "Puesta en marcha" section (StartupSection.vue), which owns the title, the total and the refresh button
	props: { embedded: { type: Boolean, default: false } },
	// everything here was read or ticked by the person who left (ESTANDAR 3.3)
	sessionData: ['plan', 'sel', 'open', 'result', 'run', 'needsLogin', 'error', 'touched'],
	data() {
		return { T: 'plugins.WorkshopService.startup_wizard.', plan: null, sel: emptySelection(), open: {}, result: null, run: null, loading: false, applying: false, runLoading: false, needsLogin: false, error: '', touched: false };
	},
	computed: {
		seePlan() { return this.atLeast('technician'); },
		isAdmin() { return this.atLeast('admin'); },
		groups() { return this.plan ? byGroup(this.plan.items) : []; },
		reportState() { return { items: this.plan ? this.plan.items.length : 0, loaded: !!this.plan, needsLogin: this.needsLogin, loading: this.loading || this.applying }; },
		tools() { return this.plan ? toolbarState(this.plan.items, this.sel) : { canAll: false, canClear: false }; },
		picked() { return this.plan ? chosen(this.plan.items, this.sel) : []; },
		risky() { return this.plan ? chosenSafety(this.plan.items, this.sel) : []; },
		block() { return this.plan ? applyBlock(this.plan.items, this.sel, this.plan.blockers) : 'none'; },
		rows() { return this.result ? resultRows(this.plan ? this.plan.items : [], this.result) : []; }
	},
	methods: {
		code: errCode,
		lines(it) { return diffLines(it.diff); },
		infoLines(i) { return diffLines(i.diff); },
		stats(it) { return diffStats(it.diff); },
		reasonText(it) {
			const k = this.T + 'why_' + it.reason;
			return this.$te && this.$te(k) ? this.$t(k) : it.reason;
		},
		toggleDiff(id) {
			this.$set(this.open, id, !this.open[id]);
			if (this.open[id]) this.sel = setSeen(this.sel, id);
		},
		needsDiff(it) { return needsDiffOpen(this.sel, it); },
		openDiff(id) {
			if (!this.open[id]) this.$set(this.open, id, true);
			this.sel = setSeen(this.sel, id);
		},
		markAll() {
			for (const id of openableIds(this.plan.items)) this.$set(this.open, id, true);
			this.sel = selectAll(this.sel, this.plan.items);
		},
		clearMarks() { this.sel = clearAll(this.sel); },
		tick(id, v) { this.sel = setTicked(this.sel, this.plan.items, id, !!v); },
		safe(id, v) { this.sel = setSafe(this.sel, id, !!v); },
		off(v) { this.sel = setMachineOff(this.sel, !!v); },
		touchLocked() {
			if (this.isAdmin) return;
			this.touched = true;
			this.$nextTick(() => blinkLocked(this.$el, signedOut()));
		},
		// the person changed: the call in flight is dropped (gen) and the plan is read again for the one who is here now. The old call no
		// longer puts the spinner out (it is stale), so it is put out here and read() puts it back on if there is something to read:
		// without this a session that settled while the first read was in flight left the spinner on for ever and the plan never came
		onSessionChange() {
			this._gen++;
			this.loading = false;
			this.applying = false;
			this.runLoading = false;
			this.read();
		},
		async read() {
			if (!this.seePlan) { this.loading = false; return; }
			const gen = this._gen;
			this.loading = true;
			this.error = '';
			try {
				const p = await api('startup.plan', {}, { noLogin: true, quiet: true });
				if (gen !== this._gen) return;
				this.plan = p;
				this.sel = emptySelection();
				this.open = {};
				this.needsLogin = false;
			} catch (e) {
				if (gen !== this._gen) return;
				this.plan = null;
				const kind = errorKind(e);
				this.needsLogin = kind === 'login' || (kind === 'role' && signedOut());
				this.error = this.needsLogin || kind === 'role' ? '' : (e && e.message) || String(e);
			} finally {
				if (gen === this._gen) this.loading = false;
			}
		},
		async apply() {
			if (!this.isAdmin || this.block || this.applying) return;
			const gen = this._gen;
			this.applying = true;
			this.error = '';
			try {
				const r = await api('startup.apply', buildPayload(this.plan.items, this.sel));
				if (gen !== this._gen) return;
				this.result = r;
				this.run = null;
				await this.read();
			} catch (e) {
				if (gen !== this._gen) return;
				// refused before a byte was written (busy board, a safety confirmation, a group that is not whole): nothing changed
				this.error = (e && e.message) || String(e);
			} finally {
				if (gen === this._gen) {
					this.applying = false;
					// whatever the answer was (also a refusal), the statements about the machine and the safety files are asked again
					this.sel = afterApply(this.sel);
				}
			}
		},
		async toggleRun() {
			if (this.run) { this.run = null; return; }
			this.runLoading = true;
			try { this.run = await api('startup.runs.get', { run_id: this.result.run_id }, { quiet: true }); } catch (e) { this.error = (e && e.message) || String(e); } finally { this.runLoading = false; }
		}
	},
	created() { this._gen = 0; },
	mounted() { this.read(); },
	watch: {
		seePlan(v) { if (v && !this.plan) this.read(); },
		reportState: { immediate: true, deep: true, handler(v) { this.$emit('state', v); } }
	}
};
</script>

<style scoped>
.svc-wiz-intro { color: var(--tp-faint, #9e9e9e); max-width: 70ch; }
.svc-wiz-group { margin-top: 14px; }
.svc-wiz-head { font-size: 13px; font-weight: 600; padding-bottom: 4px; border-bottom: 1px solid var(--wf-line); }
.svc-wiz-help { color: var(--tp-faint, #9e9e9e); margin: 4px 0; }
.svc-wiz-item { padding: 8px; border-bottom: 1px solid rgba(128, 128, 128, 0.12); }
.svc-wiz-item.is-locked { opacity: 0.75; }
.svc-wiz-item.is-ticked { background: rgba(251, 140, 0, 0.06); }
.svc-wiz-row { display: grid; grid-template-columns: 150px minmax(0, 1fr) auto; align-items: center; column-gap: 10px; min-height: 48px; }
.svc-wiz-path { font-size: 13px; overflow-wrap: anywhere; }
.svc-wiz-reason { font-size: 12px; line-height: 1.4; color: var(--tp-faint, #9e9e9e); overflow-wrap: anywhere; }
.svc-wiz-touch { min-height: 44px; }
.svc-wiz-diffbox { margin-top: 6px; }
.svc-wiz-diff { font-size: 12px; line-height: 1.45; max-height: 320px; overflow: auto; padding: 8px; border-radius: 4px; background: rgba(128, 128, 128, 0.1); white-space: pre; }
.svc-wiz-diff .d-add { color: #2e7d32; display: block; }
.svc-wiz-diff .d-del { color: #c62828; display: block; }
.svc-wiz-diff .d-hunk, .svc-wiz-diff .d-file { color: #1565c0; display: block; }
.svc-wiz-diff .d-ctx { display: block; }
.svc-wiz-safety { margin: 6px 0 0 8px; padding: 6px 8px; border-left: 3px solid #FB8C00; }
.svc-wiz-foot { margin-top: 16px; }
.svc-wiz-apply { display: inline-flex; align-items: center; flex-wrap: wrap; }
.svc-wiz-why { color: var(--tp-faint, #9e9e9e); }
.svc-wiz-result { padding-top: 8px; border-top: 1px solid var(--wf-line); }
@media (max-width: 599px) {
	.svc-wiz-row { grid-template-columns: minmax(0, 1fr); row-gap: 4px; }
}
</style>
