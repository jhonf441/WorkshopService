<template>
	<!-- THE legend of Setup: the four colours every state of this section uses and, for the files, what each of the six words means. One place, the same
	     words everywhere. Props: kind ('levels' | 'files'). -->
	<div class="sv-legend" :data-kind="kind">
		<p class="sv-legend-title">{{ t('configPackage.legend_title') }}</p>
		<ul v-if="kind === 'levels'" class="sv-legend-list">
			<li v-for="l in LEVELS" :key="l"><span class="sv-state" :data-level="l"><span class="mdi sv-ico sv-ico-s" :class="LEVEL_ICON[l]" aria-hidden="true" />{{ t('configPackage.lv_' + l).split(':')[0] }}</span><span>{{ t('configPackage.lv_' + l).split(':').slice(1).join(':').trim() }}</span></li>
		</ul>
		<ul v-else class="sv-legend-list">
			<li v-for="s in FILE_STATES" :key="s"><span class="sv-state" :data-level="LEVEL[s]"><span class="mdi sv-ico sv-ico-s" :class="LEVEL_ICON[LEVEL[s]]" aria-hidden="true" />{{ t('configPackage.fs_' + s) }}</span><span>{{ t('configPackage.fsh_' + s).split(':').slice(1).join(':').trim() }}</span></li>
		</ul>
	</div>
</template>

<script>
import { t } from '../../core/dwc.js'
import { FILE_STATES } from '../../package-view.js'

const LEVELS = ['ok', 'warn', 'error', 'rest']

export default {
	name: 'StateLegend',
	props: { kind: { type: String, default: 'levels' } },
	data() {
		return {
			LEVELS,
			FILE_STATES,
			LEVEL: { identical: 'ok', present: 'ok', missing: 'error', edited: 'warn', not_yet: 'rest', attention: 'warn' },
			LEVEL_ICON: { ok: 'mdi-check-circle-outline', warn: 'mdi-alert-outline', error: 'mdi-close-circle-outline', rest: 'mdi-clock-outline' }
		}
	},
	methods: { t }
}
</script>
