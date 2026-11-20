'use strict'

// The areas of the workshop in plain words, for the tab "Who can do what" (Access). PURE: no imports, no DOM, no translator. The service groups its
// capabilities in nine categories (machine, jobs, ...); that is too coarse for a person (machine alone has 17), so the page groups the same capabilities in
// ten areas. Nothing here decides access: it only says which capability is shown in which area and which operation stands for a capability when the
// service is asked (access.check). tests/access-areas.test.js reads dsf/permission_caps.py and fails when a capability is in no area or in two.
//
//   AREAS                       [{ id, icon, caps: [capability id] }] in the order they are shown; titles are the keys access.area_<id> / access.area_short_<id>
//   areaOf(capId)               the id of the area of a capability, or ''
//   representativeOp(cap)       the operation asked for a capability (cap = an item of roles.list: { id, ops }), or '' when no operation stands for it
//   OP_OVERRIDES                the capabilities whose operations are only patterns (roles.*): the operation asked instead

export const AREAS = Object.freeze([
	{ id: 'movement', icon: 'mdi-axis-arrow', caps: ['machine.move', 'machine.motors', 'machine.takeover', 'machine.height', 'machine.workarea', 'machine.procedures', 'machine.try', 'machine.stop'] },
	{ id: 'tuning', icon: 'mdi-tune', caps: ['machine.view', 'machine.meshes', 'machine.maintenance', 'machine.config_view', 'machine.config_apply', 'machine.workstate', 'machine.guard', 'machine.hardware_params', 'machine.config_restore', 'system.bed_calibration', 'system.bedzones', 'system.pelletlayers', 'system.layerrecipes'] },
	{ id: 'jobs', icon: 'mdi-play-circle-outline', caps: ['jobs.view', 'jobs.run', 'jobs.manage', 'jobs.air'] },
	{ id: 'files', icon: 'mdi-folder-outline', caps: ['jobs.library', 'jobs.library_manage', 'config.database', 'config.database_admin'] },
	{ id: 'lights', icon: 'mdi-lightbulb-outline', caps: ['lights.view', 'lights.use', 'lights.config', 'lights.m950'] },
	{ id: 'energy', icon: 'mdi-flash-outline', caps: ['energy.view', 'energy.timers', 'energy.meter', 'energy.shutdown', 'energy.reset'] },
	{ id: 'camera', icon: 'mdi-camera-outline', caps: ['camera.view', 'camera.capture', 'camera.vision', 'camera.manage', 'camera.settings', 'camera.relay'] },
	{ id: 'activity', icon: 'mdi-bell-outline', caps: ['activity.view', 'activity.write', 'activity.settings', 'activity.delete'] },
	{ id: 'service', icon: 'mdi-cog-outline', caps: ['config.view', 'config.api', 'config.edit', 'config.bridge', 'config.critical', 'processes.control', 'service.restart', 'system.plugins', 'system.view'] },
	{ id: 'security', icon: 'mdi-shield-account-outline', caps: ['security.session', 'security.audit', 'security.audit_tools', 'security.users', 'security.roles', 'security.access', 'security.keys', 'security.passwords'] }
].map(a => Object.freeze(Object.assign({}, a, { caps: Object.freeze(a.caps) }))))

export const OP_OVERRIDES = Object.freeze({
	'security.users': 'users.list',
	'security.roles': 'roles.list',
	'security.access': 'access.profiles.list',
	'security.keys': 'keys.list',
	'security.passwords': 'password.status'
})

export function areaOf(capId) {
	const a = AREAS.find(x => x.caps.indexOf(capId) >= 0)
	return a ? a.id : ''
}

export function representativeOp(cap) {
	const c = cap || {}
	if (Object.prototype.hasOwnProperty.call(OP_OVERRIDES, c.id)) return OP_OVERRIDES[c.id]
	const ops = Array.isArray(c.ops) ? c.ops : []
	const plain = ops.find(o => typeof o === 'string' && o && o.indexOf('*') < 0)
	return plain || ''
}
