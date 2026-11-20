<template>
	<div id="svc-roles" class="roles-card">
		<!-- Roles and permissions (phase 3 of informes/permisos-por-rol/DISENO.md). Administrator only: any other role sees ONE reason and nothing is asked of the service. -->
		<v-card class="mb-3">
			<v-card-title>
				<v-icon small class="mr-2 svx-ico">mdi-shield-key-outline</v-icon>{{ r('title') }}<access-term-help term="own_role" />
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
							<span v-if="list.roles.length >= list.limits.roles" class="wf-help">{{ r('limit_reached', { n: list.limits.roles }, list.limits.roles) }}</span>
						</div>

						<!-- the role being created or edited: its data, what changes, and apply -->
						<v-card v-if="draft" outlined class="roles-draft mb-3">
							<v-card-text>
								<h3 class="roles-h">{{ draft.isNew ? r('form_new_title') : r('form_edit_title', { name: draft.name }) }}</h3>
								<v-row dense align="start" class="roles-form-row">
									<v-col cols="12" sm="4">
										<wf-field id="roles-name" :label="r('field_name')">
											<sv-text-field id="roles-name" v-model="draft.name" :disabled="!draft.isNew" maxlength="32" autocomplete="off" :aria-label="r('field_name')" />
										</wf-field>
									</v-col>
									<v-col cols="12" sm="4">
										<wf-field id="roles-base" :label="r('field_base')">
											<template #help><help-tip :title="r('field_base')" :what="r('help_base_what')" :why="r('help_base_why')" :how="r('help_base_how')" /></template>
											<sv-select id="roles-base" v-model="draft.base" :items="baseItems" :aria-label="r('field_base')" />
										</wf-field>
									</v-col>
									<v-col cols="12" sm="4">
										<wf-field id="roles-desc" :label="r('field_description')">
											<sv-text-field id="roles-desc" v-model="draft.description" :maxlength="list.limits.description" autocomplete="off" :aria-label="r('field_description')" />
										</wf-field>
									</v-col>
								</v-row>
								<div v-if="foreign.length" class="wf-help mt-2">{{ r('foreign_kept', { n: foreign.length }, foreign.length) }}</div>

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

						<roles-matrix :columns="columns" :groups="groups" :tallies="tallies" :damaged="!!list.damaged" :draft-open="!!draft" :busy="busy" :armed-delete="armedDelete" @cell="onCell" @edit="startEdit" @remove="removeRole" />
					</template>
					<div v-else-if="loading" class="wf-help">{{ r('loading') }}</div>
				</template>
			</v-card-text>
		</v-card>

	</div>
</template>

<script>
'use strict'

import SvTextField from './ui/SvTextField.vue'
import SvSelect from './ui/SvSelect.vue'
import { api, currentIdentity, onIdentity, whoami } from './workshop-api.js'
import { roleMixin } from './role-mixin.js'
import HelpGuide from './HelpGuide.vue'
import HelpTip from './HelpTip.vue'
import LockReason from './LockReason.vue'
import RolesMatrix from './RolesMatrix.vue'
import AccessTermHelp from './AccessTermHelp.vue'
import WfField from './WfField.vue'
import {
	BASE_ROLES, CELL_INFO, diffStates, editable, emptyDef, foreignEntries, groupByCategory, isDirty, riskyGrants, tallyByCapability, toggle
} from './roles-matrix.js'

const NAME_RE = /^[\w .\-]{1,32}$/

export default {
	name: 'RolesCard',
	components: { SvTextField, SvSelect, AccessTermHelp, HelpGuide, HelpTip, LockReason, WfField, RolesMatrix },
	mixins: [roleMixin],
	// everything here came from the administrator who was signed in: emptied on sign-out and on a change of role (ESTANDAR 3.3)
	sessionData: ['list', 'tallies', 'draft', 'error', 'formError', 'msg', 'armedApply', 'armedDelete'],
	data() {
		return {
			identity: currentIdentity(),
			list: null, tallies: {},
			loading: false, busy: false, error: '', formError: '', msg: '',
			draft: null, armedApply: false, armedDelete: '',
			off: null
		}
	},
	computed: {
		isAdmin() { return !!this.identity && this.identity.role === 'admin' },
		usersOff() { return !!this.identity && (this.identity.configured === false || !!this.identity.users_disabled) },
		caps() { return this.list ? this.list.capabilities : [] },
		groups() { return this.list ? groupByCategory(this.list.capabilities, this.list.categories) : [] },
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
		// the stale calls no longer put their spinners out (gen), so they are put out here; the identity handler reads again for an admin
		onSessionChange() { this._gen++; this.loading = false },
		r(key, params, count) { return count === undefined ? this.$t('plugins.WorkshopService.roles.' + key, params) : this.$tc('plugins.WorkshopService.roles.' + key, count, params) },
		roleName(role) { return this.$t('plugins.WorkshopService.users.role_' + role) },
		cellLabel(s) { return this.r(CELL_INFO[s].label) },
		fail(e) { return e && e.code !== 'cancelled' ? (e.message || String(e)) : '' },
		canEdit(cap, col) { return editable(cap, col) && !(this.list && this.list.damaged) },
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
			} catch (e) {
				this.error = this.fail(e)
			}
			this.loading = false
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
/* The own roles card: only what is its own (prefix roles-); the matrix has its own file */
.roles-concepts { display: flex; flex-wrap: wrap; gap: 8px; }
.roles-concept { display: inline-flex; align-items: center; gap: 2px; padding: 0 2px 0 12px; border: 1px solid var(--wf-line-strong); border-radius: 999px; font-size: 13px; font-weight: 500; }
.roles-form-row .wf-field-label, .roles-form-row label { min-height: 28px; display: flex; align-items: center; }
.roles-form-row .v-input__control { min-height: 44px; }
.roles-form-row .v-input__slot { min-height: 44px !important; align-items: center; }
.roles-h { margin: 0 0 8px; font-size: 14px; font-weight: 600; }
.roles-diff { margin: 0; padding-left: 18px; font-size: 13px; }
.roles-diff li { margin-bottom: 4px; }
.roles-diff-change { margin-left: 8px; }
</style>
