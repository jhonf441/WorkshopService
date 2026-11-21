<template>
	<!-- Security > Report, read only (step 6 of DISENO-PANTALLAS): people and keys of access.report. One search for both tables, sorting on each, a panel with the
	     last use of each capability of a person and "Copy report" (on every screen). Events for the page that holds the
	     section:  @open-person="name"  @open-can="name"  @open-activity="name"  @open-key="{ id, name }"  @open-keys  (this screen never changes anything). -->
	<div ref="root" class="security-report">
		<v-card class="mb-3">
			<v-card-title class="text-subtitle-1">
				{{ $t('plugins.WorkshopService.access.report_title') }}
				<v-spacer />
				<v-btn small outlined class="access-touch security-copy" :disabled="!answer" @click="copy()"><v-icon left small>mdi-content-copy</v-icon>{{ copied ? $t('plugins.WorkshopService.access.common_copied') : $t('plugins.WorkshopService.access.report_copy') }}</v-btn>
				<v-btn small outlined class="access-touch ml-2" :loading="loading" @click="load()"><v-icon left small>mdi-refresh</v-icon>{{ $t('plugins.WorkshopService.access.common_refresh') }}</v-btn>
			</v-card-title>
			<v-card-text>
				<access-state :state="state" :detail="detail" @retry="load()">
					<template v-if="answer">
						<div v-if="answer.damaged" class="wf-note is-warn mb-2" role="note"><v-icon class="wf-note-icon" aria-hidden="true">mdi-alert-outline</v-icon><span>{{ $t('plugins.WorkshopService.access.report_damaged') }}</span></div>
						<security-person-drawer v-if="person" :key="person.name" :person="person" :now="now" @back="selected = ''" @see-access="$emit('open-person', $event)" @see-can="$emit('open-can', $event)" @see-activity="$emit('open-activity', $event)" />
						<template v-else>
							<div class="wf-help mb-3">{{ $t('plugins.WorkshopService.access.report_summary', { locked: summary.locked, never: summary.never, keys: summary.unusedKeys, expired: summary.expiredKeys }) }}</div>
							<sv-text-field v-model="text" icon="mdi-magnify" type="search" class="access-search mb-4" :placeholder="$t('plugins.WorkshopService.access.common_search')" :aria-label="$t('plugins.WorkshopService.access.common_search')" />
							<sv-table-block :title="$t('plugins.WorkshopService.access.report_people_title')">
								<security-people-table :rows="people" :now="now" :sort="peopleSort" @sort="peopleSort = $event" @open="selected = $event" />
							</sv-table-block>
							<sv-table-block :title="$t('plugins.WorkshopService.access.report_keys_title')">
								<security-keys-summary :overview="keysView" @open="$emit('open-key', $event)" @open-all="$emit('open-keys')" />
							</sv-table-block>
							<div class="wf-help mt-2">{{ $t('plugins.WorkshopService.access.report_delay') }}</div>
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
import SvTableBlock from './ui/SvTableBlock.vue'
import AccessState from './AccessState.vue'
import SecurityPeopleTable from './SecurityPeopleTable.vue'
import SecurityKeysSummary from './SecurityKeysSummary.vue'
import SecurityPersonDrawer from './SecurityPersonDrawer.vue'
import { securityApi } from './access-security-api.js'
import { keysOverview, peopleRows, reportText, summaryOf } from './access-report-view.js'
import { stateOfError } from './access-profile-view.js'
import { copyText } from './copy.js'

const SLOW_MS = 15000

export default {
	components: { SvTextField, SvTableBlock, AccessState, SecurityPeopleTable, SecurityKeysSummary, SecurityPersonDrawer },
	data() {
		return { answer: null, text: '', selected: '', peopleSort: { field: 'name', dir: 'asc' }, copied: false, loading: false, failed: '', failure: null, slow: false }
	},
	computed: {
		now() {
			return (this.answer && this.answer.generated) | 0
		},
		people() {
			return peopleRows(this.answer, this.text, this.peopleSort)
		},
		// counts and exceptions of the keys (the whole list is in Access > Keys); the search filters the people, not the counts
		keysView() {
			return keysOverview(this.answer)
		},
		summary() {
			return summaryOf(this.answer)
		},
		person() {
			return this.selected ? peopleRows(this.answer, '', null).find((p) => p.name === this.selected) || null : null
		},
		// one state at a time, the first that applies (section 5); a damaged access file is a note beside the report, which does not depend on the profiles
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
				this.answer = await securityApi.report()
			} catch (e) {
				this.answer = null
				this.failure = e
				this.failed = stateOfError(e)
			} finally {
				this.loading = false
				clearTimeout(this.timer)
			}
		},
		async copy() {
			if (!this.answer) return
			const t = (k, p, count) => {
				const full = k.startsWith('users.') ? 'plugins.WorkshopService.' + k : 'plugins.WorkshopService.access.' + k
				return count === undefined ? this.$t(full, p) : this.$tc(full, count, p)
			}
			this.copied = await copyText(reportText(this.answer, t), this.$refs.root)
			setTimeout(() => { this.copied = false }, 2000)
		}
	}
}
</script>

<style>
</style>
