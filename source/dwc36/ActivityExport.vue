<template>
	<!-- Export: asks audit.export page by page for the range and assembles ONE file of JSON lines in the browser. It works on every screen. The file holds the whole range (audit.export has no other filter).
	       <activity-export :range="{ from, to }" :can-export="true" /> -->
	<div class="activity-export">
		<v-btn v-if="running" small outlined class="access-touch" @click="cancelled = true"><v-icon left small>mdi-close</v-icon>{{ $t('plugins.WorkshopService.access.audit_export_cancel') }}</v-btn>
		<v-btn v-else small outlined class="access-touch" :disabled="!canExport" @click="run()"><v-icon left small>mdi-download</v-icon>{{ $t('plugins.WorkshopService.access.audit_export') }}</v-btn>
		<span v-if="running" class="text-caption">{{ $tc('plugins.WorkshopService.access.audit_export_progress', progress, { n: progress }) }}</span>
		<span v-else-if="note" class="text-caption" role="status">{{ note }}</span>
		<span v-else class="text-caption">{{ $t('plugins.WorkshopService.access.audit_export_range_only') }}</span>
	</div>
</template>

<script>
'use strict'

import { accessApi } from './access-api.js'
import { assembleExport, exportFileName } from './access-audit-view.js'

const AREA = 'plugins.WorkshopService.access.'

export default {
	props: {
		range: { type: Object, default: () => ({ from: '', to: '' }) },
		canExport: { type: Boolean, default: true }
	},
	data() {
		return { running: false, cancelled: false, progress: 0, note: '' }
	},
	methods: {
		// the file goes to the browser; a test replaces this method
		download(text, name) {
			const url = URL.createObjectURL(new Blob([text], { type: 'application/x-ndjson' }))
			const a = document.createElement('a')
			a.href = url
			a.download = name
			document.body.appendChild(a)
			a.click()
			document.body.removeChild(a)
			setTimeout(() => URL.revokeObjectURL(url), 1000)
		},
		async run() {
			if (!this.canExport || this.running) return
			this.running = true
			this.cancelled = false
			this.progress = 0
			this.note = ''
			try {
				const range = { from: this.range.from, to: this.range.to }
				const r = await assembleExport(after => accessApi.auditExport(range, after), { progress: n => { this.progress = n }, cancelled: () => this.cancelled })
				if (r.cancelled) this.note = this.$t(AREA + 'audit_export_cancelled')
				else if (!r.rows) this.note = this.$t(AREA + 'audit_export_empty')
				else {
					this.download(r.text, exportFileName(range))
					this.note = this.$tc(AREA + 'audit_export_done', r.rows, { n: r.rows, chained: r.chained })
				}
			} catch (e) {
				this.note = this.$t(AREA + 'state_error', { detail: (e && e.message) || String(e) })
			}
			this.running = false
		}
	}
}
</script>

<style>
.activity-export { display: inline-flex; align-items: center; gap: 8px; flex-wrap: wrap; }
</style>
