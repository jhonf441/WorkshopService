<template>
	<!-- Security > Recorded activity (step 5 of DISENO-PANTALLAS): the old "Audit" section, grown. Who did what, from which device; now with the filters of the
	     service (group, target, result, refusals, detail), the rule that decided on each row, the whole event of a row, the verification chain, the export,
	     the recent alarms and the settings. Operations: audit.list / verify / export / settings and activity.list (type security_alarm) through access-api.js.
	     Nothing here can edit or delete a row: the service has no such operation. -->
	<v-card class="mb-3">
		<v-card-title class="text-subtitle-1">
			<v-icon small class="mr-2 svx-ico">mdi-clipboard-text-clock-outline</v-icon>{{ $t('plugins.WorkshopService.access.audit_title') }}
			<v-spacer />
			<v-btn small outlined class="access-touch mr-2" :disabled="!isAdmin" @click="settingsOpen = true"><v-icon left small>mdi-tune</v-icon>{{ $t('plugins.WorkshopService.access.audit_settings') }}</v-btn>
			<v-btn small outlined class="access-touch" :loading="loading" @click="refresh()"><v-icon left small>mdi-refresh</v-icon>{{ $t('plugins.WorkshopService.access.common_refresh') }}</v-btn>
		</v-card-title>
		<v-card-text>
			<div class="text-caption grey--text mb-3">{{ $t('plugins.WorkshopService.audit.help') }}</div>
			<session-notice v-if="!isAdmin" :kind="gateKind" variant="cover" needed="admin" />
			<access-state v-else :state="state" :detail="detail" @retry="read()">
				<activity-chain :can-verify="canTools" @broken="v => $emit('chain', v)" />
				<activity-alerts :tick="tick" @see="seeRefusals" />
				<activity-filters :value="f" :users="users" :groups="groupNames" :start-open="!narrow" @input="f = $event" @clear="clearFilters()" />
				<div v-if="!rows.length && !loading" class="wf-help access-own-empty">{{ $t('plugins.WorkshopService.access.audit_empty') }}</div>
				<div v-else class="access-table-wrap">
					<table class="access-table">
						<thead>
							<tr>
								<th>{{ $t('plugins.WorkshopService.access.audit_col_when') }}</th>
								<th>{{ $t('plugins.WorkshopService.access.audit_col_person') }}</th>
								<th>{{ $t('plugins.WorkshopService.access.audit_col_operation') }}</th>
								<th>{{ $t('plugins.WorkshopService.access.audit_col_result') }}</th>
								<th>{{ $t('plugins.WorkshopService.access.audit_col_decided') }}</th>
								<th></th>
							</tr>
						</thead>
						<tbody>
							<tr v-for="(r, i) in views" :key="r.id" class="access-row">
								<td class="text-caption" style="white-space:nowrap">{{ r.when }}</td>
								<td>
									{{ r.user || '-' }}
									<role-chip v-if="r.role" :role="r.role" :text="roleName(r.role)" class="ml-1" />
								</td>
								<td>
									<code>{{ r.op }}</code>
									<v-chip v-if="r.read" x-small outlined label class="ml-1">{{ $t('plugins.WorkshopService.access.audit_read_chip') }}</v-chip>
									<div v-if="r.target" class="text-caption grey--text">{{ r.target }}</div>
								</td>
								<td><v-chip x-small label outlined :color="RESULT_COLOR[r.result]">{{ $t('plugins.WorkshopService.access.audit_f_result_' + r.result) }}</v-chip></td>
								<td class="text-caption">{{ r.decided ? decidedText(r.decided) : '-' }}<code v-if="r.decided && decidedRaw(r.decided)" class="access-id">{{ decidedRaw(r.decided) }}</code></td>
								<td class="access-cell-act"><v-btn small outlined class="access-touch" @click="event = rows[i]">{{ $t('plugins.WorkshopService.access.common_view') }}</v-btn></td>
							</tr>
						</tbody>
					</table>
				</div>
				<div class="activity-foot">
					<span class="text-caption">{{ $t('plugins.WorkshopService.access.audit_count', pageInfo) }}</span>
					<v-spacer />
					<v-btn small outlined class="access-touch" :disabled="offset === 0" :aria-label="$t('plugins.WorkshopService.access.audit_prev')" @click="move(-1)"><v-icon small>mdi-chevron-left</v-icon></v-btn>
					<v-btn small outlined class="access-touch" :disabled="offset + PAGE >= total" :aria-label="$t('plugins.WorkshopService.access.audit_next')" @click="move(1)"><v-icon small>mdi-chevron-right</v-icon></v-btn>
					<activity-export :range="days" :can-export="canTools" class="ml-2" />
				</div>
				<div class="text-caption grey--text mt-2">{{ $tc('plugins.WorkshopService.access.audit_kept', KEPT_DAYS, { days: KEPT_DAYS }) }}</div>
			</access-state>
			<activity-event v-if="event" :key="event.id" :row="event" @close="event = null" />
			<activity-settings v-if="settingsOpen" :can-change="canTools" @close="settingsOpen = false" />
		</v-card-text>
	</v-card>
</template>

<script>
'use strict'

import { currentIdentity, onIdentity } from './workshop-api.js'
import { signedOut } from './workshop-auth.js'
import { roleMixin } from './role-mixin.js'
import { accessApi } from './access-api.js'
import SessionNotice from './SessionNotice.vue'
import AccessState from './AccessState.vue'
import RoleChip from './RoleChip.vue'
import ActivityChain from './ActivityChain.vue'
import ActivityAlerts from './ActivityAlerts.vue'
import ActivityFilters from './ActivityFilters.vue'
import ActivityExport from './ActivityExport.vue'
import ActivityEvent from './ActivityEvent.vue'
import ActivitySettings from './ActivitySettings.vue'
import { resolve, localText, relative } from './range-picker.js'
import { stateOfError } from './access-profile-view.js'
import { displayNamesMixin } from './display-names-mixin.js'
import { isNarrowScreen } from './access-report-view.js'
import { KEPT_DAYS, PAGE_SIZE, listArgs, pageText, rowView } from './access-audit-view.js'

const SLOW_MS = 15000
const RESULT_COLOR = { allowed: 'success', denied: 'error', error: 'warning' }

function freshFilters() {
	return { range: relative(7, 'days'), user: '', group: '', op: '', target: '', result: '', denied: false, errors: false, detail: true }
}

// layout only: under 900 px the filters start folded (all of them stay reachable)

export default {
	name: 'AuditCard',
	components: { SessionNotice, AccessState, RoleChip, ActivityChain, ActivityAlerts, ActivityFilters, ActivityExport, ActivityEvent, ActivitySettings },
	mixins: [roleMixin, displayNamesMixin],
	props: {
		// the operations of the service ({ op, kind }): a row of a read operation gets the "Read" chip
		operations: { type: Array, default: () => [] }
	},
	// the rows and the people of the old session are emptied on sign-out / change of role (ESTANDAR 3.3); the filters are not data of the session
	sessionData: ['rows', 'total', 'users', 'offset', 'error', 'failure', 'loading', 'groups', 'event', 'settingsOpen'],
	data() {
		return {
			f: freshFilters(), rows: [], total: 0, users: [], groups: null, offset: 0, loading: false, error: '', failure: null, slow: false, tick: 0,
			event: null, settingsOpen: false, identity: currentIdentity(), off: null, narrow: isNarrowScreen(), PAGE: PAGE_SIZE, KEPT_DAYS, RESULT_COLOR
		}
	},
	computed: {
		gateKind() { void this.identityTick; return signedOut() ? 'session' : 'role' },
		// one source of truth: the operation table of the service (audit.list is admin), as the rest of the page
		isAdmin() { return !!this.identity && this.canDo('audit.list') },
		// verifying, exporting and the settings are of the tools capability: a session may see the rows and not these
		canTools() { return this.canDo('audit.verify') && this.canDo('audit.export') && this.canDo('audit.settings') },
		readOps() { return new Set(this.operations.filter(o => o && o.kind === 'read').map(o => o.op)) },
		views() { return this.rows.map(r => rowView(r, this.readOps)) },
		groupNames() { return ((this.groups && this.groups.groups) || []).filter(g => g.source !== 'role').map(g => g.name) },
		// the range as days: the service filters by day (and the file of the export too)
		days() {
			const m = this.f.range ? resolve(this.f.range, new Date()) : null
			return m ? { from: localText(m.from).slice(0, 10), to: localText(m.to).slice(0, 10) } : { from: '', to: '' }
		},
		pageInfo() { return pageText(this.offset, this.rows.length, this.total) },
		// one state at a time, the first that applies (section 5)
		state() {
			if (this.failure) return stateOfError(this.failure)
			if (this.loading && !this.rows.length && !this.total) return this.slow ? 'slow' : 'loading'
			if (this.groups && this.groups.damaged) return 'damaged'
			if (!this.canTools) return 'read_only'
			return ''
		},
		detail() { return this.failure ? this.failure.message || '' : '' }
	},
	watch: {
		f: { deep: true, handler() { this.offset = 0; this.read() } }
	},
	created() { this._gen = 0; this._readSeq = 0 },
	mounted() {
		this.off = onIdentity(i => { this.identity = i; if (this.isAdmin) this.start() })
		if (this.isAdmin) this.start()
	},
	beforeDestroy() {
		if (this.off) this.off()
		clearTimeout(this.timer)
	},
	methods: {
		// an answer of the old person that is still on its way must not fill the table again
		// the stale call no longer puts the spinner out (gen), so it is put out here; the identity handler reads again when there is something to read
		onSessionChange() { this._gen++; this.loading = false },
		// the sentence of who decided with readable names; the ids and the error code stay as quiet code (decidedRaw)
		decidedText(d) {
			const p = Object.assign({}, d.params)
			if (p.profile !== undefined) {
				if (p.rule !== undefined) p.rule = this.ruleText(p.rule, p.profile)
				p.profile = this.profileText(p.profile)
			}
			if (p.ceiling !== undefined) p.ceiling = this.profilesText(p.ceiling)
			if (p.code !== undefined) p.reason = this.codeText(p.code)
			return this.$t('plugins.WorkshopService.access.' + d.key, p)
		},
		decidedRaw(d) {
			const p = d.params
			if (p.code) return p.code
			if (p.profile && this.profileCode(p.profile)) return p.profile + (p.rule ? ' / ' + p.rule : '')
			if (p.ceiling && String(p.ceiling).split(', ').some(c => this.profileCode(c))) return p.ceiling
			return ''
		},
		roleName(r) { const k = 'plugins.WorkshopService.users.role_' + r; return this.$te(k) ? this.$t(k) : r },
		start() {
			this.read()
			this.loadGroups()
		},
		refresh() {
			this.tick++
			this.read()
		},
		move(dir) { this.offset = Math.max(0, this.offset + dir * PAGE_SIZE); this.read() },
		// the button of an alert: the refusals of that minute and the one before, by permission
		seeRefusals(minute) {
			const at = new Date(minute.replace('T', ' ').replace(/-/g, '/'))
			if (isNaN(at.getTime())) return
			const p = n => String(n).padStart(2, '0')
			const text = d => d.getFullYear() + '-' + p(d.getMonth() + 1) + '-' + p(d.getDate()) + 'T' + p(d.getHours()) + ':' + p(d.getMinutes())
			this.f = Object.assign(freshFilters(), { detail: this.f.detail, denied: true, range: { type: 'absolute', from: text(new Date(at.getTime() - 60000)), to: text(at) } })
		},
		clearFilters() { this.f = Object.assign(freshFilters(), { detail: this.f.detail }) },
		// the groups of the filter come from access.groups.list; if it fails the filter just has no groups (the other filters work)
		async loadGroups() {
			try { this.groups = await accessApi.groupsList() } catch (e) { this.groups = null }
		},
		async read() {
			const gen = this._gen
			// only the LAST read may fill the table or decide the spinner: a slower answer of an earlier filter or page is dropped
			const seq = ++this._readSeq
			const current = () => gen === this._gen && seq === this._readSeq
			this.loading = true
			this.slow = false
			this.failure = null
			clearTimeout(this.timer)
			this.timer = setTimeout(() => { this.slow = true }, SLOW_MS)
			try {
				const d = this.days
				const r = await accessApi.auditList(listArgs(Object.assign({}, this.f, { from: d.from, to: d.to }), this.offset), { noLogin: true })
				if (!current()) return
				this.rows = r.rows || []
				this.total = r.total || 0
				this.users = r.users || []
				this.error = ''
				this.failure = null
			} catch (e) {
				if (!current()) return
				if (e.code !== 'cancelled') {
					this.failure = e
					this.error = e.message || String(e)
				}
			}
			clearTimeout(this.timer)
			this.loading = false
		}
	}
}
</script>

<style>
.activity-foot { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; margin-top: 8px; }
</style>
