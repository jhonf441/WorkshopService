<template>
	<!-- Access > Keys: THE card of the keys of the external services (a key is the access of a PROGRAM, not of a person, and never administers). One list for
	     everything: what each key can do, its state, last use, expiry, and the actions (new, open, edit, switch, delete). Operations: keys.list, access.report and
	     access.review, all through access-api.js; the changes (create, update, switch, delete) are made by ApiKeyEditor, which owns the key shown once. When
	     access.report or access.review cannot be read the keys are still listed and the card says it marked nothing. After any change the list is read again. -->
	<div class="access-keys">
		<v-card class="mb-3">
			<v-card-title class="text-subtitle-1">
				<v-icon small class="mr-2 svx-ico">mdi-key-chain</v-icon>{{ $t('plugins.WorkshopService.access.keys_title') }}<access-term-help term="key" />
				<v-spacer />
				<v-btn small outlined class="access-touch mr-2" :loading="loading" @click="load()"><v-icon left small>mdi-refresh</v-icon>{{ $t('plugins.WorkshopService.access.common_refresh') }}</v-btn>
				<v-btn small color="primary" class="access-touch" :disabled="!canChange" @click="$refs.editor.openNew()"><v-icon left small>mdi-plus</v-icon>{{ $t('plugins.WorkshopService.keys.new_key') }}</v-btn>
			</v-card-title>
			<v-card-text>
				<help-guide class="mb-3" :what="$t('plugins.WorkshopService.access.keys_what')" :how="$t('plugins.WorkshopService.keys.how_to_use')" />
				<lock-reason v-if="answer && !canChange" :ops="['keys.create', 'keys.update', 'keys.revoke']" class="mb-2" />
				<error-notice :error="actionError" class="mb-2" />
				<access-state :state="state" :detail="detail" @retry="load()">
					<template v-if="answer">
						<div v-if="partial" class="wf-note is-warn mb-2" role="note"><v-icon class="wf-note-icon" aria-hidden="true">mdi-alert-outline</v-icon><span>{{ $t('plugins.WorkshopService.access.keys_partial') }}</span></div>
						<access-key-card v-if="selected" :key="selected" :row="selectedRow" :now="now" :can-change="canChange" @back="selected = ''" @edit="edit" @toggle="toggle" @remove="remove" />
						<template v-else>
							<div class="sv-tbar">
								<sv-text-field v-model="text" icon="mdi-magnify" type="search" class="access-search" :placeholder="$t('plugins.WorkshopService.access.common_search')" :aria-label="$t('plugins.WorkshopService.access.common_search')" />
							</div>
							<access-key-list :rows="rows" :now="now" :total="total" :can-change="canChange" @open="selected = $event" @edit="edit" @toggle="toggle" @remove="remove" />
						</template>
					</template>
				</access-state>
			</v-card-text>
		</v-card>
		<api-key-editor ref="editor" :operations="operations" :presets="presets" @changed="load()" @failed="e => { actionError = e }" />
	</div>
</template>

<script>
'use strict'

import SvTextField from './ui/SvTextField.vue'
import AccessState from './AccessState.vue'
import AccessTermHelp from './AccessTermHelp.vue'
import AccessKeyList from './AccessKeyList.vue'
import AccessKeyCard from './AccessKeyCard.vue'
import ApiKeyEditor from './ApiKeyEditor.vue'
import ErrorNotice from './ErrorNotice.vue'
import LockReason from './LockReason.vue'
import HelpGuide from './HelpGuide.vue'
import { accessCanMixin } from './reason-mixin.js'
import { accessApi } from './access-api.js'
import { keyRows } from './access-keys-view.js'
import { keyFocus } from './access-go.js'
import { stateOfError } from './access-profile-view.js'

const SLOW_MS = 15000

export default {
	components: { SvTextField, AccessTermHelp, AccessState, AccessKeyList, AccessKeyCard, ApiKeyEditor, ErrorNotice, LockReason, HelpGuide },
	mixins: [accessCanMixin],
	// the keys, the report and the review come from the person who left: emptied on sign-out and change of role (ESTANDAR 3.3)
	sessionData: ['answer', 'report', 'review', 'selected', 'text', 'actionError'],
	// focus { id, n }: open this key (asked from Security); operations: api.describe, for the operation pickers of the dialog
	props: { nowSeconds: { type: Number, default: 0 }, focus: { type: Object, default: null }, operations: { type: Array, default: () => [] } },
	data() {
		return { focused: 0, actionError: null, answer: null, report: null, review: null, partial: false, text: '', selected: '', loading: false, failed: '', failure: null, slow: false }
	},
	computed: {
		now() {
			return this.nowSeconds || Math.floor(Date.now() / 1000)
		},
		rows() {
			return keyRows(this.answer, this.report, this.review, this.text, this.now)
		},
		presets() {
			return (this.answer && this.answer.presets) || {}
		},
		// the switch, the pencil and the bin: only for a role that may change keys (the lock reason says why not)
		canChange() {
			return this.canDo('keys.update') && this.canDo('keys.revoke')
		},
		total() {
			return this.answer && Array.isArray(this.answer.keys) ? this.answer.keys.length : 0
		},
		selectedRow() {
			return keyRows(this.answer, this.report, this.review, '', this.now).find(r => r.id === this.selected) || null
		},
		// one state at a time, the first that applies (section 5); a damaged access file does not hide the keys, which keep their own format
		state() {
			if (this.failed) return this.failed
			if (this.loading && !this.answer) return this.slow ? 'slow' : 'loading'
			const damaged = (this.review && this.review.damaged) || (this.report && this.report.damaged)
			if (this.answer && damaged) return 'damaged'
			return ''
		},
		detail() {
			return this.failure ? this.failure.message || '' : ''
		}
	},
	watch: {
		'focus.n'() {
			this.applyFocus()
		}
	},
	created() {
		this.load()
	},
	beforeDestroy() {
		clearTimeout(this.timer)
	},
	methods: {
		// another person: the lists are read again for the new identity (a sign-out only empties them)
		onSessionChange(kind) {
			if (kind !== 'signed-out') this.load()
		},
		// the key a button of Security named: shown once per request, when the list is there
		applyFocus() {
			if (!this.answer || !this.focus || !this.focus.n || this.focused === this.focus.n) return
			this.focused = this.focus.n
			const id = keyFocus(this.answer.keys, this.focus.id)
			if (id) this.selected = id
		},
		edit(row) {
			this.$refs.editor.openEdit(row.raw)
		},
		toggle(e) {
			this.actionError = null
			this.$refs.editor.toggle(e.row, e.on)
		},
		remove(row) {
			this.actionError = null
			this.$refs.editor.remove(row)
		},
		async load() {
			this.loading = true
			this.slow = false
			this.failed = ''
			this.failure = null
			clearTimeout(this.timer)
			this.timer = setTimeout(() => { this.slow = true }, SLOW_MS)
			try {
				this.answer = await accessApi.keysList()
				// the last use and the review are extra: when one cannot be read the keys are still shown and the screen says it did not mark anything
				const [report, review] = await Promise.all([accessApi.report().catch(() => null), accessApi.review().catch(() => null)])
				this.report = report
				this.review = review
				this.partial = !report || !review
				if (this.selected && !this.rows.some(r => r.id === this.selected)) this.selected = ''
				this.applyFocus()
			} catch (e) {
				this.answer = null
				this.failure = e
				this.failed = stateOfError(e)
			} finally {
				this.loading = false
				clearTimeout(this.timer)
			}
		}
	}
}
</script>
