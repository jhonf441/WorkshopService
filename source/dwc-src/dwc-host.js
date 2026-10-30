'use strict'

// The ONE place where the Vue plugins touch DuetWebControl 3.7. Everything else in vue/ (shared pieces and plugins) asks
// this module for the object model, the connection, the router helpers and the texts, so a change of the DWC surface is
// fixed here and nowhere else.
//
// "DuetWebControl" is not a module on disk: scripts/build-plugin.js turns the import into `window.DWC`, which DWC fills with
// every export of its plugin API, stores and composables (see PLUGINS.md of the DWC tree). In the node tests this file is
// replaced by tests/lib/dwc-host-fake.js (see the loaders of the plugin tests).
//
//   import { machineModel, isConnected, sendCode, i18n, onLocaleChange } from './dwc-host.js'
//
// Reactivity: machineModel() returns the reactive model of the Pinia machine store, so reading it inside computed() or a
// template tracks it. Components get the router with useRouter() (vue-router is an external of the build), not from here.

import { useMachineStore, useSettingsStore, useMenuStore, registerCategory, unregisterRoute, Events, i18n as dwcI18n } from 'DuetWebControl'
import { watch } from 'vue'

// ---- machine ----

export function machineStore() {
	return useMachineStore()
}

// machine.model of DWC (reactive). plugins is a ModelDictionary (a Map): plugins.get('WorkshopService')
export function machineModel() {
	return useMachineStore().model
}

export function modelPlugins() {
	return useMachineStore().model.plugins
}

// true when DWC has a connection to the machine (3.6: store.getters.isConnected)
export function isConnected() {
	return useMachineStore().isConnected
}

// Sends G-code through DWC. The workshop pages should use the central API of the service instead (workshop-api.js); this is for
// the few cases that need the raw code. THE one adapter of the Vue plugins: sendCode('G28') or sendCode({ code, log, noWait }).
// DWC 3.7's store takes (code, fromInput, logReply, noWait): log defaults to true (the reply goes to the console log, as in 3.6),
// pass log: false for the silent reads. Resolves with the reply text.
export function sendCode(arg) {
	const o = typeof arg === 'string' ? { code: arg } : arg
	return useMachineStore().sendCode(o.code, false, o.log !== false, o.noWait === true)
}

// ids of the DWC plugins that are enabled (3.7 keeps ONE list: settings.enabledPlugins; 3.6 had a machine one and a global one)
export function enabledPlugins() {
	const list = useSettingsStore().enabledPlugins
	return Array.isArray(list) ? list : null
}

// ---- texts ----

// DWC's vue-i18n instance (composition mode: the translate functions live in i18n.global). This adapter keeps the call shapes
// the 3.6 code used (i18n.t(key, params), i18n.t(key, 'es'), i18n.te(key, 'es'), i18n.locale) so the pure modules and the
// tests do not change:
//   t(key)  t(key, params)  t(key, locale)  t(key, locale, params)  t(key, params, locale)
// NOTE 3.7 / vue-i18n 11: a message must escape '|' (plural separator) and '@' (linked message) as {'|'} and {'@'}; the
// test tests/vue-i18n-syntax.test.js checks every catalog of vue/.
export const i18n = {
	get locale() {
		return dwcI18n.global.locale.value
	},
	t(key, a, b) {
		const locale = typeof a === 'string' ? a : (typeof b === 'string' ? b : undefined)
		const params = [a, b].find(x => x !== null && typeof x === 'object')
		return dwcI18n.global.t(key, params || {}, locale ? { locale } : {})
	},
	te(key, locale) {
		return locale ? dwcI18n.global.te(key, locale) : dwcI18n.global.te(key)
	}
}

// fn(newLocale) when the person changes the language of DWC (a watcher outside any component: it lives as long as the page)
export function onLocaleChange(fn) {
	return watch(() => dwcI18n.global.locale.value, fn)
}

// ---- router helpers (the router itself comes from useRouter() in a component) ----

// true when DWC has a page at that path (the plugin that owns it is installed and enabled). DWC ends its route table with a
// catch-all page ([...notFound].vue), so a path that only the catch-all matches does not exist.
export function pathExists(router, path) {
	try {
		const matched = router.resolve(path).matched
		if (!matched || !matched.length) return false
		const last = matched[matched.length - 1]
		return !/notFound|pathMatch|\(\.\*\)/.test(String(last.path) + ' ' + String(last.name || ''))
	} catch (e) {
		return false
	}
}

// ---- plugin lifecycle ----

// DWC 3.7 does not remove anything when a plugin is stopped (no script, route, menu entry or timer): it only emits
// 'dwcPluginUnloaded' with the plugin id. Run fn once when OUR plugin is unloaded, to undo what outlives a component (timers,
// recorders, routes, menu groups). Without it a stop followed by a start keeps the first component (registerRoute is idempotent
// by path) and the old timers. Returns a function that cancels the subscription.
export function onPluginUnload(pluginId, fn) {
	const same = id => String(id).toLowerCase() === String(pluginId).toLowerCase()
	const handler = id => {
		if (!same(id)) return
		Events.off('dwcPluginUnloaded', handler)
		try {
			fn()
		} catch (e) {
			console.warn(pluginId + ': cleanup on unload failed', e)
		}
	}
	Events.on('dwcPluginUnloaded', handler)
	return () => Events.off('dwcPluginUnloaded', handler)
}

// Removes the route and its drawer entry (unregisterRoute) and, when no item of the group `categoryName` is left, the drawer
// group that ensureMenuCategory() added to the menu store.
export function removePluginRoute(path, categoryName) {
	try {
		unregisterRoute(path)
	} catch (e) {
		console.warn('unregisterRoute failed for ' + path, e)
	}
	if (categoryName) removeMenuCategoryIfEmpty(categoryName)
}

// ---- menu ----

// A drawer group of our own ("Monitor"). In 3.7 registerCategory() only records the group in the plugin registry; the navigation
// drawer lists the groups of the menu store, so the group is also added there (once). Call it BEFORE registerRoute() with the
// same `name`; the routes then use { [name]: { ... } } as usual. captionKey is an i18n key (registered messages).
export function ensureMenuCategory(name, icon, captionKey, order = 45) {
	registerCategory(name, icon, captionKey)
	const menu = useMenuStore()
	const key = name.toLowerCase()
	if (!menu.categories.some(c => c.key === key)) {
		menu.categories.push({ key, icon, captionKey, order })
	}
}

// Takes the group out of the drawer when it has no page left (the last Monitor plugin was stopped). Only a group that
// ensureMenuCategory() pushed is touched; items of other plugins keep it alive.
export function removeMenuCategoryIfEmpty(name) {
	const menu = useMenuStore()
	const key = name.toLowerCase()
	if ((menu.pluginItems || []).some(i => i.category === key)) return
	const i = menu.categories.findIndex(c => c.key === key)
	if (i !== -1) menu.categories.splice(i, 1)
}
