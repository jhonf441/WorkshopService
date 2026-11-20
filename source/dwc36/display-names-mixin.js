'use strict'

// The text of the readable names of display-names.js, for the components that print a profile, a rule, an operation entry, a role, a way in or a
// cause to a person. Display only: the id stays the identity (never send the text to the service). An id without a readable name is returned as it is.

import { causeKey, codeKey, entryLabel, profileLabel, roleKey, ruleLabel, viaKey } from './display-names.js'

const AREA = 'plugins.WorkshopService.'

export const displayNamesMixin = {
	methods: {
		nameText(label) {
			return label.key ? this.$t(AREA + label.key, label.params || {}) : ''
		},
		profileText(id) {
			const l = profileLabel(id)
			return l.key ? this.$t(AREA + l.key, l.params) : String(id)
		},
		// a list of ids written as 'a, b' (a sentence parameter)
		profilesText(ids) {
			return String(ids || '').split(', ').filter(Boolean).map(p => this.profileText(p)).join(', ')
		},
		profileCode(id) {
			return profileLabel(id).code
		},
		ruleText(rule, profile) {
			const l = ruleLabel(rule, profile)
			return l.key ? this.$t(AREA + l.key) : String(rule)
		},
		ruleCode(rule, profile) {
			return ruleLabel(rule, profile).code
		},
		entryText(entry) {
			const l = entryLabel(entry)
			return l.key ? this.$t(AREA + l.key) : String(entry)
		},
		entryCode(entry) {
			return entryLabel(entry).code
		},
		roleText(role) {
			const k = roleKey(role)
			return k ? this.$t(AREA + k) : String(role)
		},
		viaText(via) {
			const k = viaKey(via)
			return k ? this.$t(AREA + k) : String(via)
		},
		causeText(cause) {
			const k = causeKey(cause)
			return k ? this.$t(AREA + k) : String(cause)
		},
		codeText(code) {
			const k = codeKey(code)
			return k ? this.$t(AREA + k) : this.$t(AREA + 'access.audit_code_unknown')
		}
	}
}
