<template>
	<!-- "Remove" of a custom profile (access.profiles.remove). Off, with the reason written, while somebody has it (the service refuses that anyway) and while the
	     access file is damaged. A touch opens the same before / after dialog as every change (the profile as it is, and nothing); the verb removes it.
	       <access-profile-remove :row="{ name, users: [], groups: [] }" :damaged="false" @removed="name => ..." /> -->
	<span class="access-remove">
		<v-btn small outlined class="access-touch" :disabled="blocked" @click="ask()">{{ $t('plugins.WorkshopService.access.common_remove') }}</v-btn>
		<span v-if="holders.length" class="wf-help access-remove-why">{{ $t('plugins.WorkshopService.access.profiles_remove_in_use', { names: holders.join(', ') }) }}</span>
		<span v-if="failure" class="access-problem" role="alert">{{ failure }}</span>
		<access-profile-change v-if="doc" :value="true" :title="$t('plugins.WorkshopService.access.change_profile_remove', { name: row.name })" :confirm-label="$t('plugins.WorkshopService.access.common_remove')" :diff="diff" :attached="{ users: row.users, groups: row.groups }" :removing="true" :busy="busy" :error="error" @input="close" @confirm="remove" />
	</span>
</template>

<script>
'use strict'

import AccessProfileChange from './AccessProfileChange.vue'
import { accessApi } from './access-api.js'
import { diffProfile } from './access-diff.js'

export default {
	components: { AccessProfileChange },
	props: {
		row: { type: Object, required: true }, // { name, users, groups } of profileRows()
		damaged: { type: Boolean, default: false }
	},
	data() {
		return { doc: null, busy: false, error: '', failure: '' }
	},
	computed: {
		holders() {
			return (this.row.users || []).concat(this.row.groups || [])
		},
		blocked() {
			return this.damaged || this.holders.length > 0
		},
		diff() {
			return diffProfile(this.doc, null)
		}
	},
	methods: {
		async ask() {
			this.failure = ''
			this.error = ''
			try {
				this.doc = (await accessApi.profilesGet(this.row.name)).document
			} catch (e) {
				this.failure = (e && e.message) || String(e)
			}
		},
		close() {
			if (!this.busy) this.doc = null
		},
		async remove() {
			this.busy = true
			this.error = ''
			try {
				await accessApi.profilesRemove(this.row.name, { confirm: true })
				this.doc = null
				this.$emit('removed', this.row.name)
			} catch (e) {
				this.error = (e && e.message) || String(e)
			} finally {
				this.busy = false
			}
		}
	}
}
</script>

<style>
.access-remove { display: inline-flex; align-items: center; flex-wrap: wrap; gap: 6px; }
</style>
