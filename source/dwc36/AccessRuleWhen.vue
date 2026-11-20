<template>
	<!-- "Only when" of one rule: exactly the five conditions of the service (mode, job running, machine on, way in, highest risk). There is no field of
	     time, date or address and none can be typed: the list is closed. Emits set(key, value) with value undefined to remove the condition.
	       <access-rule-when :when="rule.when" @set="(key, value) => ..." /> -->
	<div class="access-when">
		<div class="access-when-row">
			<span class="access-rule-label">{{ $t('plugins.WorkshopService.access.builder_when_mode') }}</span>
			<access-toggle v-for="m in modes" :key="m" :label="m" :on="inList('mode', m)" @click="flip('mode', m)" />
			<access-toggle :label="$t('plugins.WorkshopService.access.builder_when_person_modes')" :on="inList('mode', variable)" @click="flip('mode', variable)" />
		</div>
		<div v-for="k in flags" :key="k" class="access-when-row">
			<span class="access-rule-label">{{ $t('plugins.WorkshopService.access.builder_when_' + (k === 'job_running' ? 'job' : 'on')) }}</span>
			<access-toggle radio :label="$t('plugins.WorkshopService.access.builder_when_any')" :on="flag(k) === undefined" @click="$emit('set', k, undefined)" />
			<access-toggle radio :label="$t('plugins.WorkshopService.access.common_yes')" :on="flag(k) === true" @click="$emit('set', k, true)" />
			<access-toggle radio :label="$t('plugins.WorkshopService.access.common_no')" :on="flag(k) === false" @click="$emit('set', k, false)" />
		</div>
		<div class="access-when-row">
			<span class="access-rule-label">{{ $t('plugins.WorkshopService.access.builder_when_via') }}</span>
			<access-toggle v-for="v in vias" :key="v" :label="$t('plugins.WorkshopService.access.check_via_' + v)" :on="inList('via', v)" @click="flip('via', v)" />
		</div>
		<div class="access-when-row">
			<span class="access-rule-label">{{ $t('plugins.WorkshopService.access.builder_when_risk') }}</span>
			<access-toggle radio :label="$t('plugins.WorkshopService.access.builder_when_any')" :on="risk === undefined" @click="$emit('set', 'risk_max', undefined)" />
			<access-toggle v-for="n in 4" :key="n" radio :label="String(n)" :on="risk === n" @click="$emit('set', 'risk_max', n)" />
		</div>
	</div>
</template>

<script>
'use strict'

import AccessToggle from './AccessToggle.vue'
import { MODES, VIAS, MODE_VARIABLE } from './access-profile-edit.js'

export default {
	components: { AccessToggle },
	props: { when: { type: Object, default: null } },
	data() {
		return { modes: MODES, vias: VIAS, variable: MODE_VARIABLE, flags: ['job_running', 'machine_on'] }
	},
	computed: {
		risk() {
			return this.when ? this.when.risk_max : undefined
		}
	},
	methods: {
		list(key) {
			return this.when && Array.isArray(this.when[key]) ? this.when[key] : []
		},
		inList(key, v) {
			return this.list(key).indexOf(v) >= 0
		},
		flip(key, v) {
			const l = this.list(key).slice()
			const at = l.indexOf(v)
			if (at >= 0) l.splice(at, 1)
			else l.push(v)
			this.$emit('set', key, l.length ? l : undefined)
		},
		flag(key) {
			return this.when ? this.when[key] : undefined
		}
	}
}
</script>

<style>
.access-when-row { display: flex; align-items: center; flex-wrap: wrap; gap: 6px; margin-top: 6px; }
</style>
