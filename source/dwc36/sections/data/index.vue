<template>
	<!-- Data and backups: the database and its copies. A tab is built the first time it is opened and then only hidden.
	     Props: active (this section is in view), tab ('db' | 'backups'). -->
	<div class="sv-data">
		<db-tab v-if="seen.db" v-show="tab === 'db'" :active="active && tab === 'db'" />
		<backups-tab v-if="seen.backups" v-show="tab === 'backups'" :active="active && tab === 'backups'" />
	</div>
</template>

<script>
import BackupsTab from './BackupsTab.vue'
import DbTab from './DbTab.vue'

export default {
	name: 'DataSection',
	components: { BackupsTab, DbTab },
	props: { active: { type: Boolean, default: false }, tab: { type: String, default: 'db' } },
	data() {
		return { seen: { db: false, backups: false } }
	},
	watch: {
		tab: { immediate: true, handler(now) { if (this.active && now in this.seen) this.seen[now] = true } },
		active(on) { if (on && this.tab in this.seen) this.seen[this.tab] = true }
	}
}
</script>
