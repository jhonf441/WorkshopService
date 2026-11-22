<template>
	<!-- What ONE person can do, by area: who they are (role, profiles, groups, ceiling in one list, each with its reason), then the ten areas, each line with its
	     state, the reason and what to do. "Try as this person" only reads (access.check): it does not use their session or PIN and changes nothing.
	       <access-can-person :view="personView(...)" :caps="caps" :focus-area="'movement'" @back="..." @go="..." /> -->
	<div class="can-person-view">
		<div class="access-view-head">
			<v-btn small outlined class="access-touch" @click="$emit('back')"><v-icon left small>mdi-arrow-left</v-icon>{{ $t('plugins.WorkshopService.access.who_all_people') }}</v-btn>
			<strong class="access-view-name">{{ view.name }}</strong>
			<v-chip small outlined label>{{ roleLabel(view.role) }}</v-chip>
			<v-spacer />
			<v-btn small :color="tryOn ? null : 'primary'" :outlined="tryOn" class="access-touch" @click="tryOn = !tryOn"><v-icon left small>mdi-account-eye-outline</v-icon>{{ tryOn ? $t('plugins.WorkshopService.access.who_try_off') : $t('plugins.WorkshopService.access.who_try_button', { name: view.name }) }}</v-btn>
		</div>
		<div v-if="tryOn" class="can-as-banner" role="status"><v-icon small aria-hidden="true">mdi-eye-outline</v-icon><span>{{ $t('plugins.WorkshopService.access.who_try_banner', { name: view.name }) }}</span></div>
		<access-can-try v-if="tryOn" :user="view.name" :role="view.role" :caps="caps" :damaged="view.damaged" />

		<div class="wf-help mb-2">{{ $t('plugins.WorkshopService.access.who_decides_' + (view.governed ? 'profiles' : 'role')) }}</div>
		<div v-if="view.damaged" class="wf-note is-warn mb-2" role="note"><v-icon class="wf-note-icon" aria-hidden="true">mdi-alert-outline</v-icon><span>{{ $t('plugins.WorkshopService.access.who_damaged') }}</span></div>
		<div class="access-rule-label">{{ $t('plugins.WorkshopService.access.who_has_title') }}</div>
		<ul class="can-sources">
			<li v-for="(s, i) in view.sources" :key="i">{{ sourceText(s) }}</li>
		</ul>

		<div class="sv-tbar">
			<div class="access-kinds" role="group">
				<button v-for="f in filters" :key="f" type="button" class="access-kind access-touch" :class="{ 'is-on': show === f }" :aria-pressed="show === f ? 'true' : 'false'" @click="show = f">{{ $t('plugins.WorkshopService.access.who_filter_' + f) }}</button>
			</div>
			<sv-text-field v-model="text" icon="mdi-magnify" type="search" class="access-search" :placeholder="$t('plugins.WorkshopService.access.who_search')" :aria-label="$t('plugins.WorkshopService.access.who_search')" />
		</div>
		<div v-if="hasUnknown" class="wf-help mb-2">{{ $t('plugins.WorkshopService.access.who_unknown_note') }}</div>

		<div v-for="a in shownAreas" :key="a.id" class="can-area">
			<button type="button" class="can-area-head access-touch" :aria-expanded="isOpen(a) ? 'true' : 'false'" @click="toggle(a)">
				<v-icon small aria-hidden="true">{{ a.icon }}</v-icon>
				<span class="can-area-name">{{ $t('plugins.WorkshopService.access.area_' + a.id) }}</span>
				<access-can-state :state="a.state" />
				<span class="wf-help can-area-count">{{ $t('plugins.WorkshopService.access.who_area_allowed', { n: allowedOf(a), total: a.total }) }}</span>
				<v-icon small aria-hidden="true">{{ isOpen(a) ? 'mdi-chevron-up' : 'mdi-chevron-down' }}</v-icon>
			</button>
			<ul v-if="isOpen(a)" class="can-lines">
				<access-can-line v-for="l in a.lines" :key="l.id" :line="l" :role="view.role" @go="g => $emit('go', g)" />
			</ul>
		</div>
		<div v-if="!shownAreas.length" class="wf-help">{{ $t('plugins.WorkshopService.access.who_no_match') }}</div>
	</div>
</template>

<script>
'use strict'

import SvTextField from './ui/SvTextField.vue'
import AccessCanState from './AccessCanState.vue'
import AccessCanLine from './AccessCanLine.vue'
import AccessCanTry from './AccessCanTry.vue'
import { displayNamesMixin } from './display-names-mixin.js'
import { isBaseRole } from './access-people-view.js'

const FILTERS = Object.freeze(['all', 'cannot', 'can'])
const NOT_ALLOWED = Object.freeze(['cannot', 'admin_only', 'unknown'])

export default {
	name: 'AccessCanPerson',
	components: { SvTextField, AccessCanState, AccessCanLine, AccessCanTry },
	mixins: [displayNamesMixin],
	props: {
		view: { type: Object, required: true },
		caps: { type: Array, default: () => [] },
		focusArea: { type: String, default: '' }
	},
	data() {
		return { show: 'all', text: '', open: this.focusArea ? { [this.focusArea]: true } : {}, tryOn: false }
	},
	computed: {
		filters() { return FILTERS },
		hasUnknown() { return this.view.areas.some(a => a.unknown) },
		searching() { return this.show !== 'all' || !!(this.text || '').trim() },
		// the areas with the lines the filter keeps (an area with none is left out while a filter or a search is on)
		shownAreas() {
			const q = (this.text || '').trim().toLowerCase()
			const keep = l => (this.show === 'all' || (this.show === 'can' ? !NOT_ALLOWED.includes(l.state) : NOT_ALLOWED.includes(l.state))) && (!q || l.title.toLowerCase().includes(q))
			return this.view.areas.map(a => Object.assign({}, a, { lines: a.lines.filter(keep) })).filter(a => !this.searching || a.lines.length)
		}
	},
	watch: {
		focusArea(a) { if (a) this.open = Object.assign({}, this.open, { [a]: true }) }
	},
	methods: {
		roleLabel(r) { return isBaseRole(r) ? this.$t('plugins.WorkshopService.users.role_' + r) : r },
		allowedOf(a) { return a.counts.can + a.counts.stop },
		isOpen(a) { return this.searching || !!this.open[a.id] },
		toggle(a) { this.open = Object.assign({}, this.open, { [a.id]: !this.open[a.id] }) },
		// one line of what the person has: its name (never the id) and why it is there
		sourceText(s) {
			const A = 'plugins.WorkshopService.access.'
			if (s.kind === 'role') return this.$t(A + s.reason, { role: this.roleLabel(s.role), name: s.role })
			if (s.kind === 'own_role') return this.$t(A + s.reason, { name: s.name })
			if (s.kind === 'profile') return this.$t(A + s.reason, { name: this.profileText(s.id) })
			if (s.kind === 'group') return this.$t(A + s.reason, { name: s.group, profiles: s.profiles.length ? s.profiles.map(p => this.profileText(p)).join(', ') : this.$t(A + 'groups_profiles_none') })
			return this.$t(A + s.reason, { name: this.profileText(s.id) })
		}
	}
}
</script>

<style>
.can-as-banner { display: flex; align-items: center; gap: 8px; padding: 8px 12px; margin-bottom: 8px; border: 1px solid var(--wf-c-warning); border-radius: 8px; font-size: 13px; }
.can-sources { margin: 4px 0 12px; padding-left: 18px; font-size: 13px; }
.can-area { border: 1px solid var(--wf-line); border-radius: 8px; margin-bottom: 8px; }
.can-area-head { display: flex; align-items: center; flex-wrap: wrap; gap: 4px 12px; width: 100%; padding: 6px 12px; border: 0; background: transparent; color: inherit; font: inherit; text-align: left; cursor: pointer; }
.can-area-name { flex: 1 1 160px; font-weight: 600; }
.can-lines { margin: 0; padding: 0 12px 8px; }
</style>
