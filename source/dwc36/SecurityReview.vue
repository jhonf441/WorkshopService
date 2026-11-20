<template>
	<!-- Security > Review, read only (step 6 of DISENO-PANTALLAS): the findings of access.review, as the service sorted and worded them, each with a button that
	     asks the page to open the object it names. This container only reads (access.review) and says what to open through events:
	       @open-profile="name"   @open-person="name"   @open-key="{ id, name }"
	     The container that holds the section decides where each one goes. -->
	<div class="security-review">
		<v-card class="mb-3">
			<v-card-title class="text-subtitle-1">
				{{ $t('plugins.WorkshopService.access.review_title') }}
				<v-spacer />
				<v-btn small outlined class="access-touch" :loading="loading" @click="load()"><v-icon left small>mdi-refresh</v-icon>{{ $t('plugins.WorkshopService.access.review_run') }}</v-btn>
			</v-card-title>
			<v-card-text>
				<access-state :state="state" :detail="detail" @retry="load()">
					<template v-if="answer">
						<security-review-summary :answer="answer" />
						<div v-if="answer.damaged" class="wf-note is-warn mb-2" role="note"><v-icon class="wf-note-icon" aria-hidden="true">mdi-alert-outline</v-icon><span>{{ $t('plugins.WorkshopService.access.review_damaged') }}</span></div>
						<div v-if="!rows.length" class="wf-help access-own-empty">{{ $t('plugins.WorkshopService.access.review_none') }}</div>
						<security-finding-list v-else :rows="rows" @open="open" />
						<div class="wf-help mt-2">{{ $t('plugins.WorkshopService.access.review_live_note') }}</div>
					</template>
				</access-state>
			</v-card-text>
		</v-card>
	</div>
</template>

<script>
'use strict'

import AccessState from './AccessState.vue'
import SecurityReviewSummary from './SecurityReviewSummary.vue'
import SecurityFindingList from './SecurityFindingList.vue'
import { securityApi } from './access-security-api.js'
import { findingRows } from './access-review-view.js'
import { stateOfError } from './access-profile-view.js'

const SLOW_MS = 15000

export default {
	components: { AccessState, SecurityReviewSummary, SecurityFindingList },
	data() {
		return { answer: null, loading: false, failed: '', failure: null, slow: false }
	},
	computed: {
		rows() {
			return findingRows(this.answer)
		},
		// one state at a time, the first that applies (section 5). A damaged access file is a note beside the findings (it omits the ones that depend on profiles),
		// not a reason to hide what the service could review.
		state() {
			if (this.failed) return this.failed
			if (this.loading && !this.answer) return this.slow ? 'slow' : 'loading'
			return ''
		},
		detail() {
			return this.failure ? this.failure.message || '' : ''
		},
		damaged() {
			return this.answer ? !!this.answer.damaged : null
		}
	},
	watch: {
		// the answer tells by itself that the access file is damaged: the page shows it in its header
		damaged(v) { if (v !== null) this.$emit('damaged', v) }
	},
	created() {
		this.load()
	},
	beforeDestroy() {
		clearTimeout(this.timer)
	},
	methods: {
		async load() {
			this.loading = true
			this.slow = false
			this.failed = ''
			this.failure = null
			clearTimeout(this.timer)
			this.timer = setTimeout(() => { this.slow = true }, SLOW_MS)
			try {
				this.answer = await securityApi.review()
			} catch (e) {
				this.answer = null
				this.failure = e
				this.failed = stateOfError(e)
			} finally {
				this.loading = false
				clearTimeout(this.timer)
			}
		},
		open(target) {
			if (target.kind === 'profile') this.$emit('open-profile', target.name)
			else if (target.kind === 'person') this.$emit('open-person', target.name)
			else if (target.kind === 'key') this.$emit('open-key', { id: target.id, name: target.name })
		}
	}
}
</script>
