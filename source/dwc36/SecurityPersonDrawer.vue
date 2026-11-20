<template>
	<!-- What the report knows of one person: access, PIN, last sign-in and the last use of each capability (newest first). A panel over the tables, not a side
	     drawer: it works the same with a finger. "See access" and "See activity" ask the page to go there (this screen changes nothing).
	       <security-person-drawer :person="row of the people table" :now="answer.generated" @back @see-access @see-can @see-activity /> -->
	<div class="security-drawer">
		<div class="security-drawer-head">
			<v-btn small outlined class="access-touch" @click="$emit('back')"><v-icon left small>mdi-arrow-left</v-icon>{{ rt('common_back') }}</v-btn>
			<strong class="security-drawer-name">{{ person.name }}</strong>
			<v-chip small outlined label>{{ person.customRole ? person.role : rt('users.role_' + person.role) }}</v-chip>
			<v-chip small outlined label :color="person.governed ? 'info' : ''">{{ rt(person.governed ? 'report_governed' : 'report_base_only') }}</v-chip>
			<v-chip v-if="person.locked" small outlined label color="error">{{ rt('report_locked', { time: duration(person.lockedFor) }) }}</v-chip>
			<v-chip v-if="person.neverSignedIn" small outlined label color="warning">{{ rt('report_never_signed') }}</v-chip>
		</div>
		<div class="wf-help">{{ rt('report_drawer_groups', { names: names(person.groups) }) }}</div>
		<div class="wf-help">{{ rt('report_drawer_profiles', { names: names(person.profiles) }) }}</div>
		<h4 class="security-drawer-title">{{ rt('report_drawer') }}</h4>
		<div v-if="!used.length" class="wf-help access-own-empty">{{ rt('report_drawer_empty') }}</div>
		<ul v-else class="security-used" role="list">
			<li v-for="u in used" :key="u.capability" class="security-used-row"><code>{{ u.capability }}</code><span>{{ ago(u.at) }}</span></li>
		</ul>
		<div class="wf-help mt-2">{{ rt('report_delay') }}</div>
		<div class="security-drawer-act mt-2">
			<v-btn small outlined class="access-touch" @click="$emit('see-access', person.name)">{{ rt('report_see_access') }}</v-btn>
			<v-btn small outlined class="access-touch" @click="$emit('see-can', person.name)">{{ rt('report_see_can') }}</v-btn>
			<v-btn small outlined class="access-touch" @click="$emit('see-activity', person.name)">{{ rt('report_see_activity') }}</v-btn>
		</div>
	</div>
</template>

<script>
'use strict'

import { agoText, durationText, translatorMixin, usedList } from './access-report-view.js'

export default {
	mixins: [translatorMixin],
	props: {
		person: { type: Object, required: true },
		now: { type: Number, default: 0 }
	},
	computed: {
		used() {
			return usedList(this.person)
		}
	},
	methods: {
		ago(epoch) {
			return agoText(this.rt, this.now, epoch)
		},
		duration(s) {
			return durationText(this.rt, s)
		},
		names(list) {
			return list && list.length ? list.join(', ') : this.rt('common_none')
		}
	}
}
</script>

<style>
.security-drawer { border: 1px solid var(--wf-line); border-radius: 8px; padding: 12px; margin-bottom: 12px; }
.security-drawer-head { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; margin-bottom: 8px; }
.security-drawer-name { font-size: 16px; }
.security-drawer-title { margin: 12px 0 4px; font-size: 13px; font-weight: 600; }
.security-used { list-style: none; margin: 0; padding: 0; border: 1px solid var(--wf-line); border-radius: 8px; }
.security-used-row { display: flex; justify-content: space-between; gap: 12px; min-height: 44px; align-items: center; padding: 4px 10px; border-bottom: 1px solid var(--wf-line); font-size: 13px; }
.security-used-row:last-child { border-bottom: 0; }
.security-drawer-act { display: flex; flex-wrap: wrap; gap: 8px; }
</style>
