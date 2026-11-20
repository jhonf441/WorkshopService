<template>
	<!-- Edit one custom profile, or a new one (or a copy of a base one): Builder | JSON | Versions, the dry run (access.profiles.validate) after every change,
	     the single before / after dialog, save (access.profiles.set), versions with Compare and Go back (access.profile.rollback). The service judges every
	     step; what this adds is the check of the obvious mistakes, the dialog, and the state "another administrator changed it".
	       <access-profile-editor :name="'Lights'" :caps="rolesList" :names="[...]" :limits="{ rules: 50, versions: 5 }" :damaged="false" @back @saved="name => ..." /> -->
	<div class="access-profile-view access-profile-editor">
		<div class="access-view-head">
			<v-btn small outlined class="access-touch" @click="$emit('back')"><v-icon left small>mdi-arrow-left</v-icon>{{ $t('plugins.WorkshopService.access.common_back') }}</v-btn>
			<strong class="access-view-name">{{ draft.name || $t('plugins.WorkshopService.access.edit_new_title') }}</strong>
			<v-chip small outlined label>{{ $t('plugins.WorkshopService.access.profiles_type_own') }}</v-chip>
			<v-chip v-if="got" small outlined label color="success">{{ $t('plugins.WorkshopService.access.profiles_version_of', { n: got.version, total: got.versions }) }}</v-chip>
			<v-chip v-if="viewing" small outlined label color="info">{{ $t('plugins.WorkshopService.access.versions_viewing', { n: viewing }) }}</v-chip>
			<v-spacer />
			<v-btn small outlined class="access-touch" @click="$emit('back')">{{ $t('plugins.WorkshopService.access.common_cancel') }}</v-btn>
			<v-btn small color="primary" class="access-touch" :disabled="!reviewable" @click="openDialog('save')">{{ $t('plugins.WorkshopService.access.edit_review') }}</v-btn>
		</div>
		<access-state :state="state" :detail="detail" @retry="load()">
			<template v-if="draft">
				<div v-if="seedNote" class="wf-note mb-2" role="note"><v-icon class="wf-note-icon" aria-hidden="true">mdi-information-outline</v-icon><span>{{ seedText || $t('plugins.WorkshopService.access.edit_duplicate_note') }}</span></div>
				<div class="access-name-row">
					<sv-text-field :value="draft.name" :readonly="!fresh" class="access-name-field" :label="$t('plugins.WorkshopService.access.builder_name')" @input="setName" />
					<help-tip :title="$t('plugins.WorkshopService.access.builder_name')" :what="$t('plugins.WorkshopService.access.' + (fresh ? 'builder_name_rule' : 'edit_name_locked'))" />
				</div>
				<div v-if="got" class="access-holders wf-help">
					<span class="access-rule-label">{{ $t('plugins.WorkshopService.access.profiles_col_holders') }}</span>
					<span v-if="!users.length && !groups.length">{{ $t('plugins.WorkshopService.access.profiles_holders_nobody') }}</span>
					<span v-if="users.length">{{ $t('plugins.WorkshopService.access.profiles_holders_users', { names: users.join(', ') }) }}</span>
					<span v-if="groups.length">{{ $t('plugins.WorkshopService.access.profiles_holders_groups', { names: groups.join(', ') }) }}</span>
				</div>
				<div class="access-modes" role="group">
					<button v-for="m in modes" :key="m" type="button" class="access-kind access-touch" :class="{ 'is-on': mode === m }" :aria-pressed="mode === m ? 'true' : 'false'" @click="goMode(m)">{{ $t('plugins.WorkshopService.access.builder_mode_' + m) }}{{ m === 'versions' && got ? ' (' + got.versions + ')' : '' }}</button>
				</div>
				<div v-if="nameTaken" class="access-problem" role="alert">{{ $t('plugins.WorkshopService.access.builder_name_taken') }}</div>
				<div v-for="(p, i) in topIssues" :key="'p' + i" class="access-problem" role="alert">{{ $t('plugins.WorkshopService.access.check_' + p.code, p.params) }}</div>
				<div v-if="savedNote" class="wf-note mb-2" role="status"><v-icon class="wf-note-icon" aria-hidden="true">mdi-check-circle-outline</v-icon><span>{{ savedNote }}</span></div>
				<div class="access-check-line wf-help" role="status">{{ verdict }}</div>
				<div v-for="w in warnings" :key="w.code" class="access-warning wf-help" role="note">{{ w.text }}</div>
				<access-rules-editor v-if="mode === 'builder'" :doc="draft" :ctx="ctx" :issues="issues" :suggestions="ctx.known" :max="maxRules" :accordion="narrow" @input="setDraft" />
				<access-json-editor v-else-if="mode === 'json'" :text="jsonDraft" :readonly="readOnly" :line="jsonLine" @input="typed" @format="format" @validate="validateNow()" />
				<template v-else>
					<access-version-list :name="draft.name" :versions="versions" :max="maxVersions" :viewing="viewing" :editable="true" :locked="damaged" @view="n => viewing = n === (got && got.version) ? 0 : n" @compare="n => openDialog('compare', n)" @rollback="n => openDialog('rollback', n)" />
					<access-capability-builder v-if="viewing" :doc="shownDoc" :capabilities="ctx.caps" :categories="ctx.categories" :max="maxRules" />
				</template>
			</template>
		</access-state>
		<access-profile-change v-if="dialog" :value="true" :title="dialogTitle" :confirm-label="dialogVerb" :diff="dialogDiff" :attached="attached" :warnings="dialog.kind === 'save' ? warnings : []" :risk4="risk4" :drop="dialog.kind === 'save' ? next.drops : null" :is-new="dialog.kind === 'save' && fresh" :view-only="dialog.kind === 'compare'" :busy="busy" :error="dialogError" @input="closeDialog" @confirm="confirm" />
	</div>
</template>

<script>
'use strict'

import SvTextField from './ui/SvTextField.vue'
import HelpTip from './HelpTip.vue'
import AccessState from './AccessState.vue'
import AccessRulesEditor from './AccessRulesEditor.vue'
import AccessJsonEditor from './AccessJsonEditor.vue'
import AccessVersionList from './AccessVersionList.vue'
import AccessCapabilityBuilder from './AccessCapabilityBuilder.vue'
import AccessProfileChange from './AccessProfileChange.vue'
import { accessApi } from './access-api.js'
import { diffProfile, nextVersion } from './access-diff.js'
import { buildable, canReview, checkDoc, cloneDoc, contextOf, emptyDoc, parseJson, riskOf, sameDoc } from './access-profile-edit.js'
import { jsonText, stateOfError } from './access-profile-view.js'
import { isNarrowScreen } from './access-report-view.js'

const VALIDATE_MS = 350

export default {
	components: { SvTextField, HelpTip, AccessState, AccessRulesEditor, AccessJsonEditor, AccessVersionList, AccessCapabilityBuilder, AccessProfileChange },
	props: {
		name: { type: String, default: '' }, // a saved custom profile; empty for a new one
		seed: { type: Object, default: null }, // the document a new one starts from (a copy of a base profile)
		seedText: { type: String, default: '' }, // the sentence of the note above the copy when it did not come from a base profile (a template)
		caps: { type: Object, default: () => ({}) }, // the answer of roles.list
		limits: { type: Object, default: () => ({ rules: 50, versions: 5 }) },
		damaged: { type: Boolean, default: false },
		readOnly: { type: Boolean, default: false }
	},
	data() {
		return {
			got: null, versions: [], draft: emptyDoc(this.name), fresh: !this.name, openedVersion: 0, state: this.name ? 'loading' : '', detail: '',
			mode: 'builder', nameTaken: false, jsonDraft: '', jsonLine: 0, jsonBad: false, viewing: 0,
			validation: null, refusal: '', validating: false, dialog: null, busy: false, dialogError: '', savedNote: '', seedNote: !!this.seed,
			narrow: false
		}
	},
	computed: {
		modes() {
			return this.fresh ? ['builder', 'json'] : ['builder', 'json', 'versions']
		},
		ctx() {
			return contextOf(this.caps)
		},
		maxRules() {
			return this.limits.rules || 50
		},
		maxVersions() {
			return this.limits.versions || 5
		},
		users() {
			return (this.got && this.got.attached_to && this.got.attached_to.users) || []
		},
		groups() {
			return (this.got && this.got.attached_to && this.got.attached_to.groups) || []
		},
		attached() {
			return { users: this.users, groups: this.groups }
		},
		issues() {
			return checkDoc(this.draft, this.ctx)
		},
		// the mistakes about the whole document (the ones about a rule are drawn on that rule)
		topIssues() {
			return this.mode === 'builder' ? this.issues.filter(p => !p.rule) : this.issues
		},
		changed() {
			return this.fresh || !this.got || !sameDoc(this.draft, this.got.document)
		},
		warnings() {
			return (this.validation && this.validation.warnings) || []
		},
		risk4() {
			return this.warnings.some(w => w.code === 'risk4' || w.code === 'admin_like') || (this.dialogDiff && this.dialogDiff.highestRisk >= 4)
		},
		reviewable() {
			return canReview({ issues: this.issues, refused: !!this.refusal, validating: this.validating, valid: !!this.validation && this.validation.valid, changed: this.changed, damaged: this.damaged || this.readOnly, busy: this.busy }) && !this.jsonBad
		},
		verdict() {
			const t = k => this.$t('plugins.WorkshopService.access.' + k)
			if (this.jsonBad) return t('edit_json_blocks')
			if (this.issues.length) return ''
			if (this.refusal) return this.refusal
			if (this.validating || !this.validation) return t('edit_validating')
			return t(this.changed ? 'edit_valid' : 'edit_unchanged')
		},
		next() {
			return this.fresh ? { n: 1, drops: null } : nextVersion(this.versions, this.maxVersions)
		},
		shownDoc() {
			const v = this.versions.find(x => x.n === this.viewing)
			return v ? v.doc : this.draft
		},
		versionDoc() {
			const v = this.dialog && this.versions.find(x => x.n === this.dialog.n)
			return v ? v.doc : null
		},
		dialogDiff() {
			const d = this.dialog
			if (!d) return null
			const active = this.got ? this.got.document : null
			if (d.kind === 'save') return diffProfile(this.fresh ? null : active, this.draft, { riskOf: riskOf(this.ctx) })
			return diffProfile(active, this.versionDoc, { riskOf: riskOf(this.ctx) })
		},
		dialogTitle() {
			const d = this.dialog
			const name = this.draft.name
			if (!d) return ''
			if (d.kind === 'save') return this.$t('plugins.WorkshopService.access.diff_title', { name })
			if (d.kind === 'rollback') return this.$t('plugins.WorkshopService.access.versions_rollback_title', { n: d.n, name })
			return this.$t('plugins.WorkshopService.access.versions_compare_title', { n: d.n, m: this.got ? this.got.version : 0 })
		},
		dialogVerb() {
			const d = this.dialog
			if (!d) return ''
			return d.kind === 'save' ? this.$t('plugins.WorkshopService.access.diff_save', { n: this.next.n }) : this.$t('plugins.WorkshopService.access.versions_rollback_do', { n: d.n })
		}
	},
	watch: {
		draft() {
			this.onDraft()
		}
	},
	created() {
		this.narrow = isNarrowScreen()
		if (this.name) this.load()
		else {
			this.draft = this.seed ? cloneDoc(this.seed) : emptyDoc('')
			this.jsonDraft = jsonText(this.draft)
		}
	},
	beforeDestroy() {
		clearTimeout(this.timer)
	},
	methods: {
		async load() {
			this.state = 'loading'
			this.detail = ''
			try {
				this.take(await accessApi.profilesGet(this.name))
				this.versions = ((await accessApi.profileVersions(this.name)) || {}).versions || []
				this.draft = cloneDoc(this.got.document)
				this.jsonDraft = jsonText(this.draft)
				this.state = ''
			} catch (e) {
				this.got = null
				this.state = stateOfError(e)
				this.detail = (e && e.message) || ''
			}
		},
		take(answer) {
			this.got = answer
			this.openedVersion = answer.version
		},
		async reloadVersions() {
			this.versions = ((await accessApi.profileVersions(this.got.name)) || {}).versions || []
		},
		setName(v) {
			if (this.fresh) this.setDraft(Object.assign(cloneDoc(this.draft), { name: String(v || '') }))
		},
		setDraft(doc) {
			this.draft = doc
			this.savedNote = ''
			this.nameTaken = false
		},
		// every change of the document: the JSON text follows the Builder, the dry run runs after a short pause (and never with a mistake we know of)
		onDraft() {
			if (this.mode !== 'json') this.jsonDraft = jsonText(this.draft)
			clearTimeout(this.timer)
			this.validation = null
			this.refusal = ''
			if (this.issues.length || this.jsonBad) return
			this.validating = true
			this.timer = setTimeout(() => this.validateNow(), VALIDATE_MS)
		},
		async validateNow() {
			clearTimeout(this.timer)
			if (this.issues.length || this.jsonBad) return
			const mine = (this.seq = (this.seq || 0) + 1)
			this.validating = true
			try {
				const r = await accessApi.profilesValidate(this.draft)
				if (mine !== this.seq) return
				this.validation = r
				this.refusal = ''
			} catch (e) {
				if (mine !== this.seq) return
				this.validation = null
				this.refusal = (e && e.message) || String(e)
			} finally {
				if (mine === this.seq) this.validating = false
			}
		},
		goMode(m) {
			if (m === 'builder' && this.mode === 'json') {
				const p = parseJson(this.jsonDraft)
				if (!p.doc || !buildable(p.doc)) {
					this.jsonBad = true
					this.jsonLine = p.line || 1
					return
				}
				this.jsonBad = false
				this.jsonLine = 0
				if (!sameDoc(p.doc, this.draft)) this.draft = p.doc
			}
			this.mode = m
			if (m !== 'versions') this.viewing = 0
		},
		// text typed in the JSON editor: the document follows when it reads, and the dry run runs on it
		typed(text) {
			this.jsonDraft = text
			const p = parseJson(text)
			if (p.doc === undefined) {
				this.jsonBad = true
				this.jsonLine = p.line || 1
				clearTimeout(this.timer)
				this.validation = null
				return
			}
			this.jsonBad = false
			this.jsonLine = 0
			this.draft = p.doc
			this.savedNote = ''
		},
		format() {
			const p = parseJson(this.jsonDraft)
			if (p.doc !== undefined) this.jsonDraft = JSON.stringify(p.doc, null, 2)
		},
		openDialog(kind, n) {
			this.dialogError = ''
			this.dialog = { kind, n: n || 0 }
		},
		closeDialog() {
			if (!this.busy) this.dialog = null
		},
		// Another administrator may have changed the profile (or taken the name) since it was opened: read it again before the call; if the version moved the
		// document is reloaded, the draft is kept and the person is told. The service has no check of its own for this, so a very small window remains.
		async stillTheSame() {
			if (this.fresh) {
				try {
					await accessApi.profilesGet(this.draft.name)
				} catch (e) {
					if (e && e.code === 'unknown_profile') return true
					throw e
				}
				this.state = 'stale'
				this.nameTaken = true
				return false
			}
			const now = await accessApi.profilesGet(this.got.name)
			if (now.version === this.openedVersion) return true
			this.take(now)
			await this.reloadVersions()
			this.state = 'stale'
			return false
		},
		async confirm() {
			const d = this.dialog
			if (!d || this.busy) return
			this.busy = true
			this.dialogError = ''
			try {
				if (!(await this.stillTheSame())) {
					this.dialog = null
					return
				}
				this.state = ''
				const wasNew = this.fresh
				if (d.kind === 'save') this.take(await accessApi.profilesSet(this.draft, { confirm: true }))
				else this.take(await accessApi.profileRollback(this.got.name, d.n, { confirm: true }))
				this.fresh = false
				await this.reloadVersions()
				this.draft = cloneDoc(this.got.document)
				this.jsonDraft = jsonText(this.draft)
				this.jsonBad = false
				this.jsonLine = 0
				this.viewing = 0
				this.savedNote = this.$t('plugins.WorkshopService.access.' + (d.kind === 'save' ? 'diff_saved' : 'versions_rolled'), { n: this.got.version })
				this.dialog = null
				this.$emit('saved', { name: this.got.name, created: wasNew })
			} catch (e) {
				this.dialogError = (e && e.message) || String(e)
			} finally {
				this.busy = false
			}
		}
	}
}
</script>

<style>
.access-name-row { display: flex; align-items: center; gap: 4px; margin-bottom: 8px; }
.access-name-field { max-width: 420px; }
.access-warning { color: var(--v-warning-base, #f57c00); }
</style>
