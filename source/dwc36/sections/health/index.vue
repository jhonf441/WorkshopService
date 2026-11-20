<template>
	<!-- Diagnostics: how the processes of the service are doing, what the service asks of the board, and what happened the last
	     time the Pi went off without closing. A tab is built the first time it is opened and then only hidden.
	     Props: active (this section is in view), tab ('processes' | 'load' | 'shutdowns'), anchor. -->
	<div class="sv-health">
		<processes-tab v-if="seen.processes" v-show="tab === 'processes'" :active="active && tab === 'processes'" :anchor="tab === 'processes' ? anchor : ''" />
		<load-tab v-if="seen.load" v-show="tab === 'load'" />
		<shutdowns-tab v-if="seen.shutdowns" v-show="tab === 'shutdowns'" :active="active && tab === 'shutdowns'" />
	</div>
</template>

<script>
import LoadTab from './LoadTab.vue'
import ProcessesTab from './ProcessesTab.vue'
import ShutdownsTab from './ShutdownsTab.vue'

export default {
	name: 'HealthSection',
	components: { LoadTab, ProcessesTab, ShutdownsTab },
	props: { active: { type: Boolean, default: false }, tab: { type: String, default: 'processes' }, anchor: { type: String, default: '' } },
	data() {
		return { seen: { processes: false, load: false, shutdowns: false } }
	},
	watch: {
		tab: { immediate: true, handler(now) { if (this.active && now in this.seen) this.seen[now] = true } },
		active(on) { if (on && this.tab in this.seen) this.seen[this.tab] = true }
	}
}
</script>
