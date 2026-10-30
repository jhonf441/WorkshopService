<template>
	<v-card v-if="rows.length" class="mb-3 svc-startup-master">
		<!-- Setup of the whole machine (2026-10-24). One line per INSTALLED plugin with what its own start-up card last said
		     (readiness.list). A plugin that is not installed or not enabled has no line; one that was never opened says
		     "not checked yet", never "ready". The card itself lives in each plugin's page: this only points at it. -->
		<v-card-title class="d-flex align-center flex-wrap" style="gap:8px">
			<span><v-icon small class="mr-2 svx-ico">mdi-rocket-launch-outline</v-icon>{{ $t(T + 'title') }}</span>
			<v-chip small outlined :color="needsLogin ? undefined : summary.pending ? 'warning' : summary.unchecked ? undefined : 'success'">{{ summaryText }}</v-chip>
			<v-spacer />
			<v-btn v-if="needsLogin" small color="primary" @click="logIn()"><v-icon small left>mdi-login</v-icon>{{ $t(T + 'log_in') }}</v-btn>
			<v-btn small text :loading="loading" @click="read()"><v-icon small left>mdi-refresh</v-icon>{{ $t('plugins.WorkshopService.common.refresh') }}</v-btn>
		</v-card-title>
		<v-card-text>
			<div class="text-body-2 mb-3 svc-sm-intro">{{ $t(T + 'intro') }}</div>
			<v-alert v-if="needsLogin" dense text type="info" class="mb-2">{{ $t(T + 'login_needed') }}</v-alert>
			<section v-for="g in groups" :key="g.id" class="svc-sm-group" :class="'svc-sm-group-' + g.id">
				<div class="svc-sm-head">
					<v-icon small :color="g.color">{{ g.icon }}</v-icon>
					<span>{{ $t(T + 'group_' + g.id, { n: g.rows.length }) }}</span>
				</div>
				<div v-for="r in g.rows" :key="r.key" class="svc-sm-row" :class="'svc-sm-' + g.id">
					<v-icon small :color="color(r)" class="svc-sm-ico">{{ icon(r) }}</v-icon>
					<div class="svc-sm-main">
						<div class="svc-sm-name">{{ $t(T + 'name_' + r.key) }}</div>
						<div class="svc-sm-state">{{ stateText(r) }}</div>
						<div v-if="r.entry && r.entry.total > 0" class="svc-sm-bar" role="progressbar" :aria-valuemin="0" :aria-valuemax="r.entry.total" :aria-valuenow="done(r)">
							<div class="svc-sm-fill" :class="'svc-sm-fill-' + g.id" :style="{ width: percent(r) + '%' }"></div>
						</div>
					</div>
					<div class="svc-sm-act">
						<v-btn v-if="r.section" small outlined color="warning" @click="$emit('section', r.section)">{{ $t(T + 'users_action') }}</v-btn>
						<v-btn v-else-if="r.path && hasPath(r.path)" small outlined :color="g.id === 'pending' ? 'warning' : undefined" @click="$router.push(r.path)">{{ $t(T + (r.entry ? 'open' : 'open_check')) }}</v-btn>
						<span v-else class="text-caption svc-sm-bar-note">{{ $t(T + 'from_bar') }}</span>
					</div>
				</div>
			</section>
		</v-card-text>
	</v-card>
</template>

<script>
'use strict'

import { api, askLogin, currentIdentity, onIdentity } from './workshop-api.js'
import { buildGroups, doneSteps, donePercent } from './startup-groups.js'
import { IDS, pluginActive, pathExists } from './workshop-ids.js'

// Plugins that have a start-up card, in the order a new person should go through them. path = the page that holds the card
// (none: the plugin lives in the side bar). key = the table of workshop-ids.js, also the end of the i18n key.
const PLUGINS = [
	{ key: 'bar', id: 'WorkshopControlBar' },
	{ key: 'lights', id: 'WorkshopLights', path: '/Plugins/Lights' },
	{ key: 'consumption', id: 'WorkshopPower', path: '/Plugins/Power' },
	{ key: 'motors', id: 'WorkshopMotors', path: '/Plugins/Motors' },
	{ key: 'jog', id: 'WorkshopJog' },
	{ key: 'camera', id: 'WorkshopCamera' },
	{ key: 'vision', id: 'WorkshopVision', path: '/Plugins/Vision' },
	{ key: 'workbench', id: 'WorkshopWorkbench', path: '/Plugins/Workbench' },
	{ key: 'printing', id: 'WorkshopPrinting', path: '/Plugins/Printing' },
	{ key: 'rs485', id: 'WorkshopRS485', path: '/Plugins/RS485' },
	{ key: 'activity', id: 'WorkshopActivity', path: '/Plugins/Activity' },
	{ key: 'health', id: 'WorkshopPiHealth', path: '/Plugins/PiHealth' }
];

export default {
	data() {
		return { T: 'plugins.WorkshopService.startup_master.', reported: {}, loading: false, needsLogin: false, off: null, identity: currentIdentity() };
	},
	computed: {
		// only the installed and enabled plugins; the id that is installed (new or old) is the one the report carries
		// Without people the roles do nothing and everybody who reaches DWC is an administrator: the first row of the list says it, with a button
		// to the Users section (it is never forced: a machine that works without users keeps working, it only stays pending here)
		usersRow() {
			const i = this.identity;
			return i && (i.users_disabled || i.configured === false) ? { key: 'users', id: 'users', section: 'users', entry: { pending: 1, total: 1 } } : null;
		},
		rows() {
			return (this.usersRow ? [this.usersRow] : []).concat(PLUGINS.filter(p => pluginActive(this.$store, p.key)).map(p => {
				const ids = IDS[p.key] || [p.id];
				const entry = ids.map(i => this.reported[i]).find(Boolean) || null;
				return Object.assign({}, p, { entry });
			}));
		},
		groups() {
			return buildGroups(this.rows, this.needsLogin);
		},
		summary() {
			const withData = this.rows.filter(r => r.entry);
			return {
				pending: withData.filter(r => r.entry.pending > 0).length,
				unchecked: this.rows.length - withData.length
			};
		},
		summaryText() {
			const s = this.summary;
			if (this.needsLogin) return this.$t(this.T + 'sum_login');
			if (s.pending) return this.$t(this.T + 'sum_pending', { n: s.pending });
			if (s.unchecked) return this.$t(this.T + 'sum_unchecked', { n: s.unchecked });
			return this.$t(this.T + 'sum_ready');
		}
	},
	methods: {
		done(r) { return doneSteps(r.entry); },
		percent(r) { return donePercent(r.entry); },
		hasPath(path) { return pathExists(this.$router, path); },
		async logIn() { await askLogin(); await this.read(); },
		color(r) { return !r.entry ? 'grey' : r.entry.pending ? 'warning' : 'success'; },
		icon(r) { return !r.entry ? 'mdi-help-circle-outline' : r.entry.pending ? 'mdi-alert-circle-outline' : 'mdi-check-circle-outline'; },
		stateText(r) {
			if (r.key === 'users') return this.$t(this.T + 'users_state');
			if (this.needsLogin) return this.$t(this.T + 'login_row');
			if (!r.entry) return this.$t(this.T + 'unchecked');
			if (r.entry.pending) return this.$t(this.T + 'pending', { n: r.entry.pending, total: r.entry.total });
			return this.$t(this.T + 'ready');
		},
		async read() {
			this.loading = true;
			try {
				const r = await api('readiness.list', {}, { noLogin: true, quiet: true });
				this.reported = (r && r.plugins) || {};
				this.needsLogin = false;
			} catch (e) {
				// no session: say so, do not pass it off as 'not checked'
				this.reported = {};
				this.needsLogin = !!e && (e.code === 'login_required' || e.code === 'forbidden');
			} finally {
				this.loading = false;
			}
		}
	},
	mounted() {
		this.read();
		this.off = onIdentity(i => { this.identity = i || currentIdentity(); this.read(); });
	},
	beforeDestroy() { if (this.off) this.off(); }
};
</script>

<style scoped>
.svc-sm-intro { color: var(--tp-faint, #9e9e9e); max-width: 70ch; }
.svc-sm-group + .svc-sm-group { margin-top: 14px; }
.svc-sm-group-pending { padding-left: 0; }
.svc-sm-group-unchecked { padding-left: 0; }
.svc-sm-group-ready { opacity: 0.85; }
.svc-sm-head {
	display: flex; align-items: center; gap: 6px;
	font-size: 13px; font-weight: 600;
	padding-bottom: 4px; border-bottom: 1px solid var(--wf-line);
}
.svc-sm-row {
	display: grid; grid-template-columns: 24px minmax(0, 1fr) auto; align-items: center; column-gap: 10px;
	padding: 8px 8px; border-bottom: 1px solid rgba(128, 128, 128, 0.12); min-height: 48px;
}
.svc-sm-row:last-child { border-bottom: 0; }
.svc-sm-pending { font-weight: 500; }
.svc-sm-name { font-size: 14px; font-weight: 500; line-height: 1.3; }
.svc-sm-state { font-size: 12px; line-height: 1.4; color: var(--tp-faint, #9e9e9e); white-space: normal; overflow-wrap: anywhere; }
.svc-sm-pending .svc-sm-state { color: inherit; opacity: 0.85; }
.svc-sm-bar { height: 4px; border-radius: 2px; margin-top: 6px; background: rgba(128, 128, 128, 0.25); overflow: hidden; max-width: 220px; }
.svc-sm-fill { height: 100%; border-radius: 2px; }
.svc-sm-fill-pending { background: #FB8C00; }
.svc-sm-fill-ready { background: #43A047; }
.svc-sm-bar-note { color: var(--tp-faint, #9e9e9e); text-align: right; max-width: 160px; }
@media (max-width: 599px) {
	.svc-sm-row { grid-template-columns: 24px minmax(0, 1fr); row-gap: 6px; }
	.svc-sm-act { grid-column: 2; }
	.svc-sm-bar { max-width: none; }
	.svc-sm-bar-note { text-align: left; max-width: none; }
}
</style>
