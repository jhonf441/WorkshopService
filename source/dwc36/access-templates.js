'use strict'

// The ready-made templates of Access > Templates, as DATA (the owner reviewed this list in chat; it is a proposal, never given to anybody by itself). PURE: no
// imports, no DOM, no translator. A template is a complete profile ready to copy: a list of rules, each an allow rule of capabilities (the ids of
// dsf/permission_caps.py) with an optional condition. The names, the sentence of what each one is for and the line of what it does NOT allow are catalog keys
// `access.templates_<id>_name` / `_use` / `_not` (es and en); no id of a capability is ever drawn: the names of the capabilities come from the service (roles.list).
// Nothing here decides access: the service validates a copy when it is saved (access.profiles.validate, access.profiles.set) and evaluates it.
// tests/access-templates.test.js feeds every template to the real validator (dsf/access_profile.py) and to the capability table.
//
//   TEMPLATES                 [{ id, use, rules: [{ id, caps: [capability id], when? }] }] in the order they are shown
//   TEMPLATE_IDS              their ids
//   ADMINISTRATOR_CARD        { id } the card of the Administrator: a role, not a profile (no rules)
//   FIXED_STOP                the stop is always allowed: it is a fixed line of every template, not a capability they list
//   MODES_WHEN / LASER_WHEN   the conditions: the modes the person has / the laser mode only
//   capsOf(template)          every capability a template lists, once, in order
//
// What a template never grants (section 5.1 of the report): machine.hardware_params, applying or restoring a configuration, and every capability of risk 4.

export const MODES_WHEN = Object.freeze({ mode: Object.freeze(['${person.modes}']) })
export const LASER_WHEN = Object.freeze({ mode: Object.freeze(['laser']) })
export const FIXED_STOP = true

const VIEW = ['machine.view', 'jobs.view', 'jobs.library', 'lights.view', 'energy.view', 'activity.view', 'system.view']
const VISITOR = VIEW.concat(['camera.view'])
// what a shift operator does at any time, and what only holds in the modes the person has (movement and jobs)
const SHIFT_PLAIN = VISITOR.concat(['lights.use', 'energy.timers', 'activity.write', 'camera.capture', 'camera.vision', 'machine.workstate'])
const SHIFT_MOVING = ['machine.move', 'machine.motors', 'jobs.run', 'jobs.air']
const TECH_EXTRA = ['machine.takeover', 'machine.height', 'machine.workarea', 'machine.procedures', 'machine.meshes', 'machine.maintenance', 'machine.config_view',
	'system.bed_calibration', 'system.bedzones', 'camera.manage', 'camera.settings', 'lights.config', 'config.view', 'processes.control', 'energy.meter']

const rule = (id, caps, when) => Object.freeze(Object.assign({ id, caps: Object.freeze(caps.slice()) }, when ? { when } : {}))
const template = (id, use, rules) => Object.freeze({ id, use, rules: Object.freeze(rules) })

export const TEMPLATES = Object.freeze([
	template('view_only', 'both', [rule('View', VIEW)]),
	template('visitor_camera', 'extra', [rule('View', VISITOR)]),
	template('shift_operator', 'both', [rule('Basic', SHIFT_PLAIN), rule('ByMode', SHIFT_MOVING, MODES_WHEN)]),
	template('laser_operator', 'extra', [rule('Basic', SHIFT_PLAIN), rule('LaserOnly', SHIFT_MOVING.concat(['jobs.manage']), LASER_WHEN)]),
	template('maintenance_tech', 'extra', [rule('Basic', SHIFT_PLAIN.concat(TECH_EXTRA)), rule('ByMode', SHIFT_MOVING, MODES_WHEN)])
])

export const TEMPLATE_IDS = Object.freeze(TEMPLATES.map(t => t.id))
export const ADMINISTRATOR_CARD = Object.freeze({ id: 'administrator' })

export function capsOf(t) {
	const out = []
	;((t && t.rules) || []).forEach(r => r.caps.forEach(c => { if (out.indexOf(c) < 0) out.push(c) }))
	return out
}
