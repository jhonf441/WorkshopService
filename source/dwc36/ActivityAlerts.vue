<template>
	<!-- The recent alarms of the service (damaged access file, burst of refusals, sensitive change, broken chain). The service logs each one as an event of the
	     type security_alarm in the Activity history, so they are read with activity.list and that type. Changing `tick` reads them again.
	       <activity-alerts :tick="n" /> -->
	<div class="activity-alerts">
		<div class="activity-alerts-head">
			<strong>{{ $t('plugins.WorkshopService.access.audit_alerts', { n: total }) }}</strong>
			<span class="text-caption">{{ $tc('plugins.WorkshopService.access.audit_alerts_range', days, { days: days }) }}</span>
		</div>
		<p class="wf-help mb-1" data-part="alerts-help">{{ $t('plugins.WorkshopService.access.audit_alerts_help') }}</p>
		<div v-if="failure" class="wf-help" role="note">{{ $t('plugins.WorkshopService.access.audit_alerts_error', { detail: failure }) }}</div>
		<div v-else-if="!rows.length && !loading" class="wf-help">{{ $t('plugins.WorkshopService.access.audit_alerts_none') }}</div>
		<ul v-else class="activity-alert-list">
			<li v-for="a in rows" :key="a.id" class="activity-alert"><v-icon small color="warning">mdi-alert-outline</v-icon><span class="text-caption">{{ a.ts }}</span> {{ a.text }}
				<button v-if="a.minute" type="button" class="wf-btn sv-btn sv-text activity-alert-see" data-act="see" @click="$emit('see', a.minute)">{{ $t('plugins.WorkshopService.access.audit_alert_see') }}</button></li>
		</ul>
		<div v-if="total > rows.length" class="text-caption">{{ $tc('plugins.WorkshopService.access.audit_alerts_more', total - rows.length, { n: total - rows.length }) }}</div>
	</div>
</template>

<script>
'use strict'

import { accessApi } from './access-api.js'
import { ALERT_DAYS, ALERT_SHOWN, alertRows } from './access-audit-view.js'

function day(back) {
	const d = new Date(Date.now() - back * 86400000)
	const p = n => String(n).padStart(2, '0')
	return d.getFullYear() + '-' + p(d.getMonth() + 1) + '-' + p(d.getDate())
}

export default {
	props: { tick: { type: Number, default: 0 } },
	data() {
		return { raw: null, loading: false, failure: '', days: ALERT_DAYS }
	},
	computed: {
		lang() {
			return (this.$i18n && this.$i18n.locale) || 'es'
		},
		rows() {
			return alertRows(this.raw, this.lang, this.$t('plugins.WorkshopService.access.audit_anonymous'))
		},
		total() {
			return this.raw && Number.isInteger(this.raw.total) ? this.raw.total : 0
		}
	},
	watch: {
		tick() {
			this.load()
		}
	},
	created() {
		this.load()
	},
	methods: {
		async load() {
			this.loading = true
			this.failure = ''
			try {
				this.raw = await accessApi.alarms(day(ALERT_DAYS), day(0), ALERT_SHOWN)
			} catch (e) {
				this.raw = null
				this.failure = (e && e.message) || String(e)
			}
			this.loading = false
		}
	}
}
</script>

<style>
.activity-alerts { margin-bottom: 8px; }
.activity-alerts-head { display: flex; align-items: baseline; gap: 12px; }
.activity-alert-list { list-style: none; padding: 0; margin: 4px 0; }
.activity-alert { padding: 2px 0; }
</style>
