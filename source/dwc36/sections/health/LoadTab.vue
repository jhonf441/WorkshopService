<template>
	<!-- Diagnostics > Load towards the board: how much the service asks the board, against the limit it is designed to stay under, and
	     what the service itself costs the Pi. Only published data: anybody sees it. -->
	<div class="sv-health-load">
	<section class="sv-card" aria-labelledby="sv-hl-title">
		<div class="sv-card-head"><h2 id="sv-hl-title"><span class="mdi mdi-swap-vertical-bold sv-ico" aria-hidden="true" />{{ t('health.load_title') }}</h2>
			<span class="sv-state" :data-level="state.level" data-part="state"><span class="mdi sv-ico sv-ico-s" :class="state.icon" aria-hidden="true" />{{ state.text }}</span>
		</div>
		<p v-if="!hasData" class="sv-quiet" role="status">{{ t(running ? 'health.no_data' : 'health.stopped_note') }}</p>
		<template v-else>
			<div class="sv-stats" :class="{ 'sv-stale': !running }">
				<div class="sv-stat" data-stat="calls" :data-level="load.over ? 'warn' : null"><b>{{ load.perMin === null ? '–' : load.perMin }}</b><span>{{ t('health.load_calls', { limit: load.limit }) }}</span></div>
				<div class="sv-stat" data-stat="subscription" :data-level="subDown ? 'error' : null"><b>{{ subWord }}</b><span>{{ subLine }}</span></div>
				<div class="sv-stat" data-stat="cpu"><b>{{ num(proc.cpu_pct, ' %') }}</b><span>{{ t('health.load_cpu') }}</span></div>
				<div class="sv-stat" data-stat="memory"><b>{{ num(proc.memory_mb, ' MB') }}</b><span>{{ t('health.load_memory') }}</span></div>
			</div>
			<p :class="load.over ? 'sv-field-error' : 'sv-quiet'" :role="load.over ? 'alert' : null" data-part="verdict">{{ verdict }}</p>
			<table v-if="load.areas.length" class="sv-table">
				<caption class="sv-vh">{{ t('health.load_table') }}</caption>
				<thead><tr><th scope="col">{{ t('health.load_area') }}</th><th scope="col" class="sv-num">{{ t('health.load_per_min') }}</th><th scope="col" class="sv-num">{{ t('health.load_share') }}</th><th scope="col" class="sv-num">{{ t('health.load_slowest') }}</th></tr></thead>
				<tbody>
					<tr v-for="a in load.areas" :key="a.id" :data-area="a.id"><th scope="row"><code class="sv-code">{{ a.id }}</code></th><td class="sv-num">{{ a.n }}</td><td class="sv-num">{{ a.pct }} %</td><td class="sv-num">{{ a.maxMs }} ms</td></tr>
				</tbody>
			</table>
			<p v-else class="sv-quiet">{{ t('health.load_none') }}</p>
			<p v-if="piHealth" class="sv-quiet sv-home-note"><a class="sv-btn sv-text" :href="PI_HEALTH" @click="toPiHealth">{{ t('health.load_pi_health') }}</a></p>
		</template>
	</section>
		<screen-card />
	</div>
</template>

<script>
import { t, tc, goPath, pathExists } from '../../core/dwc.js'
import { get, serviceRunning } from '../../core/live/published.js'
import { loadOf } from './view.js'
import ScreenCard from './ScreenCard.vue'

const PI_HEALTH = '/Plugins/PiHealth'

export default {
	name: 'LoadTab',
	components: { ScreenCard },
	data() {
		return { PI_HEALTH }
	},
	computed: {
		// the one word of the card, like the state of a process: within the limit, over it, the subscription lost, or nothing to say yet
		state() {
			if (!this.hasData) return { level: 'rest', icon: 'mdi-minus-circle-outline', text: t('health.load_state_none') }
			if (this.subDown) return { level: 'error', icon: 'mdi-close-circle-outline', text: t('health.load_state_down') }
			if (this.load.over) return { level: 'warn', icon: 'mdi-alert-outline', text: t('health.load_state_over') }
			return { level: 'ok', icon: 'mdi-check-circle-outline', text: t('health.load_state_ok') }
		},
		running() {
			return serviceRunning()
		},
		hasData() {
			return !!get('servicesInternal')
		},
		load() {
			return loadOf(get('servicesInternal'))
		},
		proc() {
			return this.load.process || {}
		},
		subDown() {
			return !!this.load.subscription && this.load.subscription.live === false
		},
		subWord() {
			const s = this.load.subscription
			return !s ? '–' : t(s.live === false ? 'health.sub_down' : 'health.sub_live')
		},
		subLine() {
			const s = this.load.subscription
			return s && s.live !== false && typeof s.patches_s === 'number' ? t('health.sub_rate', { n: s.patches_s, kb: s.kb_s }) : t('health.load_subscription')
		},
		verdict() {
			const l = this.load
			if (l.perMin === null) return t('health.load_unknown')
			const top = l.areas[0]
			if (l.over) return t('health.load_over', { n: l.perMin, limit: l.limit }) + (top ? ' ' + t('health.load_top', { area: top.id, pct: top.pct }) : '')
			return tc('health.load_normal', l.perMin, { limit: l.limit })
		},
		piHealth() {
			return pathExists(PI_HEALTH)
		}
	},
	methods: {
		t,
		num(v, unit) {
			return typeof v === 'number' ? v + unit : '–'
		},
		toPiHealth(e) {
			if (e && (e.ctrlKey || e.metaKey || e.shiftKey || e.altKey || e.button > 0)) return
			if (e && typeof e.preventDefault === 'function') e.preventDefault()
			goPath(PI_HEALTH)
		}
	}
}
</script>
