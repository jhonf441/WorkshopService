'use strict'

// The sentence of a refusal of the service (the `sentence` that access-people-view.js checkOutcome arranges: key, params, paramKeys) as text, for the
// components that draw it: the result of a test (AccessCheckResult) and the lines of "Who can do what". Names (profiles, rules, roles) come from
// display-names.js through displayNamesMixin: the ids are never drawn.

import { displayNamesMixin } from './display-names-mixin.js'
import { isBaseRole } from './access-people-view.js'

const AREA = 'plugins.WorkshopService.access.'

export const accessSentenceMixin = {
	mixins: [displayNamesMixin],
	methods: {
		roleLabel(r) {
			return isBaseRole(r) ? this.$t('plugins.WorkshopService.users.role_' + r) : r
		},
		sentenceText(s, role) {
			const params = Object.assign({ role: this.roleLabel(role) }, s.params)
			if (params.tier) params.tier = this.roleLabel(params.tier)
			if (params.profile !== undefined) {
				if (params.rule !== undefined) params.rule = this.ruleText(params.rule, params.profile)
				params.profile = this.profileText(params.profile)
			}
			if (params.ceiling !== undefined) params.ceiling = this.profilesText(params.ceiling)
			Object.keys(s.paramKeys || {}).forEach(k => { params[k] = s.paramKeys[k].map(x => this.$t(AREA + x)).join(', ') })
			return this.$t(AREA + s.key, params)
		}
	}
}
