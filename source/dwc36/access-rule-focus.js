'use strict'

// Small pure rules of the rules editor of a profile (AccessRulesEditor.vue, AccessRuleEditor.vue); the components do the DOM.
//
//   addBlock(rules, max, issuesOf)   why a new rule cannot be added now: { key, params } (key of the area `access`) or null when it can
//   needsScroll(rect, viewH, min)    (reveal.js, re-exported) the 320 px placement rule
//   ruleName(rule, i)                what the person calls the rule in a sentence: its name, or its place when it has none yet

import { MIN_VISIBLE, RESULT_FLASH_MS, needsScroll } from './reveal.js'

export { MIN_VISIBLE, needsScroll }
export const FLASH_MS = RESULT_FLASH_MS

export function ruleName(rule, i) {
	return rule && typeof rule.id === 'string' && rule.id ? rule.id : String(i + 1)
}

export function addBlock(rules, max, issuesOf) {
	const list = Array.isArray(rules) ? rules : []
	if (list.length >= max) return { key: 'builder_add_block_max', params: { max } }
	for (let i = 0; i < list.length; i++) {
		const r = list[i]
		if (!r || !Array.isArray(r.operations) || !r.operations.length) return { key: 'builder_add_block_empty', params: { rule: ruleName(r, i) } }
	}
	for (let i = 0; i < list.length; i++) {
		if (typeof issuesOf === 'function' && issuesOf(list[i], i).length) return { key: 'builder_add_block_fix', params: { rule: ruleName(list[i], i) } }
	}
	return null
}
