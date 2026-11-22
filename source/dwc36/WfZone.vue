<template>
	<!-- A zone that paints the state of what it shows: no screen writes its own "loading" or "no data" (FASE2, promoted from the service SvZone, drawn with the
	     classes of the family: wf-cover for what replaces the content, wf-note for the stale mark). Never taller than a card: covers are 96 px inside a card.
	       status   'idle' | 'loading' | 'ready' | 'refreshing' | 'empty' | 'stale' | 'locked' | 'error'
	       error    { message, code }          lock  { state: 'session' | 'role', text, title, neededRole }  (status 'locked' without lock = the generic role cover)
	       updated  when it was read ("13:40") for asked data          staleText  "Data from 3 min ago"
	       emptyTitle / emptyText  what "nothing yet" means here      refreshable  Refresh next to the time
	     Slots: default (the content), empty (the action that creates the first one), skeleton (bars with the shape of the content).
	     Events: retry, refresh. A failed refresh keeps the content and says so next to the time. -->
	<div class="wf-zone" :data-status="status" :aria-busy="status === 'loading' ? 'true' : null">
		<div v-if="status === 'loading' || status === 'idle'" class="wf-skel" role="status" :aria-label="ts('wf_loading')">
			<slot name="skeleton"><i /><i /><i /><i /></slot>
		</div>
		<div v-else-if="status === 'locked'" class="wf-cover" :class="'wf-cover--' + lockInfo.state" role="status">
			<span class="mdi wf-cover-icon" :class="lockInfo.state === 'session' ? 'mdi-account-circle-outline' : 'mdi-lock-outline'" aria-hidden="true" />
			<div class="wf-cover-title">{{ lockInfo.title || (lockInfo.state === 'session' ? ts('wf_no_session') : lockInfo.neededRole ? ts('wf_needs_role', { role: lockInfo.neededRole }) : ts('wf_refusal_default')) }}</div>
			<div v-if="lockInfo.text" class="wf-cover-text">{{ lockInfo.text }}</div>
		</div>
		<div v-else-if="status === 'error'" class="wf-cover" :class="busy ? 'wf-cover--down' : 'wf-cover--error'" role="alert">
			<span class="mdi wf-cover-icon" :class="busy ? 'mdi-alert-outline' : 'mdi-close-circle-outline'" aria-hidden="true" />
			<div class="wf-cover-title">{{ busy ? ts('wf_busy') : ts('wf_read_failed') }}</div>
			<div v-if="error && error.message" class="wf-cover-text">{{ error.message }}</div>
			<code v-if="error && error.code" class="wf-result-code">{{ error.code }}</code>
			<button type="button" class="wf-btn wf-main" @click="$emit('retry')">{{ ts('wf_retry') }}</button>
		</div>
		<div v-else-if="status === 'empty'" class="wf-cover wf-cover--empty" role="status">
			<span class="mdi mdi-information-outline wf-cover-icon" aria-hidden="true" />
			<div class="wf-cover-title">{{ emptyTitle }}</div>
			<div v-if="emptyText" class="wf-cover-text">{{ emptyText }}</div>
			<slot name="empty" />
		</div>
		<template v-else>
			<div v-if="updated || status === 'refreshing' || failedRefresh || status === 'stale' || refreshable" class="wf-zone-meta">
				<span v-if="status === 'stale'" class="wf-zone-stale"><span class="mdi mdi-clock-alert-outline wf-zone-ico" aria-hidden="true" />{{ staleText || ts('wf_stale') }}</span>
				<span v-if="status === 'refreshing'" class="wf-vh" role="status">{{ ts('wf_refreshing') }}</span>
				<span v-if="updated" class="wf-zone-age"><span class="mdi mdi-clock-outline wf-zone-ico" aria-hidden="true" />{{ ts('wf_updated_at', { time: updated }) }}</span>
				<span v-if="failedRefresh" class="wf-zone-age is-old" role="status">{{ ts('wf_read_failed') }} {{ error.message }}</span>
				<button v-if="refreshable" type="button" class="wf-btn wf-zone-refresh" :disabled="busyHeld" :aria-busy="busyHeld ? 'true' : null" @click="$emit('refresh')"><span class="mdi mdi-refresh wf-zone-ico" aria-hidden="true" /><span class="wf-act-stack" :data-alt="ts('wf_refresh')">{{ ts('wf_refresh') }}</span></button>
			</div>
			<div :class="{ 'is-stale': status === 'stale' }"><slot /></div>
		</template>
	</div>
</template>

<script>
import { ts } from './shared-t.js'
import { wfBusyMixin } from './wf-busy.js'

export default {
	name: 'WfZone',
	mixins: [wfBusyMixin],
	props: {
		status: { type: String, default: 'idle' },
		error: { type: Object, default: null },
		lock: { type: Object, default: null },
		updated: { type: String, default: '' },
		staleText: { type: String, default: '' },
		emptyTitle: { type: String, default: '' },
		emptyText: { type: String, default: '' },
		refreshable: { type: Boolean, default: false }
	},
	computed: {
		busyNow() {
			return this.status === 'refreshing'
		},
		// a locked zone always says so: without a reason from the page it is the generic role cover (never the content, never nothing)
		lockInfo() {
			return this.lock || { state: 'role', neededRole: '' }
		},
		busy() {
			return !!this.error && this.error.code === 'busy'
		},
		// the content is on screen and the last read failed
		failedRefresh() {
			return !!this.error && (this.status === 'ready' || this.status === 'stale')
		}
	},
	methods: { ts }
}
</script>
