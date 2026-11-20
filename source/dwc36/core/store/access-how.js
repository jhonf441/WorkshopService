'use strict'

// "How access works": the ONE glossary of Access. The card of the host (sections/access/AccessHow.vue) draws it; every "?" next to a technical word asks it to open and
// to mark that word. The two do not know each other: the request lives here (like access-focus.js).
//
//   TERMS            the words of the glossary, in the order they are told (texts: access_help.term_<id>_name / _def / _example)
//   TAB_PURPOSES     the tabs of Access that say what they are for (text: access_help.purpose_<tab>)
//   how              { want, term, n }  want = the card must be open; term = the word to mark; n grows with every request
//   showTerm(term)   open the card and mark the word

import Vue from 'vue'

export const TERMS = Object.freeze(['base_role', 'own_role', 'profile', 'rule', 'group', 'ceiling', 'capability', 'key'])
export const TAB_PURPOSES = Object.freeze(['people', 'profiles', 'templates', 'can', 'keys', 'settings'])

// the five nodes of the flow, in order, and the icon of each node and of each word (mdi, the set the page already has)
export const STEPS = Object.freeze(['person', 'role', 'profiles', 'ceiling', 'result'])
export const STEP_ICONS = Object.freeze({ person: 'mdi-account-outline', role: 'mdi-shield-account-outline', profiles: 'mdi-clipboard-list-outline', ceiling: 'mdi-arrow-collapse-up', result: 'mdi-check-circle-outline' })
export const TERM_ICONS = Object.freeze({ base_role: 'mdi-shield-account-outline', own_role: 'mdi-account-cog-outline', profile: 'mdi-clipboard-list-outline', rule: 'mdi-format-list-checks', group: 'mdi-account-group-outline', ceiling: 'mdi-arrow-collapse-up', capability: 'mdi-puzzle-outline', key: 'mdi-key-outline' })
export const RULES = Object.freeze(['stop', 'deny', 'none', 'admin'])   // the short phrases under the flow (texts: access_help.rule_<id>)

export const how = Vue.observable({ want: false, term: '', n: 0 })

export function showTerm(term) {
	how.term = TERMS.indexOf(term) >= 0 ? term : ''
	how.want = true
	how.n += 1
}
