<template>
	<!-- Access > Who can do what: every person by areas at a glance, and one person in detail (state, reason and what to do on each line). Everything is read from
	     the service and nothing is changed: users.list (the people), roles.list (the capabilities and their titles), access.person.get, access.groups.list and ONE
	     access.check call per person with up to 100 requests (the 65 capabilities fit). The page groups and words the answers; it never decides a permission.
	     `focus` { name, n }: open that person (asked from the card of a person or from Security). Emits `go` ({ tab, name }) to open another tab. -->
	<div class="access-can">
		<v-card class="mb-3">
			<v-card-title class="text-subtitle-1">
				{{ $t('plugins.WorkshopService.access.who_title') }}
				<v-spacer />
				<v-btn small outlined class="access-touch" :loading="loading" @click="load()"><v-icon left small>mdi-refresh</v-icon>{{ $t('plugins.WorkshopService.access.common_refresh') }}</v-btn>
			</v-card-title>
			<v-card-text>
				<div class="wf-help mb-2">{{ $t('plugins.WorkshopService.access.who_help') }}</div>
				<div class="wf-help mb-2">{{ $t('plugins.WorkshopService.access.who_mode_note') }}</div>
				<access-state :state="state" :detail="detail" @retry="load()">
					<template v-if="ready">
						<access-can-person v-if="selectedView" :key="selected.name" :view="selectedView" :caps="caps" :focus-area="selected.area" @back="selected = null" @go="g => $emit('go', g)" />
						<access-can-grid v-else :rows="grid" @open="selected = $event" />
					</template>
				</access-state>
			</v-card-text>
		</v-card>
	</div>
</template>

<script>
'use strict'

import AccessState from './AccessState.vue'
import AccessCanGrid from './AccessCanGrid.vue'
import AccessCanPerson from './AccessCanPerson.vue'
import { roleMixin } from './role-mixin.js'
import { currentIdentity } from './workshop-api.js'
import { accessApi } from './access-api.js'
import { roleGroupsOf } from './access-people-view.js'
import { stateOfError } from './access-profile-view.js'
import { BATCH_MAX, askPlan, chunk, gridRows, personView, rowsByCap } from './who-can-view.js'

const SLOW_MS = 15000
// every request assumes the mode the machine is in now (the same for all of them)
const CONTEXT = Object.freeze({ modeNow: true })

export default {
	name: 'AccessCan',
	components: { AccessState, AccessCanGrid, AccessCanPerson },
	mixins: [roleMixin],
	props: { focus: { type: Object, default: null } },
	data() {
		return { focused: 0, caps: [], views: [], selected: null, ready: false, loading: false, failed: '', failure: null, slow: false }
	},
	computed: {
		// users turned off (or none created): there is nobody to ask about
		usersOff() {
			void this.identityTick
			const i = currentIdentity()
			return !!i && (i.configured === false || !!i.users_disabled)
		},
		grid() { return gridRows(this.views) },
		selectedView() { return this.selected ? this.views.find(v => v.name === this.selected.name) || null : null },
		state() {
			if (this.failed) return this.failed
			if (this.loading && !this.ready) return this.slow ? 'slow' : 'loading'
			return ''
		},
		detail() { return this.failure ? this.failure.message || '' : '' }
	},
	watch: {
		'focus.n'() { this.applyFocus() }
	},
	created() {
		this.load()
	},
	beforeDestroy() {
		clearTimeout(this.timer)
	},
	methods: {
		applyFocus() {
			if (!this.ready || !this.focus || !this.focus.n || this.focused === this.focus.n) return
			this.focused = this.focus.n
			const hit = this.views.find(v => v.name.toLowerCase() === String(this.focus.name || '').toLowerCase())
			if (hit) this.selected = { name: hit.name, area: '' }
		},
		// one person: what they have and ONE answer per capability, in as many calls as the limit of a batch asks (a call never carries more than BATCH_MAX)
		async viewOf(user, caps, groups) {
			const plan = askPlan(caps, CONTEXT)
			const [person, answers] = await Promise.all([
				accessApi.personGet(user.name).catch(() => null),
				Promise.all(chunk(plan.items, BATCH_MAX).map(items => accessApi.checkMany(user.name, items).then(r => (r && r.items) || [])))
			])
			const rows = rowsByCap(plan, [].concat(...answers))
			return personView({ name: user.name, role: user.role, person: person || { role: user.role }, caps, rows, roleGroups: roleGroupsOf(user.name, groups) })
		},
		async load() {
			this.loading = true
			this.slow = false
			this.failed = ''
			this.failure = null
			clearTimeout(this.timer)
			this.timer = setTimeout(() => { this.slow = true }, SLOW_MS)
			const gen = this._gen = (this._gen || 0) + 1
			try {
				const caps = ((await accessApi.capabilities()) || {}).capabilities || []
				const groups = await accessApi.groupsList().catch(() => null)
				const users = this.usersOff ? [] : ((await accessApi.people()) || {}).users || []
				const views = await Promise.all(users.map(u => this.viewOf(u, caps, groups)))
				if (gen !== this._gen) return
				this.caps = caps
				this.views = views
				this.ready = true
				if (this.selected && !views.some(v => v.name === this.selected.name)) this.selected = null
			} catch (e) {
				if (gen !== this._gen) return
				this.failure = e
				this.failed = stateOfError(e)
			} finally {
				if (gen === this._gen) {
					this.loading = false
					clearTimeout(this.timer)
				}
			}
			this.applyFocus()
		}
	}
}
</script>
