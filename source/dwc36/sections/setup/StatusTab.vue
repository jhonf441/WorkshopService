<template>
	<!-- Setup > State: ONE verdict for the whole setup with the next thing to do, and one row for each installed plugin: what it reported the last time
	     (Ready / N of M steps left / Not opened yet: never "ready" without knowing), what it covers, a button to its own card and a four-line help.
	     A visitor reads what the plugins published; the files and the changes need a technician. Prop: active (this tab is in view). -->
	<div class="sv-setup-status">
		<sv-verdict :level="verdict.level" :title="headline" :facts="facts">
			<button v-if="nextButton" type="button" class="wf-btn sv-btn wf-main" data-act="next" @click="goNext">{{ nextButton }}</button>
		</sv-verdict>

		<section class="sv-card" aria-labelledby="sv-ss-title" data-card="plugins">
			<div class="sv-card-head">
				<h2 id="sv-ss-title"><span class="mdi mdi-clipboard-check-outline sv-ico" aria-hidden="true" />{{ t('setup.rows_title') }}</h2>
				<button type="button" class="wf-btn sv-btn" data-act="refresh" @click="refresh"><span class="mdi mdi-refresh sv-ico sv-ico-s" aria-hidden="true" />{{ t('kit.refresh') }}</button>
			</div>
			<p class="sv-lead">{{ t('setup.rows_lead') }}</p>
			<state-legend kind="levels" />
			<p v-if="readiness.status === 'error'" class="sv-field-error" role="alert" data-part="read-failed"><span class="mdi mdi-alert-outline sv-ico sv-ico-s" aria-hidden="true" />{{ t('setup.read_failed') }} <button type="button" class="wf-btn sv-btn sv-text" @click="readiness.reload()">{{ t('kit.retry') }}</button></p>
			<wf-zone class="sv-zone-host" v-else :status="zoneStatus" :lock="zoneLock(readiness.lock)" :empty-title="t('setup.rows_none')" @sign-in="signIn">
				<ul class="sv-rows">
					<sv-action-row v-for="r in rows" :key="r.key" :icon="r.icon" :name="rowName(r)" :desc="rowDesc(r)" :data-row="r.key">
						<template #control>
							<span class="sv-word" :data-level="level(r)" :data-key="r.key"><span class="mdi sv-ico sv-ico-s" :class="ICON[word(r)]" aria-hidden="true" />{{ wordText(r) }}</span>
							<button v-if="r.key === 'users'" type="button" class="wf-btn sv-btn" data-act="open" @click="nav.go({ s: 'access', t: 'people' })">{{ t('startup_master.users_action') }}</button>
							<button v-else-if="r.path && pageOn(r.path)" type="button" class="wf-btn sv-btn" :class="{ 'sv-text': word(r) === 'ready' }" data-act="open" @click="goPath(r.path)">{{ t(word(r) === 'ready' ? 'startup_master.open' : 'startup_master.open_check') }}</button>
							<span v-else-if="!r.path" class="sv-quiet sv-from-bar" data-part="from-bar">{{ t('startup_master.from_bar') }}</span>
						</template>
						<template #help><help-fold v-bind="help(r.key, 'setup')" /></template>
					</sv-action-row>
				</ul>
			</wf-zone>
		</section>
	</div>
</template>

<script>
import { goPath, pathExists, pluginOn, t as tr, tc as trc } from '../../core/dwc.js'
import { readiness, startupFiles, startupPlan } from '../../core/resources.js'
import { session, signIn, want } from '../../core/store/session.js'
import { rowsMixin } from '../../core/rows-mixin.js'
import { fileCounts } from '../../package-view.js'
import StateLegend from './StateLegend.vue'
import SvActionRow from '../../ui/SvActionRow.vue'
import HelpFold from '../../HelpFold.vue'
import SvVerdict from '../../ui/SvVerdict.vue'
import WfZone from '../../WfZone.vue'
import { WORD_LEVEL, readyCount, rowsOf, stepsOf, tabOfNext, verdictKeys, verdictOf, wordOf } from './view.js'

const ICON = { ready: 'mdi-check-circle-outline', pending: 'mdi-alert-outline', unchecked: 'mdi-clock-outline', login: 'mdi-account-lock-outline' }
const settled = r => r.status !== 'idle' && r.status !== 'loading'
const needsSession = r => !!r.lock && r.lock.state === 'session'

export default {
	name: 'StatusTab',
	components: { StateLegend, SvActionRow, HelpFold, SvVerdict, WfZone },
	mixins: [rowsMixin],
	inject: { nav: { from: 'svNav', default: () => ({ go() {}, href: () => '#' }) } },
	props: { active: { type: Boolean, default: false } },
	data() {
		return { readiness, ICON }
	},
	computed: {
		// nobody may read what the plugins reported: the rows say so, the verdict says "no session"
		needsLogin() {
			return needsSession(readiness)
		},
		usersOff() {
			return session.state !== 'resolving' && (session.usersOff || !session.configured)
		},
		rows() {
			return rowsOf(readiness.data && readiness.data.plugins, pluginOn, this.usersOff)
		},
		zoneStatus() {
			return readiness.status === 'ready' && !this.rows.length ? 'empty' : readiness.status
		},
		verdict() {
			const steps = Object.assign(stepsOf(this.rows, this.needsLogin), { settled: settled(readiness) || this.needsLogin })
			const fd = startupFiles.data
			const files = { loaded: !!fd, needsLogin: needsSession(startupFiles), counts: fd ? fileCounts(fd.plugins) : null, settled: settled(startupFiles) || startupFiles.status === 'locked' }
			const pd = startupPlan.data
			const plan = { loaded: !!pd, items: pd ? pd.items.length : 0, needsLogin: needsSession(startupPlan), settled: settled(startupPlan) || startupPlan.status === 'locked' }
			return verdictOf({ steps, files, plan })
		},
		keys() {
			return verdictKeys(this.verdict)
		},
		headline() {
			return this.keys.head === 'state_pending' || this.keys.head === 'state_attention' || this.keys.head === 'state_unchecked'
				? trc('configPackage.' + this.keys.head, this.keys.n, { n: this.keys.n }) : tr('configPackage.' + this.keys.head)
		},
		facts() {
			const out = this.keys.parts.map(p => trc('configPackage.' + p.key, p.n, { n: p.n }))
			const c = readyCount(this.rows, this.needsLogin)
			if (c.total && !this.needsLogin) out.unshift(this.t('setup.ready_of', { ready: c.ready, total: c.total }))
			return out
		},
		nextButton() {
			const id = this.verdict.next.id
			return id === 'sign_in' ? tr('configPackage.next_sign_in') : id === 'plan' ? tr('configPackage.next_plan') : id === 'files' ? tr('configPackage.next_files') : ''
		}
	},
	watch: {
		active: { immediate: true, handler(on) { if (on) this.show(); else this.hide() } }
	},
	methods: {
		goPath,
		show() {
			want(['readiness.list', 'startup.files', 'startup.plan'])
			readiness.show()
			startupFiles.show()
			startupPlan.show()
		},
		hide() {
			readiness.hide()
			startupFiles.hide()
			startupPlan.hide()
		},
		refresh() {
			readiness.reload()
			startupFiles.reload()
			startupPlan.reload()
		},
		goNext() {
			const id = this.verdict.next.id
			if (id === 'sign_in') return signIn()
			const tab = tabOfNext(this.verdict.next)
			if (tab) this.nav.go({ s: 'setup', t: tab })
		},
		pageOn(path) {
			return pathExists(path)
		},
		word(r) {
			return wordOf(r, this.needsLogin)
		},
		level(r) {
			return WORD_LEVEL[this.word(r)]
		},
		rowName(r) {
			return r.key === 'users' ? this.t('startup_master.name_users') : this.t('startup_master.name_' + r.key)
		},
		rowDesc(r) {
			return this.t('setup.covers_' + r.key)
		},
		wordText(r) {
			const w = this.word(r)
			if (r.key === 'users') return this.t('setup.word_users')
			if (w === 'login') return this.t('startup_master.login_row')
			if (w === 'unchecked') return this.t('setup.word_unchecked')
			if (w === 'pending') return this.tc('startup_master.pending', r.entry.total, { n: r.entry.pending, total: r.entry.total })
			if (r.entry && r.entry.skipped) return this.t('startup_master.ready_skipped', { n: r.entry.skipped })
			return this.t('startup_master.ready')
		}
	}
}
</script>
