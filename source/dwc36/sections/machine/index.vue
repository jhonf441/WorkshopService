<template>
	<!-- Machine: what the machine does by itself (Automations) and how the Pi talks to the board (Communication). A tab is built the
	     first time it is opened and then only hidden. Props: active (this section is in view), tab ('auto' | 'comms'). -->
	<div class="sv-machine">
		<auto-tab v-if="seen.auto" v-show="tab === 'auto'" :active="active && tab === 'auto'" />
		<comms-tab v-if="seen.comms" v-show="tab === 'comms'" :active="active && tab === 'comms'" />
	</div>
</template>

<script>
import AutoTab from './AutoTab.vue'
import CommsTab from './CommsTab.vue'

export default {
	name: 'MachineSection',
	components: { AutoTab, CommsTab },
	props: { active: { type: Boolean, default: false }, tab: { type: String, default: 'auto' } },
	data() {
		return { seen: { auto: false, comms: false } }
	},
	watch: {
		tab: { immediate: true, handler(now) { if (this.active && now in this.seen) this.seen[now] = true } },
		active(on) { if (on && this.tab in this.seen) this.seen[this.tab] = true }
	}
}
</script>
