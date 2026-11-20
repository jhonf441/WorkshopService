<template>
	<!-- Data > Database: is the database healthy, how big it is, what it keeps and since when; and, for a technician, whether the old energy
	     readings are summed up. Read with a session (a visitor reads it too: it is a viewer operation). Prop: active (this tab is in view). -->
	<div class="sv-data-db">
		<section class="sv-card" aria-labelledby="sv-dd-title" data-card="db">
			<div class="sv-card-head">
				<h2 id="sv-dd-title"><span class="mdi mdi-database-outline sv-ico" aria-hidden="true" />{{ t('data.db_title') }}</h2>
				<span v-if="status.data" class="sv-chip" :data-level="fig.ok ? null : 'warn'"><span class="mdi sv-ico sv-ico-s" :class="fig.ok ? 'mdi-check-circle-outline' : 'mdi-alert-outline'" aria-hidden="true" />{{ t(fig.ok ? 'data.db_check_ok' : 'data.db_check_bad') }}</span>
			</div>
			<sv-zone :status="status.status" :error="status.error" :lock="status.lock" :updated="updated" refreshable :empty-title="t('data.db_none')" @retry="status.reload()" @refresh="status.reload()" @sign-in="signIn">
				<div class="sv-stats">
					<div class="sv-stat" data-stat="size"><b>{{ fig.mb === null ? '–' : fig.mb + ' MB' }}</b><span>{{ t('data.db_size') }}</span></div>
					<div class="sv-stat" data-stat="rows"><b>{{ fig.rows }}</b><span>{{ t('data.db_rows') }}</span></div>
					<div class="sv-stat" data-stat="written"><b>{{ written }}</b><span>{{ t('data.db_written') }}</span></div>
					<div class="sv-stat" data-stat="free"><b>{{ fig.freeGb === null ? '–' : fig.freeGb + ' GB' }}</b><span>{{ t('data.db_free') }}</span></div>
				</div>
				<p v-if="!fig.ok" class="sv-field-error" role="alert" data-part="check-bad"><span class="mdi mdi-alert-outline sv-ico sv-ico-s" aria-hidden="true" />{{ t('data.db_check_bad_text') }}</p>
				<table class="sv-table">
					<caption class="sv-vh">{{ t('data.db_table') }}</caption>
					<thead><tr><th scope="col">{{ t('data.db_keeps') }}</th><th scope="col" class="sv-num">{{ t('data.db_rows_col') }}</th><th scope="col">{{ t('data.db_since') }}</th><th scope="col">{{ t('data.db_until') }}</th></tr></thead>
					<tbody>
						<tr v-for="x in tables" :key="x.name" :data-table="x.name">
							<th scope="row" :data-label="t('data.db_keeps')">{{ label(x.name) }}<code class="sv-code">{{ x.name }}</code></th>
							<td class="sv-num" :data-label="t('data.db_rows_col')">{{ x.rows }}</td>
							<td :data-label="t('data.db_since')">{{ day(x.since) }}</td>
							<td :data-label="t('data.db_until')">{{ day(x.until) }}</td>
						</tr>
					</tbody>
				</table>
			</sv-zone>
		</section>

		<section v-if="status.data" class="sv-card" aria-labelledby="sv-dd-sum" data-card="summarize">
			<div class="sv-card-head"><h2 id="sv-dd-sum"><span class="mdi mdi-chart-line sv-ico" aria-hidden="true" />{{ t('data.sum_title') }}</h2></div>
			<ul class="sv-rows">
				<sv-action-row icon="mdi-chart-line" :name="t('data.sum_name')" :desc="t('data.sum_desc', { days: detailDays })" :action="dbSettings" :permission="perm('db.settings')" :stale="stale" @retry="toggleSummarize">
					<template #control="c">
						<sv-switch :checked="summarize === true" :word="t(summarize === null ? 'data.word_unknown' : summarize ? 'data.word_on' : 'data.word_off')" :label="t('data.sum_name')" :state="c.state" :disabled="c.disabled || summarize === null" @toggle="toggleSummarize" />
					</template>
					<template #help><sv-help v-bind="help('summarize', 'data')" /></template>
				</sv-action-row>
			</ul>
			<sv-reason :lock="lockOf(['db.settings'])" @sign-in="signIn" />
		</section>
	</div>
</template>

<script>
import { locale } from '../../core/dwc.js'
import { dbStatus } from '../../core/resources.js'
import { dbSettings } from '../../core/actions/data.js'
import { want } from '../../core/store/session.js'
import { rowsMixin } from '../../core/rows-mixin.js'
import { date, time, toMs } from '../../core/format/dates.js'
import { tableLabel } from '../../table-names.js'
import SvActionRow from '../../ui/SvActionRow.vue'
import SvHelp from '../../ui/SvHelp.vue'
import SvReason from '../../ui/SvReason.vue'
import SvSwitch from '../../ui/SvSwitch.vue'
import SvZone from '../../ui/SvZone.vue'
import { figuresOf, tablesOf } from './view.js'

export default {
	name: 'DbTab',
	components: { SvActionRow, SvHelp, SvReason, SvSwitch, SvZone },
	mixins: [rowsMixin],
	props: { active: { type: Boolean, default: false } },
	data() {
		return { status: dbStatus, dbSettings }
	},
	computed: {
		fig() {
			return figuresOf(this.status.data)
		},
		tables() {
			return tablesOf(this.status.data)
		},
		written() {
			const ms = toMs(this.status.data && this.status.data.modified)
			return ms === null ? '–' : time(ms, locale()).slice(0, 5)
		},
		updated() {
			return this.status.loadedAt ? time(this.status.loadedAt, locale()).slice(0, 5) : ''
		},
		summarize() {
			const d = this.status.data
			const b = d && d.backup
			return b && typeof b.summarize_consumption === 'boolean' ? b.summarize_consumption : null
		},
		detailDays() {
			const d = this.status.data
			return (d && d.consumption_detail_days) || 90
		}
	},
	watch: {
		active: { immediate: true, handler(on) { if (on) { want(['db.status', 'db.settings']); this.status.show() } else this.status.hide() } }
	},
	methods: {
		label(name) {
			const l = tableLabel(name)
			return l.key ? this.t(l.key) : name
		},
		day(value) {
			const ms = toMs(value)
			return ms === null ? '–' : date(ms, locale())
		},
		toggleSummarize() {
			if (this.summarize === null) return
			this.dbSettings.run({ summarize: !this.summarize })
		}
	}
}
</script>
