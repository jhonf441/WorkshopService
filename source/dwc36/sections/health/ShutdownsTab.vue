<template>
	<!-- Diagnostics > Unclean shutdowns: the report the service keeps when the Pi went off without closing (a power cut, a hang).
	     The report is published: anybody reads it. Marking it as reviewed, showing it again and reading the lines of now are a
	     technician's (shown as state, with ONE sentence, to anybody else). Prop: active. -->
	<div id="svc-blackbox" class="sv-health-box">
		<section class="sv-card" aria-labelledby="sv-hb-title">
			<div class="sv-card-head">
				<h2 id="sv-hb-title"><span class="mdi mdi-power-plug-off-outline sv-ico" aria-hidden="true" />{{ t('health.box_title') }}</h2>
				<span class="sv-state" :data-level="report ? 'warn' : 'ok'" data-part="chip"><span class="mdi sv-ico sv-ico-s" :class="report ? 'mdi-alert-outline' : 'mdi-check-circle-outline'" aria-hidden="true" />{{ t(report ? 'health.box_unreviewed' : 'health.box_state_clean') }}</span>
			</div>

			<p v-if="!report && !last" class="sv-quiet" data-part="none">{{ t(running ? 'health.box_none' : 'health.stopped_note') }}</p>

			<template v-else-if="report">
				<dl class="sv-facts">
					<dt>{{ t('health.box_last_datum') }}</dt><dd data-fact="last">{{ report.last_datum || '?' }}</dd>
					<dt>{{ t('health.box_detected') }}</dt><dd data-fact="detected">{{ (report.detected || '?').replace('T', ' ') }}</dd>
					<dt>{{ t('health.box_verdict') }}</dt><dd data-fact="verdict">{{ t(OLD + 'box_v_' + a.verdict + '_t') }}</dd>
				</dl>
				<p class="sv-quiet">{{ t(OLD + 'box_v_' + a.verdict + '_d', verdictData) }}</p>
				<p v-if="a.inJob" class="sv-field-error" role="alert"><span class="mdi mdi-alert-outline sv-ico sv-ico-s" aria-hidden="true" />{{ t(OLD + 'box_in_job') }}</p>
				<template v-if="steps.length">
					<h3 class="sv-h3">{{ t(OLD + 'box_todo') }}</h3>
					<ol class="sv-health-steps"><li v-for="s in steps" :key="s">{{ s }}</li></ol>
				</template>
				<details class="sv-help" data-part="lines">
					<summary><span class="mdi mdi-text-long sv-ico sv-ico-s" aria-hidden="true" />{{ tc('health.box_lines', lines.length) }}</summary>
					<pre class="sv-health-pre" tabindex="0">{{ lines.join('\n') }}</pre>
				</details>
			</template>

			<p v-else data-part="last">{{ t('health.box_last', { when: last.last_datum || '?' }) }}</p>

			<ul v-if="report || last" class="sv-rows">
				<sv-action-row icon="mdi-download" :name="t('health.box_download_name')" :desc="downloadNote || t('health.box_download_desc')" :label="t(downloading ? 'kit.sending' : 'health.box_download')" @run="download" />
				<sv-action-row v-if="report" icon="mdi-check" :name="t('health.box_hide_name')" :desc="t('health.box_hide_desc')" :action="boxHide" :permission="perm('blackbox.hide')" :stale="!running"
					:label="t('health.box_hide')" @run="boxHide.run()" @retry="boxHide.run()" />
				<sv-action-row v-else icon="mdi-eye-outline" :name="t('health.box_show_name')" :desc="t('health.box_show_desc')" :action="boxShow" :permission="perm('blackbox.show')" :stale="!running"
					:label="t('health.box_show')" @run="boxShow.run()" @retry="boxShow.run()" />
			</ul>
			<sv-reason v-if="report || last" :lock="lock" @sign-in="signIn" />
		</section>

		<section class="sv-card" aria-labelledby="sv-hn-title">
			<div class="sv-card-head"><h2 id="sv-hn-title"><span class="mdi mdi-text-box-search-outline sv-ico" aria-hidden="true" />{{ t('health.now_title') }}</h2></div>
			<p class="sv-quiet">{{ t('health.now_desc', { n: MAX_LINES, s: interval }) }}</p>
			<details class="sv-fold" :open="nowOpen" data-part="now" @toggle="setNow($event.target.open)">
				<summary><span class="mdi mdi-chevron-right sv-ico sv-chev" aria-hidden="true" /><span class="sv-fold-name">{{ t('health.now_open') }}</span></summary>
				<div v-if="nowOpen" class="sv-fold-body">
					<sv-zone :status="now.status" :error="now.error" :lock="now.lock" :updated="nowTime" refreshable :empty-title="t('health.now_empty')" @retry="now.reload()" @refresh="now.reload()" @sign-in="signIn">
						<pre class="sv-health-pre" tabindex="0">{{ now.data }}</pre>
					</sv-zone>
				</div>
			</details>
		</section>
	</div>
</template>

<script>
import { t, tc, te, locale, readFile, saveText } from '../../core/dwc.js'
import { get, serviceRunning } from '../../core/live/published.js'
import { can, signIn } from '../../core/store/session.js'
import { createResource } from '../../core/store/resource.js'
import { call } from '../../core/api/call.js'
import { boxHide, boxShow } from '../../core/actions/processes.js'
import { time as clockTime } from '../../core/format/dates.js'
import { analyzeBox } from '../../black-box.js'
import SvActionRow from '../../ui/SvActionRow.vue'
import SvReason from '../../ui/SvReason.vue'
import SvZone from '../../ui/SvZone.vue'

const MAX_LINES = 200
const OLD = 'plugins.WorkshopService.servicePage.'
const DEFAULT_FILE = '0:/sys/workshop/data/blackbox/unclean-report.txt'

// the last lines the black box wrote, as they are NOW: a photo taken when asked, never a live view
const now = createResource({
	key: 'blackbox-lines', needs: 'blackbox.lines', empty: d => !String(d || '').trim(),
	load: async () => { const r = await call('blackbox.lines', { n: MAX_LINES }, { quiet: true }); return r.text || (typeof r.data === 'string' ? r.data : '') }
})

export default {
	name: 'ShutdownsTab',
	components: { SvActionRow, SvReason, SvZone },
	props: { active: { type: Boolean, default: false } },
	data() {
		return { OLD, MAX_LINES, boxHide, boxShow, now, nowOpen: false, downloading: false, downloadNote: '' }
	},
	computed: {
		running() {
			return serviceRunning()
		},
		box() {
			return get('boxBlack') || {}
		},
		report() {
			return this.box.report || null
		},
		last() {
			return this.box.last_drop || null
		},
		interval() {
			return this.box.interval_s || 5
		},
		lines() {
			return (this.report && Array.isArray(this.report.lines) ? this.report.lines : [])
		},
		a() {
			return analyzeBox(this.lines)
		},
		verdictData() {
			const a = this.a
			const stuck = a.last ? a.last.locks.concat(a.last.slow).map(x => x.name).join(', ') : ''
			return { cpu: a.cpu.max, ram: a.ram.max, temp: a.temp.max, min: Math.max(1, Math.round(a.samples.length * this.interval / 60)), thing: stuck }
		},
		steps() {
			const out = []
			for (let k = 1; k <= 6; k++) {
				const key = OLD + 'box_v_' + this.a.verdict + '_s' + k
				if (!te(key)) break
				out.push(t(key))
			}
			return out
		},
		lock() {
			const all = [can(this.report ? 'blackbox.hide' : 'blackbox.show')]
			return all.find(c => c.state === 'session') || all.find(c => c.state === 'role') || null
		},
		nowTime() {
			return this.now.loadedAt ? clockTime(this.now.loadedAt, locale()) : ''
		}
	},
	watch: {
		active(on) { if (!on) this.now.hide(); else if (this.nowOpen) this.now.show() }
	},
	beforeDestroy() {
		this.now.hide()
	},
	methods: {
		t,
		tc,
		signIn,
		perm(op) {
			return can(op)
		},
		setNow(on) {
			if (on === this.nowOpen) return
			this.nowOpen = on
			if (on) this.now.show(); else this.now.hide()
		},
		// the whole report from the SD; when it cannot be read, the lines the page already has, and it says so
		async download() {
			const r = this.report || this.last
			if (!r || this.downloading) return
			this.downloading = true
			this.downloadNote = ''
			let text = await readFile(r.file || DEFAULT_FILE)
			if (text === null) {
				text = this.lines.join('\n') + '\n'
				this.downloadNote = t(this.lines.length ? 'health.box_download_partial' : 'health.box_download_failed')
			}
			if (text.trim()) saveText('unclean-shutdown-' + String(r.last_datum || r.detected || '').replace(/[^0-9]/g, '').slice(0, 12) + '.txt', text)
			this.downloading = false
		}
	}
}
</script>
