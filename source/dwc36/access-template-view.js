'use strict'

// Pure helpers of Access > Templates: from a template (access-templates.js) to the draft document the profile editor opens on, the lines the cards draw
// (area by area, with the names of the capabilities that the service gave) and the change the "Give to a person" flow asks. No DOM, no calls, no translator:
// the components draw and call, nothing here decides access (the service validates the copy when it is saved and evaluates it).
//
//   copyName(text)                 a profile name (letters, digits, dot, underscore, hyphen; starts with a letter) made from "Copy of View only"
//   templateDoc(t, name)           the profile document of a template: one allow rule per rule of the template, capabilities as `cap:<id>`; a NEW object each time
//   titlesOf(rolesList)            { capability id: title } from the answer of roles.list (the titles the service already translated)
//   areaLines(t, titles)           [{ area, icon, items: [{ key, title, note }], }] the capabilities of a template grouped by area; note '' | 'modes' | 'laser'; a
//                                  capability without a title is left out (an id is never drawn) and counted in `missing`
//   summaryAreas(t)                the ids of the areas a template reaches, in the order they are shown
//   pluginLevel(profile)           'readonly' | 'operator' | 'admin' for plugin.<namespace>.<level>, else ''
//   pluginRows(list)               the plugin profiles of access.profiles.list as [{ name, level, rules }]
//   ownNames(list)                 the names of the own profiles of access.profiles.list
//   giveChange(user, profile)      the change that access-edit-view.js and the dialog understand (kind 'attach')

import { AREAS, areaOf } from './access-areas.js'
import { capsOf } from './access-templates.js'

const NAME_OK = /^[A-Za-z][A-Za-z0-9_.-]{0,63}$/
const PLUGIN_RE = /^plugin\..+\.(readonly|operator|admin)$/

export function copyName(text) {
	let s = String(text === null || text === undefined ? '' : text).normalize('NFD').replace(/[̀-ͯ]/g, '')
	s = s.replace(/[^A-Za-z0-9_.-]+/g, '_').replace(/^[^A-Za-z]+/, '').slice(0, 64)
	return NAME_OK.test(s) ? s : 'Copy'
}

export function templateDoc(t, name) {
	const rules = ((t && t.rules) || []).map(r => {
		const out = { id: r.id, decision: 'allow', operations: r.caps.map(c => 'cap:' + c) }
		if (r.when) out.when = { mode: r.when.mode.slice() }
		return out
	})
	return { version: 1, name: String(name || ''), rules }
}

export function titlesOf(rolesList) {
	const out = {}
	;((rolesList && rolesList.capabilities) || []).forEach(c => {
		if (c && typeof c.id === 'string' && typeof c.title === 'string' && c.title) out[c.id] = c.title
	})
	return out
}

// the note of a capability: it only holds in the modes the person has, or in the laser mode, or always
function noteOf(rule) {
	if (!rule.when) return ''
	return rule.when.mode.indexOf('laser') >= 0 && rule.when.mode.length === 1 ? 'laser' : 'modes'
}

export function areaLines(t, titles) {
	const names = titles || {}
	const note = {}
	;((t && t.rules) || []).forEach(r => r.caps.forEach(c => { if (!(c in note) || note[c]) note[c] = noteOf(r) }))
	const out = []
	let missing = 0
	AREAS.forEach(a => {
		const items = []
		capsOf(t).filter(c => areaOf(c) === a.id).forEach(c => {
			if (names[c]) items.push({ key: c, title: names[c], note: note[c] || '' })
			else missing++
		})
		if (items.length) out.push({ area: a.id, icon: a.icon, items })
	})
	out.missing = missing
	return out
}

export function summaryAreas(t) {
	return AREAS.filter(a => capsOf(t).some(c => areaOf(c) === a.id)).map(a => a.id)
}

export function pluginLevel(profile) {
	const m = PLUGIN_RE.exec(String(profile || ''))
	return m ? m[1] : ''
}

export function pluginRows(list) {
	return ((list && list.plugin) || []).filter(r => pluginLevel(r.name)).map(r => ({ name: String(r.name), level: pluginLevel(r.name), rules: r.rules | 0 }))
}

export function ownNames(list) {
	return ((list && list.profiles) || []).map(r => String(r.name))
}

export function giveChange(user, profile) {
	return { kind: 'attach', object: String(user), subject: { user: String(user) }, profile: String(profile) }
}
