<template>
	<!-- A zone that paints the state of what it shows: no screen writes its own "loading" or "no data".
	     Props:
	       status   of the resource: 'idle' | 'loading' | 'ready' | 'refreshing' | 'empty' | 'stale' | 'locked' | 'error'
	       error    its ServiceError ({ message, code, kind }) ; lock: { state: 'session' | 'role', text, help (one more line), neededRole, title (instead of the standard one), fixed (kept for old callers: a cover never has a button now) }
	       updated  the text of when it was read ("13:40"), for asked data ; staleText: "Data from 3 min ago"
	       emptyTitle / emptyText   what "nothing yet" means here
	       refreshable   show Refresh next to the time
	     Slots: default (the content), empty (the action to create the first one), skeleton (bars with the shape of the content).
	     Events: retry / refresh, sign-in.
	     A failed refresh keeps the content and says so next to the time. -->
	<div class="sv-zone-host" :aria-busy="status === 'loading' ? 'true' : null">
		<div v-if="status === 'loading' || status === 'idle'" class="sv-skel sv-skel-late" role="status" :aria-label="kt('loading')">
			<slot name="skeleton"><i /><i /><i /><i /></slot>
		</div>
		<div v-else-if="status === 'locked' && lock" class="sv-zone" :data-state="lock.state">
			<span class="mdi sv-ico sv-ico-l" :class="lock.state === 'session' ? 'mdi-account-circle-outline' : 'mdi-lock-outline'" aria-hidden="true" />
			<h2>{{ lock.title || (lock.state === 'session' ? kt('no_session') : kt('needs_role', { role: lock.neededRole })) }}</h2>
			<p>{{ lock.text }}</p>
			<p v-if="lock.help" class="sv-quiet" data-part="lock-help">{{ lock.help }}</p>
		</div>
		<div v-else-if="status === 'error'" class="sv-zone" :data-state="busy ? 'busy' : 'error'" role="alert">
			<span class="mdi sv-ico sv-ico-l" :class="busy ? 'mdi-alert-outline' : 'mdi-close-circle-outline'" aria-hidden="true" />
			<h2>{{ busy ? kt('busy') : kt('read_failed') }}</h2>
			<p>{{ error && error.message }}</p>
			<code v-if="error && error.code">{{ error.code }}</code>
			<button type="button" class="sv-btn" @click="$emit('retry')">{{ kt('retry') }}</button>
		</div>
		<div v-else-if="status === 'empty'" class="sv-zone" data-state="empty">
			<span class="mdi mdi-information-outline sv-ico sv-ico-l" aria-hidden="true" />
			<h2>{{ emptyTitle }}</h2>
			<p v-if="emptyText">{{ emptyText }}</p>
			<slot name="empty" />
		</div>
		<template v-else>
			<div v-if="status === 'stale'" class="sv-stale-mark"><span class="mdi mdi-clock-alert-outline sv-ico sv-ico-s" aria-hidden="true" />{{ staleText || kt('stale') }}</div>
			<div v-if="updated || status === 'refreshing' || failedRefresh" class="sv-zone-meta">
				<span v-if="status === 'refreshing'" class="sv-vh" role="status">{{ kt('refreshing') }}</span>
				<span v-if="updated" class="sv-age"><span class="mdi mdi-clock-outline sv-ico sv-ico-s" aria-hidden="true" />{{ kt('updated_at', { time: updated }) }}</span>
				<span v-if="failedRefresh" class="sv-age" data-old role="status">{{ kt('read_failed') }} {{ error.message }}</span>
				<button v-if="refreshable" type="button" class="sv-btn sv-text" :disabled="busyHeld" :aria-busy="busyHeld ? 'true' : null" @click="$emit('refresh')"><span class="mdi mdi-refresh sv-ico sv-ico-s" aria-hidden="true" /><span class="sv-btn-stack"><span>{{ kt('refresh') }}</span></span></button>
			</div>
			<div :class="{ 'sv-stale': status === 'stale' }"><slot /></div>
		</template>
	</div>
</template>

<script>
import { svTextMixin } from './sv-text.js'
import { svBusyMixin } from './sv-busy.js'

export default {
	name: 'SvZone',
	mixins: [svTextMixin, svBusyMixin],
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
		busy() {
			return !!this.error && this.error.code === 'busy'
		},
		// the content is on screen and the last read failed
		failedRefresh() {
			return !!this.error && (this.status === 'ready' || this.status === 'stale')
		}
	}
}
</script>
