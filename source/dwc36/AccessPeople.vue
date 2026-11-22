<template>
	<!-- Access > People and groups, read only (step 2 of DISENO-PANTALLAS): the lists, the card of a person or of a group and "What this person can do".
	     Operations: users.list (the people), access.groups.list / get, access.person.get and access.check, all through access-api.js. With users turned off
	     there are no people to list or to try (the fixed notice is drawn by the section); the groups can still be read. -->
	<div ref="box" class="access-people">
		<v-card class="mb-3">
			<v-card-title class="text-subtitle-1">
				{{ $t('plugins.WorkshopService.access.people_title') }}
				<v-spacer />
				<v-btn small outlined class="access-touch" :loading="loading" @click="load()"><v-icon left small>mdi-refresh</v-icon>{{ $t('plugins.WorkshopService.access.common_refresh') }}</v-btn>
			</v-card-title>
			<v-card-text>
				<access-state :state="state" :detail="detail" @retry="load()">
					<template v-if="groups">
						<access-person-card v-if="selected && selected.kind === 'person'" :key="'p:' + selected.name" :name="selected.name" :role-groups="selectedRoleGroups" :users-off="usersOff" :groups="groups" @back="selected = null" @changed="load()" @see-can="n => $emit('see-can', n)" />
						<access-group-card v-else-if="selected" :key="'g:' + selected.name" :name="selected.name" :users="usersOff ? [] : users" :groups="groups" :damaged="!!groups.damaged" @back="selected = null" @changed="load()" />
						<template v-else>
							<div class="sv-tbar">
								<div class="access-kinds" role="group">
									<button v-for="v in views" :key="v" type="button" class="access-kind access-touch" :class="{ 'is-on': view === v }" :aria-pressed="view === v ? 'true' : 'false'" @click="view = v">{{ $t('plugins.WorkshopService.access.people_view_' + v) }}</button>
								</div>
								<sv-text-field v-model="text" icon="mdi-magnify" type="search" class="access-search" :placeholder="$t('plugins.WorkshopService.access.common_search')" :aria-label="$t('plugins.WorkshopService.access.common_search')" />
							</div>
							<access-people-list v-if="view === 'people'" :rows="people" @open="selected = { kind: 'person', name: $event }" />
							<template v-else>
								<access-group-new :groups="groups" :locked="!!groups.damaged || !canDo('access.groups.set')" @created="load()" />
								<access-group-list :rows="groupList" @open="selected = { kind: 'group', name: $event }" />
							</template>
						</template>
					</template>
				</access-state>
			</v-card-text>
		</v-card>
	</div>
</template>

<script>
'use strict'

import SvTextField from './ui/SvTextField.vue'
import AccessState from './AccessState.vue'
import AccessPeopleList from './AccessPeopleList.vue'
import AccessGroupList from './AccessGroupList.vue'
import AccessPersonCard from './AccessPersonCard.vue'
import AccessGroupCard from './AccessGroupCard.vue'
import AccessGroupNew from './AccessGroupNew.vue'
import { roleMixin } from './role-mixin.js'
import { currentIdentity } from './workshop-api.js'
import { accessApi } from './access-api.js'
import { groupRows, peopleRows, roleGroupsOf } from './access-people-view.js'
import { stateOfError } from './access-profile-view.js'
import { peopleFocus } from './access-go.js'
import { reveal } from './reveal.js'

const SLOW_MS = 15000

export default {
	components: { SvTextField, AccessState, AccessPeopleList, AccessGroupList, AccessPersonCard, AccessGroupCard, AccessGroupNew },
	mixins: [roleMixin],
	props: { focus: { type: Object, default: null } }, // { name, n }: open this person or group (asked from Security); n changes with every request
	data() {
		return { focused: 0, groups: null, users: [], persons: {}, view: 'people', views: ['people', 'groups'], text: '', selected: null, loading: false, failed: '', failure: null, slow: false }
	},
	computed: {
		// users turned off (or none created): everybody is an administrator today, there is nobody to list or to try
		usersOff() {
			void this.identityTick
			const i = currentIdentity()
			return !!i && (i.configured === false || !!i.users_disabled)
		},
		people() {
			return peopleRows(this.usersOff ? [] : this.users, this.groups, this.persons, this.text)
		},
		groupList() {
			return groupRows(this.groups, this.text)
		},
		selectedRoleGroups() {
			return this.selected && this.selected.kind === 'person' ? roleGroupsOf(this.selected.name, this.groups) : []
		},
		// one state at a time, the first that applies (section 5)
		state() {
			if (this.failed) return this.failed
			if (this.loading && !this.groups) return this.slow ? 'slow' : 'loading'
			if (this.groups && this.groups.damaged) return 'damaged'
			if (this.groups && !this.canDo('access.attach')) return 'read_only'
			return ''
		},
		detail() {
			return this.failure ? this.failure.message || '' : ''
		},
		damaged() {
			return this.groups ? !!this.groups.damaged : null
		}
	},
	watch: {
		'focus.n'() {
			this.applyFocus()
		},
		// the groups list tells by itself that the access file is damaged: the page shows it in its header
		damaged(v) { if (v !== null) this.$emit('damaged', v) }
	},
	created() {
		this.load()
	},
	beforeDestroy() {
		clearTimeout(this.timer)
	},
	methods: {
		// the person or group a button of Security named: shown once per request, when the lists are there
		applyFocus() {
			if (!this.groups || this.loading || !this.focus || !this.focus.n || this.focused === this.focus.n) return
			this.focused = this.focus.n
			const hit = peopleFocus(this.usersOff ? [] : this.users, this.groups, this.focus.name)
			if (!hit) return
			this.text = ''
			this.view = hit.kind === 'person' ? 'people' : 'groups'
			this.selected = hit
			// scroll the card into view and flash it
			this.$nextTick(() => this.$root && this.$refs.box && reveal(this.$refs.box.querySelector('.access-person-card, .access-group-card'), this.$vuetify && this.$vuetify.application && this.$vuetify.application.top))
		},
		async load() {
			this.loading = true
			this.slow = false
			this.failed = ''
			this.failure = null
			clearTimeout(this.timer)
			this.timer = setTimeout(() => { this.slow = true }, SLOW_MS)
			try {
				this.groups = await accessApi.groupsList()
				if (this.usersOff) {
					this.users = []
					this.persons = {}
				} else {
					this.users = ((await accessApi.people()) || {}).users || []
					// what each person has decides who governs them; one that cannot be read is shown as such, not left out
					const got = await Promise.all(this.users.map(u => accessApi.personGet(u.name).catch(() => null)))
					const persons = {}
					this.users.forEach((u, i) => { persons[u.name] = got[i] })
					this.persons = persons
				}
			} catch (e) {
				this.groups = null
				this.failure = e
				this.failed = stateOfError(e)
			} finally {
				this.loading = false
				clearTimeout(this.timer)
			}
			this.applyFocus()
		}
	}
}
</script>
