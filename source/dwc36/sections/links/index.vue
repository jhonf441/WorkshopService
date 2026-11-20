<template>
	<!-- Connections: the G-code bridge, the commands received and the API reference. A tab is built the first time it is opened and then only
	     hidden. Props: active (this section is in view), tab ('bridge' | 'commands' | 'api'). -->
	<div class="sv-links">
		<bridge-tab v-if="seen.bridge" v-show="tab === 'bridge'" :active="active && tab === 'bridge'" />
		<commands-tab v-if="seen.commands" v-show="tab === 'commands'" :active="active && tab === 'commands'" />
		<api-tab v-if="seen.api" v-show="tab === 'api'" :active="active && tab === 'api'" />
	</div>
</template>

<script>
import ApiTab from './ApiTab.vue'
import BridgeTab from './BridgeTab.vue'
import CommandsTab from './CommandsTab.vue'

export default {
	name: 'LinksSection',
	components: { ApiTab, BridgeTab, CommandsTab },
	props: { active: { type: Boolean, default: false }, tab: { type: String, default: 'bridge' } },
	data() {
		return { seen: { bridge: false, commands: false, api: false } }
	},
	watch: {
		tab: { immediate: true, handler(now) { if (this.active && now in this.seen) this.seen[now] = true } },
		active(on) { if (on && this.tab in this.seen) this.seen[this.tab] = true }
	}
}
</script>
