<template>
	<!-- Access > Keys, read only (step 7 of DISENO-PANTALLAS): the keys of the external services with what each reaches, its last use and, only when the review
	     of accesses says so, the mark of a wide key that is not used. Operations: keys.list, access.report and access.review, all through access-api.js.
	     Keys are created, changed and revoked in the card above it (ApiKeys, same tab). Nothing here changes a key. -->
	<div class="access-keys">
		<v-card class="mb-3">
			<v-card-title class="text-subtitle-1">
				{{ $t('plugins.WorkshopService.access.keys_title') }}<access-term-help term="key" />
				<v-spacer />
				<v-btn small outlined class="access-touch mr-2" :loading="loading" @click="load()"><v-icon left small>mdi-refresh</v-icon>{{ $t('plugins.WorkshopService.access.common_refresh') }}</v-btn>
			</v-card-title>
			<v-card-text>
				<access-state :state="state" :detail="detail" @retry="load()">
					<template v-if="answer">
						<div v-if="partial" class="wf-note is-warn mb-2" role="note"><v-icon class="wf-note-icon" aria-hidden="true">mdi-alert-outline</v-icon><span>{{ $t('plugins.WorkshopService.access.keys_partial') }}</span></div>
						<access-key-card v-if="selected" :key="selected" :row="selectedRow" :now="now" @back="selected = ''" />
						<template v-else>
							<div class="access-filters">
								<sv-text-field v-model="text" icon="mdi-magnify" type="search" class="access-search" :placeholder="$t('plugins.WorkshopService.access.common_search')" :aria-label="$t('plugins.WorkshopService.access.common_search')" />
							</div>
							<access-key-list :rows="rows" :now="now" :total="total" @open="selected = $event" />
							<div class="wf-help mt-2">{{ $t('plugins.WorkshopService.access.keys_dates_note') }}</div>
						</template>
					</template>
				</access-state>
			</v-card-text>
		</v-card>
	</div>
</template>

<script>
'use strict'

import SvTextField from './ui/SvTextField.vue'
import AccessState from './AccessState.vue'
import AccessTermHelp from './AccessTermHelp.vue'
import AccessKeyList from './AccessKeyList.vue'
import AccessKeyCard from './AccessKeyCard.vue'
import { accessCanMixin } from './reason-mixin.js'
import { accessApi } from './access-api.js'
import { keyRows } from './access-keys-view.js'
import { keyFocus } from './access-go.js'
import { stateOfError } from './access-profile-view.js'

const SLOW_MS = 15000

export default {
	components: { SvTextField, AccessTermHelp, AccessState, AccessKeyList, AccessKeyCard },
	mixins: [accessCanMixin],
	props: { nowSeconds: { type: Number, default: 0 }, focus: { type: Object, default: null } }, // focus { id, n }: open this key (asked from Security)
	data() {
		return { focused: 0, answer: null, report: null, review: null, partial: false, text: '', selected: '', loading: false, failed: '', failure: null, slow: false }
	},
	computed: {
		now() {
			return this.nowSeconds || Math.floor(Date.now() / 1000)
		},
		rows() {
			return keyRows(this.answer, this.report, this.review, this.text)
		},
		total() {
			return this.answer && Array.isArray(this.answer.keys) ? this.answer.keys.length : 0
		},
		selectedRow() {
			return keyRows(this.answer, this.report, this.review, '').find(r => r.id === this.selected) || null
		},
		// one state at a time, the first that applies (section 5); a damaged access file does not hide the keys, which keep their own format
		state() {
			if (this.failed) return this.failed
			if (this.loading && !this.answer) return this.slow ? 'slow' : 'loading'
			const damaged = (this.review && this.review.damaged) || (this.report && this.report.damaged)
			if (this.answer && damaged) return 'damaged'
			if (this.answer && !this.canDo('keys.update')) return 'read_only'
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
		// the key a button of Security named: shown once per request, when the list is there
		applyFocus() {
			if (!this.answer || !this.focus || !this.focus.n || this.focused === this.focus.n) return
			this.focused = this.focus.n
			const id = keyFocus(this.answer.keys, this.focus.id)
			if (id) this.selected = id
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
