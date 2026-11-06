<template>
	<div class="roles-card">
		<!-- Roles and permissions (phase 3 of informes/permisos-por-rol/DISENO.md). Administrator only: any other role sees ONE reason and nothing is asked of the service. -->
		<v-card class="mb-3">
			<v-card-title>
				<v-icon small class="mr-2 svx-ico">mdi-shield-key-outline</v-icon>{{ r('title') }}
				<v-spacer />
				<v-btn v-if="isAdmin" small outlined :loading="loading" @click="read(true)"><v-icon left small>mdi-refresh</v-icon>{{ $t('plugins.WorkshopService.common.refresh') }}</v-btn>
			</v-card-title>
			<v-card-text>
				<div class="wf-help mb-2">{{ r('lead') }}</div>
				<lock-reason v-if="!isAdmin" op="roles.list" need="admin" class="mb-2" />
				<template v-else>
					<help-guide :what="r('guide_what')" :why="r('guide_why')" :if-missing="r('guide_missing')" :how="r('guide_how')" class="mb-3" />

					<div v-if="usersOff" class="wf-note is-warn mb-2">
						<v-icon class="wf-note-icon" aria-hidden="true">mdi-alert-outline</v-icon><span>{{ r('users_off') }}</span>
					</div>
					<div v-if="list && list.damaged" class="wf-note is-warn mb-2">
						<v-icon class="wf-note-icon" aria-hidden="true">mdi-alert-outline</v-icon><span>{{ r('damaged') }}</span>
					</div>
					<div v-if="error" class="wf-note is-warn mb-2" role="alert">
						<v-icon class="wf-note-icon" aria-hidden="true">mdi-alert-circle-outline</v-icon><span>{{ error }}</span>
					</div>

					<!-- what the words mean: one "?" each (H1) -->
					<div class="roles-concepts mb-3">
						<span v-for="c in concepts" :key="c.id" class="roles-concept">
							<span class="roles-concept-name">{{ c.name }}</span>
							<help-tip :title="c.name" :what="c.what" :why="c.why" :how="c.how" />
						</span>
					</div>

					<template v-if="list">
						<div class="wf-actions mb-2">
							<v-btn small color="primary" :disabled="!!draft || list.damaged" @click="startNew"><v-icon left small>mdi-plus</v-icon>{{ r('new_role') }}</v-btn>
							<span v-if="list.roles.length >= list.limits.roles" class="wf-help">{{ r('limit_reached', { n: list.limits.roles }) }}</span>
						</div>

						<!-- the role being created or edited: its data, what changes, and apply -->
						<v-card v-if="draft" outlined class="roles-draft mb-3">
							<v-card-text>
								<h3 class="roles-h">{{ draft.isNew ? r('form_new_title') : r('form_edit_title', { name: draft.name }) }}</h3>
								<v-row dense>
									<v-col cols="12" sm="4">
										<wf-field id="roles-name" :label="r('field_name')">
											<v-text-field id="roles-name" v-model="draft.name" :disabled="!draft.isNew" dense outlined hide-details counter="32" maxlength="32" autocomplete="off" :aria-label="r('field_name')" />
										</wf-field>
									</v-col>
									<v-col cols="12" sm="4">
										<wf-field id="roles-base" :label="r('field_base')">
											<template #help><help-tip :title="r('field_base')" :what="r('help_base_what')" :why="r('help_base_why')" :how="r('help_base_how')" /></template>
											<v-select id="roles-base" v-model="draft.base" :items="baseItems" dense outlined hide-details :aria-label="r('field_base')" />
										</wf-field>
									</v-col>
									<v-col cols="12" sm="4">
										<wf-field id="roles-desc" :label="r('field_description')">
											<v-text-field id="roles-desc" v-model="draft.description" dense outlined hide-details :counter="list.limits.description" :maxlength="list.limits.description" autocomplete="off" :aria-label="r('field_description')" />
										</wf-field>
									</v-col>
								</v-row>
								<div v-if="foreign.length" class="wf-help mt-2">{{ r('foreign_kept', { n: foreign.length }) }}</div>

								<h3 class="roles-h mt-3">{{ r('diff_title') }}</h3>
								<ul v-if="diffs.length" class="roles-diff">
									<li v-for="d in diffs" :key="d.id">
										<strong>{{ d.title }}</strong>
										<span class="roles-diff-change">{{ cellLabel(d.from) }} <v-icon x-small aria-hidden="true">mdi-arrow-right</v-icon> {{ cellLabel(d.to) }}</span>
									</li>
								</ul>
								<div v-else class="wf-help">{{ draft.isNew ? r('diff_new_plain', { base: roleName(draft.base) }) : r('diff_none') }}</div>

								<div v-if="risky.length" class="wf-note is-warn mt-2">
									<v-icon class="wf-note-icon" aria-hidden="true">mdi-alert-outline</v-icon><span>{{ r('risky_warning', { list: risky.map(c => c.title).join(', ') }) }}</span>
								</div>
								<div v-if="formError" class="wf-note is-warn mt-2" role="alert">
									<v-icon class="wf-note-icon" aria-hidden="true">mdi-alert-circle-outline</v-icon><span>{{ formError }}</span>
								</div>

								<div class="wf-actions">
									<v-btn small :color="armedApply ? 'amber darken-3' : 'primary'" :loading="busy" :disabled="!canApply" @click="apply">
										<v-icon left small>mdi-content-save-outline</v-icon>{{ armedApply ? r('apply_armed') : r('apply') }}
									</v-btn>
									<v-btn small text :disabled="busy" @click="discard">{{ $t('plugins.WorkshopService.common.cancel') }}</v-btn>
									<span v-if="!canApply && !busy" class="wf-help">{{ applyBlock }}</span>
								</div>
							</v-card-text>
						</v-card>
						<div v-if="msg" class="wf-help mb-2" role="status">{{ msg }}</div>

						<!-- the matrix: rows = capabilities by category, columns = roles -->
						<div class="wf-section-head">
							<h3 class="wf-h">{{ r('matrix_title') }}</h3>
							<p class="wf-lead">{{ r('matrix_help') }}</p>
						</div>
						<div class="roles-legend mb-2" aria-hidden="true">
							<span v-for="s in legend" :key="s" class="roles-key" :class="'is-' + s"><v-icon x-small>{{ cellIcon(s) }}</v-icon>{{ cellLabel(s) }}</span>
						</div>
						<div class="roles-scroll">
							<table class="roles-table">
								<thead>
									<tr>
										<th class="roles-cap-head" scope="col">{{ r('col_capability') }}</th>
										<th v-for="c in columns" :key="c.key" scope="col" class="roles-col-head" :class="{ 'is-custom': c.kind === 'custom', 'is-editing': c.editing }">
											<div class="roles-col-name">{{ c.label }}</div>
											<div class="roles-col-sub">
												<template v-if="c.kind === 'base'">{{ r('base_badge') }}</template>
												<template v-else>{{ r('column_base', { base: roleName(c.def.base) }) }}<template v-if="!c.isNew"> &middot; {{ r('users_n', { n: c.role.users }) }}</template></template>
											</div>
											<div v-if="c.kind === 'custom' && !c.isNew" class="roles-col-actions">
												<v-btn icon small :disabled="!!draft && !c.editing" :title="r('edit_role')" :aria-label="r('edit_role') + ': ' + c.label" @click="startEdit(c.role)"><v-icon small>mdi-pencil</v-icon></v-btn>
												<v-btn icon small :color="armedDelete === c.name ? 'error' : null" :disabled="busy || (!!draft && !c.editing)" :title="armedDelete === c.name ? r('tap_again_delete') : r('delete_role')" :aria-label="(armedDelete === c.name ? r('tap_again_delete') : r('delete_role')) + ': ' + c.label" @click="removeRole(c.role)"><v-icon small>mdi-delete</v-icon></v-btn>
											</div>
										</th>
									</tr>
								</thead>
								<tbody v-for="g in groups" :key="g.id">
									<tr class="roles-group"><th :colspan="columns.length + 1" scope="colgroup">{{ g.title }}</th></tr>
									<tr v-for="cap in g.caps" :key="cap.id">
										<th scope="row" class="roles-cap">
											<div class="roles-cap-title">{{ cap.title }}</div>
											<div class="roles-cap-chips">
												<span class="wf-pill">{{ className(cap.class) }}</span>
												<span class="wf-pill" :class="{ 'roles-risk-high': cap.risk >= 3 }">{{ r('risk', { n: cap.risk }) }}</span>
											</div>
										</th>
										<td v-for="c in columns" :key="c.key" class="roles-td">
											<button
												type="button" class="roles-cell" :class="['is-' + state(cap, c), { 'is-fixed': !canEdit(cap, c) }]"
												:aria-disabled="!canEdit(cap, c)" :aria-label="cellAria(cap, c)" :title="cellWhy(state(cap, c))"
												@click="onCell(cap, c)"
											>
												<v-icon small aria-hidden="true">{{ cellIcon(state(cap, c)) }}</v-icon>
												<span class="roles-cell-text">{{ cellLabel(state(cap, c)) }}</span>
											</button>
										</td>
									</tr>
								</tbody>
							</table>
						</div>
					</template>
					<div v-else-if="loading" class="wf-help">{{ r('loading') }}</div>
				</template>
			</v-card-text>
		</v-card>

		<!-- what a person or a role may do -->
		<v-card v-if="isAdmin && list" class="mb-3">
			<v-card-title>
				<v-icon small class="mr-2 svx-ico">mdi-account-search-outline</v-icon>{{ r('eff_title') }}
			</v-card-title>
			<v-card-text>
				<div class="wf-help mb-2">{{ r('eff_help') }}</div>
				<v-row dense>
					<v-col cols="12" sm="5">
						<wf-field id="roles-subject" :label="r('eff_subject')">
							<v-select id="roles-subject" v-model="subject" :items="subjectItems" dense outlined hide-details :placeholder="r('eff_choose')" :aria-label="r('eff_subject')" />
						</wf-field>
					</v-col>
					<v-col cols="12" sm="4">
						<wf-field id="roles-search" :label="r('eff_search')">
							<v-text-field id="roles-search" v-model="query" dense outlined hide-details clearable autocomplete="off" :aria-label="r('eff_search')" />
						</wf-field>
					</v-col>
					<v-col cols="12" sm="3" class="d-flex align-end">
						<v-checkbox v-model="blockedOnly" dense hide-details class="mt-0" :label="r('eff_blocked_only')" />
					</v-col>
				</v-row>
				<div v-if="effError" class="wf-note is-warn mt-2" role="alert">
					<v-icon class="wf-note-icon" aria-hidden="true">mdi-alert-circle-outline</v-icon><span>{{ effError }}</span>
				</div>
				<div v-if="!subject" class="wf-help mt-3">{{ r('eff_choose') }}</div>
				<template v-else-if="effective">
					<div class="roles-eff-summary mt-3">
						<span class="wf-pill">{{ r('eff_counts', { allowed: effective.counts.allowed, blocked: effective.counts.blocked }) }}</span>
						<span class="wf-pill">{{ r('eff_extra', { grants: effective.counts.by_grant, denials: effective.counts.by_deny }) }}</span>
						<span class="wf-pill">{{ effective.hardware_params ? r('eff_hardware_yes') : r('eff_hardware_no') }}</span>
					</div>
					<v-simple-table dense class="mt-2">
						<thead>
							<tr><th>{{ r('eff_col_op') }}</th><th>{{ r('eff_col_state') }}</th><th>{{ r('eff_col_reason') }}</th></tr>
						</thead>
						<tbody>
							<tr v-for="o in shownRows" :key="o.op">
								<td><code>{{ o.op }}</code></td>
								<td style="white-space:nowrap"><span class="wf-state" :class="o.allowed ? 'ok' : 'err'">{{ o.allowed ? r('eff_allowed') : r('eff_blocked') }}</span></td>
								<td class="text-caption">{{ o.allowed ? sourceText(o.source) : (o.message || '') }}</td>
							</tr>
							<tr v-if="!filteredRows.length"><td colspan="3" class="text-center">{{ r('eff_none') }}</td></tr>
						</tbody>
					</v-simple-table>
					<v-btn v-if="filteredRows.length > shownRows.length" small outlined class="mt-2" @click="showAll = true">{{ r('eff_show_all', { n: filteredRows.length }) }}</v-btn>
				</template>
				<div v-else-if="effLoading" class="wf-help mt-3">{{ r('loading') }}</div>
			</v-card-text>
		</v-card>
	</div>
</template>

<script>
'use strict'

import { api, currentIdentity, onIdentity, whoami } from './workshop-api.js'
import { roleMixin } from './role-mixin.js'
import HelpGuide from './HelpGuide.vue'
import HelpTip from './HelpTip.vue'
import LockReason from './LockReason.vue'
import WfField from './WfField.vue'
import {
	BASE_ROLES, CELL_INFO, CLASS_KEYS, cellState, diffStates, editable, emptyDef, filterEffective, foreignEntries, groupByCategory, isDirty, riskyGrants, subjectArgs,
	tallyByCapability, toggle
} from './roles-matrix.js'

const NAME_RE = /^[\w .\-]{1,32}$/
const ROWS_SHOWN = 100
const LEGEND = ['allowed', 'partial', 'blocked', 'limited', 'granted', 'denied', 'locked', 'stop']

export default {
	name: 'RolesCard',
	components: { HelpGuide, HelpTip, LockReason, WfField },
	mixins: [roleMixin],
	// everything here came from the administrator who was signed in: emptied on sign-out and on a change of role (ESTANDAR 3.3)
	sessionData: ['list', 'tallies', 'people', 'draft', 'subject', 'effective', 'error', 'effError', 'formError', 'msg', 'armedApply', 'armedDelete', 'query', 'showAll'],
	data() {
		return {
			identity: currentIdentity(),
			list: null, tallies: {}, people: [],
			loading: false, busy: false, error: '', formError: '', msg: '',
			draft: null, armedApply: false, armedDelete: '',
			subject: '', effective: null, effLoading: false, effError: '', blockedOnly: true, query: '', showAll: false,
			off: null
		}
	},
	computed: {
		isAdmin() { return !!this.identity && this.identity.role === 'admin' },
		usersOff() { return !!this.identity && (this.identity.configured === false || !!this.identity.users_disabled) },
		caps() { return this.list ? this.list.capabilities : [] },
		groups() { return this.list ? groupByCategory(this.list.capabilities, this.list.categories) : [] },
		legend() { return LEGEND },
		baseItems() { return (this.list ? this.list.bases : []).map(b => ({ value: b, text: this.roleName(b) })) },
		saved() {
			if (!this.draft || this.draft.isNew || !this.list) return null
			return this.list.roles.find(x => x.name === this.draft.name) || null
		},
		columns() {
			const out = BASE_ROLES.map(role => ({ key: 'b:' + role, kind: 'base', role, label: this.roleName(role) }))
			if (!this.list) return out
			this.list.roles.forEach(role => {
				const editing = !!this.draft && !this.draft.isNew && this.draft.name === role.name
				out.push({ key: 'c:' + role.name, kind: 'custom', name: role.name, label: role.name, role, editing, def: editing ? this.draft : role })
			})
			if (this.draft && this.draft.isNew) out.push({ key: 'c:new', kind: 'custom', isNew: true, editing: true, name: this.draft.name, label: this.draft.name || this.r('new_column'), def: this.draft })
			return out
		},
		before() { return this.draft && !this.draft.isNew ? this.saved : emptyDef(this.draft ? this.draft.base : 'operator') },
		diffs() { return this.draft && this.before ? diffStates(this.caps, this.before, this.draft, this.tallies) : [] },
		foreign() { return this.draft ? foreignEntries(this.draft, this.caps) : [] },
		risky() { return this.draft ? riskyGrants(this.caps, this.draft, 4) : [] },
		nameOk() { return !!this.draft && NAME_RE.test(this.draft.name.trim()) },
		dirty() { return !!this.draft && (this.draft.isNew || isDirty(this.saved, this.draft)) },
		canApply() { return !!this.draft && this.nameOk && this.dirty && !this.busy && !(this.list && this.list.damaged) },
		applyBlock() {
			if (!this.draft) return ''
			if (!this.nameOk) return this.r('block_name')
			if (!this.dirty) return this.r('block_nothing')
			return ''
		},
		subjectItems() {
			const items = [{ header: this.r('eff_group_users') }]
			this.people.forEach(p => items.push({ value: 'user:' + p.name, text: p.name + ' (' + this.roleName(p.role) + ')' }))
			items.push({ divider: true }, { header: this.r('eff_group_roles') })
			BASE_ROLES.forEach(b => items.push({ value: 'role:' + b, text: this.roleName(b) }))
			;(this.list ? this.list.roles : []).forEach(x => items.push({ value: 'role:' + x.name, text: x.name }))
			return items
		},
		filteredRows() { return this.effective ? filterEffective(this.effective.ops, { blockedOnly: this.blockedOnly, query: this.query }) : [] },
		shownRows() { return this.showAll ? this.filteredRows : this.filteredRows.slice(0, ROWS_SHOWN) },
		concepts() {
			return [
				{ id: 'custom', name: this.r('help_custom_title'), what: this.r('help_custom_what'), why: this.r('help_custom_why'), how: this.r('help_custom_how') },
				{ id: 'base', name: this.r('help_base_title'), what: this.r('help_base_what'), why: this.r('help_base_why'), how: this.r('help_base_how') },
				{ id: 'granted', name: this.r('help_granted_title'), what: this.r('help_granted_what'), why: this.r('help_granted_why'), how: this.r('help_granted_how') },
				{ id: 'denied', name: this.r('help_denied_title'), what: this.r('help_denied_what'), why: this.r('help_denied_why'), how: this.r('help_denied_how') },
				{ id: 'locked', name: this.r('help_locked_title'), what: this.r('help_locked_what'), why: this.r('help_locked_why'), how: this.r('help_locked_how') }
			]
		}
	},
	watch: {
		subject() { this.showAll = false; this.loadEffective() },
		draft(d) { if (!d) { this.armedApply = false; this.formError = '' } }
	},
	created() { this._gen = 0 },
	async mounted() {
		this.off = onIdentity(i => { this.identity = i; this.read() })
		await whoami().catch(() => null)
		this.identity = currentIdentity()
		await this.read()
	},
	beforeDestroy() { if (this.off) this.off() },
	methods: {
		// an answer of the old person that is still on its way must not fill the card again
		onSessionChange() { this._gen++ },
		r(key, params) { return this.$t('plugins.WorkshopService.roles.' + key, params) },
		roleName(role) { return this.$t('plugins.WorkshopService.users.role_' + role) },
		className(k) { return this.r(CLASS_KEYS[k] || CLASS_KEYS.read) },
		cellIcon(s) { return CELL_INFO[s].icon },
		cellLabel(s) { return this.r(CELL_INFO[s].label) },
		cellWhy(s) { return this.r(CELL_INFO[s].why) },
		sourceText(src) { return src === 'grant' ? this.r('src_grant') : src === 'base' ? this.r('src_base') : '' },
		fail(e) { return e && e.code !== 'cancelled' ? (e.message || String(e)) : '' },
		state(cap, col) { return cellState(cap, col, this.tallies) },
		canEdit(cap, col) { return editable(cap, col) && !(this.list && this.list.damaged) },
		cellAria(cap, col) {
			const s = this.state(cap, col)
			return cap.title + ', ' + col.label + ': ' + this.cellLabel(s) + '. ' + (this.canEdit(cap, col) ? this.r('cell_click_hint') : this.cellWhy(s))
		},
		async read(force) {
			const gen = this._gen
			if (!this.isAdmin) return
			this.loading = true
			try {
				const list = await api('roles.list', {}, { noLogin: true })
				if (gen !== this._gen) return
				if (force || !Object.keys(this.tallies).length) {
					const rows = await Promise.all(BASE_ROLES.map(role => api('roles.effective', { role }, { noLogin: true })))
					if (gen !== this._gen) return
					const tallies = {}
					BASE_ROLES.forEach((role, i) => { tallies[role] = tallyByCapability(rows[i].ops) })
					this.tallies = tallies
				}
				this.list = list
				this.error = ''
				const users = await api('users.list', {}, { noLogin: true }).catch(() => null)
				if (gen !== this._gen) return
				this.people = users && users.users ? users.users.map(u => ({ name: u.name, role: u.role })) : []
				if (this.subject) this.loadEffective()
			} catch (e) {
				this.error = this.fail(e)
			}
			this.loading = false
		},
		async loadEffective() {
			const gen = this._gen
			const args = subjectArgs(this.subject)
			this.effective = null
			this.effError = ''
			if (!args || !this.isAdmin) return
			this.effLoading = true
			try {
				const res = await api('roles.effective', args, { noLogin: true })
				if (gen !== this._gen || this.subject === '') return
				this.effective = res
			} catch (e) {
				this.effError = this.fail(e)
			}
			this.effLoading = false
		},
		startNew() {
			this.msg = ''
			this.formError = ''
			this.draft = { isNew: true, name: '', base: 'operator', description: '', grant: [], deny: [] }
		},
		startEdit(role) {
			this.msg = ''
			this.formError = ''
			this.draft = { isNew: false, name: role.name, base: role.base, description: role.description || '', grant: role.grant.slice(), deny: role.deny.slice() }
		},
		discard() { this.draft = null },
		onCell(cap, col) {
			if (!this.canEdit(cap, col)) return
			if (this.draft && !col.editing) {
				this.msg = this.r('switch_block')
				return
			}
			if (!this.draft) this.startEdit(col.role)
			this.msg = ''
			const next = toggle(cap, this.draft, this.tallies)
			this.draft = Object.assign({}, this.draft, { grant: next.grant, deny: next.deny })
		},
		async apply() {
			if (!this.canApply) return
			if (!this.armedApply) {
				this.armedApply = true
				setTimeout(() => { this.armedApply = false }, 4000)
				return
			}
			this.armedApply = false
			const d = this.draft
			this.busy = true
			this.formError = ''
			try {
				await api('roles.set', { name: d.name.trim(), base: d.base, grant: d.grant, deny: d.deny, description: d.description || '' }, { confirm: true })
				this.draft = null
				this.msg = this.r('saved')
				await this.read()
			} catch (e) {
				this.formError = this.fail(e)
			}
			this.busy = false
		},
		async removeRole(role) {
			if (this.armedDelete !== role.name) {
				this.armedDelete = role.name
				setTimeout(() => { if (this.armedDelete === role.name) this.armedDelete = '' }, 4000)
				return
			}
			this.armedDelete = ''
			this.busy = true
			this.error = ''
			try {
				await api('roles.remove', { name: role.name }, { confirm: true })
				this.draft = null
				this.msg = this.r('deleted')
				await this.read()
			} catch (e) {
				this.error = this.fail(e)
			}
			this.busy = false
		}
	}
}
</script>

<style>
/* The roles matrix: only what is its own (prefix roles-); colors are the tokens of the family (family.css), the meaning is also an icon and a word */
.roles-concepts { display: flex; flex-wrap: wrap; gap: 4px 16px; }
.roles-concept { display: inline-flex; align-items: center; gap: 2px; font-size: 13px; font-weight: 500; }
.roles-h { margin: 0 0 8px; font-size: 14px; font-weight: 600; }
.roles-diff { margin: 0; padding-left: 18px; font-size: 13px; }
.roles-diff li { margin-bottom: 4px; }
.roles-diff-change { margin-left: 8px; }
.roles-legend { display: flex; flex-wrap: wrap; gap: 4px 14px; font-size: 12px; }
.roles-key { display: inline-flex; align-items: center; gap: 4px; }
.roles-scroll { overflow-x: auto; max-width: 100%; border: 1px solid var(--wf-line); border-radius: 8px; }
.roles-table { border-collapse: separate; border-spacing: 0; width: 100%; min-width: 640px; font-size: 13px; }
.roles-table th, .roles-table td { padding: 6px 8px; border-bottom: 1px solid var(--wf-line); text-align: left; vertical-align: middle; }
.roles-cap-head, .roles-cap { position: sticky; left: 0; z-index: 1; min-width: 150px; max-width: 220px; background: var(--wf-surface); font-weight: 400; }
.roles-cap-head { font-size: 11px; font-weight: 600; text-transform: uppercase; }
.roles-col-head { min-width: 104px; text-align: center !important; vertical-align: top !important; }
.roles-col-head.is-editing { border-top: 2px solid var(--wf-accent); }
.roles-col-name { font-size: 13px; font-weight: 600; overflow-wrap: anywhere; }
.roles-col-sub { font-size: 11px; font-weight: 400; opacity: 0.8; }
.roles-col-actions { display: flex; justify-content: center; gap: 4px; margin-top: 4px; }
.roles-group th { padding: 8px; background: var(--wf-soft); font-size: 12px; font-weight: 600; text-transform: none; }
.roles-cap-title { font-weight: 500; overflow-wrap: anywhere; }
.roles-cap-chips { display: flex; flex-wrap: wrap; gap: 4px; margin-top: 2px; }
.roles-cap-chips .wf-pill { padding: 0 8px; }
.roles-risk-high { border-color: var(--wf-c-warning); }
.roles-td { padding: 2px !important; text-align: center !important; }
.roles-cell { display: flex; align-items: center; justify-content: center; gap: 4px; width: 100%; min-height: 44px; padding: 2px 6px; border: 1px solid transparent; border-radius: 6px; background: transparent; color: inherit; font: inherit; font-size: 12px; cursor: pointer; }
.roles-cell:hover:not(.is-fixed) { border-color: var(--wf-line-strong); background: var(--wf-soft); }
.roles-cell.is-fixed { cursor: default; }
.roles-cell:focus-visible { outline: 2px solid var(--wf-accent); outline-offset: -2px; }
.roles-cell-text { overflow-wrap: anywhere; }
.roles-cell.is-allowed .v-icon, .roles-cell.is-stop .v-icon, .roles-key.is-allowed .v-icon, .roles-key.is-stop .v-icon { color: var(--wf-c-success) !important; }
.roles-cell.is-partial .v-icon, .roles-cell.is-limited .v-icon, .roles-key.is-partial .v-icon, .roles-key.is-limited .v-icon { color: var(--wf-c-warning) !important; }
.roles-cell.is-granted .v-icon, .roles-key.is-granted .v-icon { color: var(--wf-c-info) !important; }
.roles-cell.is-granted .roles-cell-text { color: var(--wf-c-info-text); font-weight: 600; }
.roles-cell.is-denied .v-icon, .roles-key.is-denied .v-icon { color: var(--wf-c-error) !important; }
.roles-cell.is-denied .roles-cell-text { color: var(--wf-c-error-text); font-weight: 600; }
.roles-cell.is-blocked, .roles-cell.is-locked { opacity: 0.75; }
.roles-eff-summary { display: flex; flex-wrap: wrap; gap: 8px; }
@media (max-width: 599px) {
	.roles-cap-head, .roles-cap { min-width: 120px; max-width: 140px; }
	.roles-col-head { min-width: 92px; }
}
</style>
