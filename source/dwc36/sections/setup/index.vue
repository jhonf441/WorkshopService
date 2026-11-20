<template>
	<!-- Setup: what the machine still needs (State), the files the plugins create (Files), the changes to apply and their history (Changes) and the
	     package of settings (Package). A tab is built the first time it is opened and then only hidden. Props: active (this section is in view), tab. -->
	<div class="sv-setup">
		<status-tab v-if="seen.status" v-show="tab === 'status'" :active="active && tab === 'status'" />
		<files-tab v-if="seen.files" v-show="tab === 'files'" :active="active && tab === 'files'" />
		<changes-tab v-if="seen.changes" v-show="tab === 'changes'" :active="active && tab === 'changes'" />
		<package-tab v-if="seen.package" v-show="tab === 'package'" :active="active && tab === 'package'" />
	</div>
</template>

<script>
import ChangesTab from './ChangesTab.vue'
import FilesTab from './FilesTab.vue'
import PackageTab from './PackageTab.vue'
import StatusTab from './StatusTab.vue'

export default {
	name: 'SetupSection',
	components: { ChangesTab, FilesTab, PackageTab, StatusTab },
	props: { active: { type: Boolean, default: false }, tab: { type: String, default: 'status' } },
	data() {
		return { seen: { status: false, files: false, changes: false, package: false } }
	},
	watch: {
		tab: { immediate: true, handler(now) { if (this.active && now in this.seen) this.seen[now] = true } },
		active(on) { if (on && this.tab in this.seen) this.seen[this.tab] = true }
	}
}
</script>
