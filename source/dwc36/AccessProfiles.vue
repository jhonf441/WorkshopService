<template>
	<!-- Access > Profiles, read only (step 1 of DISENO-PANTALLAS): the list, one profile (builder, JSON, versions), the states of section 5 and the fixed note about
	     G-code. Operations: access.profiles.list / get and access.profile.versions through access-api.js; the capabilities come from roles.list. -->
	<div class="access-profiles">
		<v-card class="mb-3">
			<v-card-title class="text-subtitle-1">
				{{ $t('plugins.WorkshopService.access.profiles_title') }}<access-term-help term="profile" />
				<v-spacer />
				<v-btn v-if="canEdit && list && !selected && !draft" small color="primary" class="access-touch mr-2" :disabled="!!list.damaged" @click="start(null)"><v-icon left small>mdi-plus</v-icon>{{ $t('plugins.WorkshopService.access.profiles_new') }}</v-btn>
				<v-btn small outlined class="access-touch" :loading="loading" @click="load()"><v-icon left small>mdi-refresh</v-icon>{{ $t('plugins.WorkshopService.access.common_refresh') }}</v-btn>
			</v-card-title>
			<v-card-text>
				<div class="wf-note mb-2" role="note"><v-icon class="wf-note-icon" aria-hidden="true">mdi-information-outline</v-icon><span>{{ $t('plugins.WorkshopService.access.profiles_gcode_note') }}</span></div>
				<span class="sv-vh" role="status" aria-live="polite" data-part="said">{{ said }}</span>
				<access-state :state="state" :detail="detail" @retry="load()">
					<div v-if="list" ref="work">
						<access-profile-editor v-if="draft" :key="'e:' + draft.name + draft.n" :name="draft.name" :seed="draft.seed" :caps="capsAnswer" :limits="limits" :damaged="!!list.damaged" @back="stop()" @saved="saved" />
						<access-profile-editor v-else-if="selected && !selected.base && canEdit" :key="'o:' + selected.name" :name="selected.name" :caps="capsAnswer" :limits="limits" :damaged="!!list.damaged" @back="stop()" @saved="saved" />
						<access-profile-view v-else-if="selected" :key="selected.name" :name="selected.name" :base="selected.base" :editable="canEdit && !list.damaged" :capabilities="capabilities" :categories="categories" :max-rules="limits.rules" :max-versions="limits.versions" @back="selected = null" @duplicate="doc => start(duplicateDoc(doc, context))" />
						<access-profile-list v-else :list="list" :editable="canEdit" @open="selected = $event" @removed="load()" />
					</div>
				</access-state>
			</v-card-text>
		</v-card>
	</div>
</template>

<script>
'use strict'

import AccessState from './AccessState.vue'
import AccessTermHelp from './AccessTermHelp.vue'
import AccessProfileList from './AccessProfileList.vue'
import AccessProfileView from './AccessProfileView.vue'
import AccessProfileEditor from './AccessProfileEditor.vue'
import { roleMixin } from './role-mixin.js'
import { revealMixin } from './reveal-mixin.js'
import { confirmLeave } from './ui/unsaved-guard.js'
import { accessApi } from './access-api.js'
import { stateOfError } from './access-profile-view.js'
import { contextOf, duplicateDoc } from './access-profile-edit.js'
import { profileFocus } from './access-go.js'

const SLOW_MS = 15000

export default {
	components: { AccessTermHelp, AccessState, AccessProfileList, AccessProfileView, AccessProfileEditor },
	mixins: [roleMixin, revealMixin],
	props: { focus: { type: Object, default: null } }, // { name, n }: open this profile (asked from Security); n changes with every request
	data() {
		return { focused: 0, list: null, capabilities: [], categories: [], capsAnswer: {}, loading: false, failed: '', failure: null, slow: false, selected: null, draft: null, drafts: 0 }
	},
	computed: {
		limits() {
			return Object.assign({ rules: 50, versions: 5 }, (this.list && this.list.limits) || {})
		},
		// the session may change profiles (the table of the service decides; an administrator always may) and the service gave the lists the builder is made
		// of (capabilities, stops, what cannot be granted): without them nothing is offered to edit, the profiles stay readable
		canEdit() {
			return this.canDo('access.profiles.set') && this.capabilities.length > 0
		},
		context() {
			return contextOf(this.capsAnswer)
		},
		empty() {
			return !!this.list && !(this.list.profiles || []).length && !(this.list.base || []).length
		},
		// one state at a time, the first that applies (section 5): the cover and the failures before the notes
		state() {
			if (this.failed) return this.failed
			if (this.loading && !this.list) return this.slow ? 'slow' : 'loading'
			if (this.list && this.list.damaged) return 'damaged'
			if (this.empty) return 'empty'
			if (this.list && !this.canDo('access.profiles.set')) return 'read_only'
			return ''
		},
		detail() {
			return this.failure ? this.failure.message || '' : ''
		},
		damaged() {
			return this.list ? !!this.list.damaged : null
		}
	},
	watch: {
		'focus.n'() {
			this.applyFocus()
		},
		// the editor or the profile opens in the place of the list, which may be far from the button that asked: bring it into view (reveal.js)
		draft(v) { if (v) this.shown(this.$t('plugins.WorkshopService.access.profiles_opened_new')) },
		selected(v) { if (v) this.shown(this.$t('plugins.WorkshopService.access.profiles_opened', { name: v.name })) },
		// the list tells by itself that the access file is damaged: the page shows it in its header
		damaged(v) { if (v !== null) this.$emit('damaged', v) }
	},
	created() {
		this.load()
	},
	beforeDestroy() {
		clearTimeout(this.timer)
	},
	methods: {
		duplicateDoc,
		// the profile a button of Security named: shown once per request, when the list is there
		applyFocus() {
			if (!this.list || !this.focus || !this.focus.n || this.focused === this.focus.n) return
			this.focused = this.focus.n
			const hit = profileFocus(this.list, this.focus.name)
			if (!hit) return
			// a request from Security replaces the editor that is open: unsaved changes ask first (unsaved-guard.js)
			confirmLeave(() => {
				this.draft = null
				this.selected = hit
			})
		},
		shown(said) {
			this.$nextTick(() => this.showResult(this.$refs.work, { focus: true, said }))
		},
		// a new profile (empty, or the copy of a base one): the editor opens on it
		start(seed) {
			this.drafts++
			this.selected = null
			this.draft = { name: '', seed, n: this.drafts }
		},
		stop() {
			this.draft = null
			this.selected = null
			this.load()
		},
		// a save: the list is read again in the background so that the next time it is shown it is right
		saved() {
			accessApi.profilesList().then(l => { this.list = l }, () => {})
		},
		async load() {
			this.loading = true
			this.slow = false
			this.failed = ''
			this.failure = null
			clearTimeout(this.timer)
			this.timer = setTimeout(() => { this.slow = true }, SLOW_MS)
			try {
				this.list = await accessApi.profilesList()
				// the capabilities (category, class, risk, lock) are the service's: a failure here leaves the rules readable without the table
				const caps = await accessApi.capabilities().catch(() => null)
				this.capsAnswer = caps || {}
				this.capabilities = (caps && caps.capabilities) || []
				this.categories = (caps && caps.categories) || []
				this.applyFocus()
			} catch (e) {
				this.list = null
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
