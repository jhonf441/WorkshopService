'use strict'

// How the page names what an access key holds: its classes, its capabilities (`cap:<id>`) and its operations. PURE. Shared by Connections > Access keys
// (ApiKeys.vue) and Access > Access keys (AccessKeyCard.vue) so both say the same words. The ids are the identity the service stores; this only draws them.
//
//   CAP_PREFIX            'cap:' (keys.list answers it as cap_prefix)
//   KEY_CLASSES           the classes of an operation (read, write, motion, stop, power, admin)
//   classKey(c)           catalog key of the name of a class, relative to plugins.WorkshopService
//   isCap(entry)          the entry is a capability
//   capOf(catalog, entry) the capability of the list of the service (roles.list) or null
//   capTitle(catalog, entry)  its title, or the id without the prefix while the list is not there

export const CAP_PREFIX = 'cap:'
export const KEY_CLASSES = Object.freeze(['read', 'write', 'motion', 'stop', 'power', 'admin'])

export function classKey(c) {
	return 'keys.class_' + c
}

export function isCap(entry) {
	return String(entry).startsWith(CAP_PREFIX)
}

export function capOf(catalog, entry) {
	const id = String(entry).slice(CAP_PREFIX.length)
	return (catalog || []).find(c => c.id === id) || null
}

export function capTitle(catalog, entry) {
	const c = capOf(catalog, entry)
	return c ? c.title : String(entry).slice(CAP_PREFIX.length)
}
