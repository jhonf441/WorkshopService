'use strict'

import { modelPlugins, enabledPlugins, pathExists } from './dwc-host.js'

// Plugin ids (English, "Workshop*": Duet3D asks for repo = Id). Same table as WORKSHOP_IDS in src/_shared/00-core.js.

export const IDS = {
	service: ['WorkshopService'],
	rs485: ['WorkshopRS485'],
	jog: ['WorkshopJog'],
	bar: ['WorkshopControlBar'],
	camera: ['WorkshopCamera'],
	consumption: ['WorkshopPower'],
	motors: ['WorkshopMotors'],
	activity: ['WorkshopActivity'],
	health: ['WorkshopPiHealth'],
	lights: ['WorkshopLights'],
	vision: ['WorkshopVision'],
	printing: ['WorkshopPrinting'],
	workbench: ['WorkshopWorkbench'],
	machine: ['WorkshopMachine'],
	model: ['WorkshopModel'],
	modelAgent: ['WorkshopModelAgent'],
	config: ['WorkshopConfig']
};

// plugins = Map of DWC's model (or an object); null if it is not there
export function pluginOf(plugins, key) {
	const ids = IDS[key] || [key];
	for (const id of ids) {
		const p = plugins && (typeof plugins.get === 'function' ? plugins.get(id) : plugins[id]);
		if (p) return p;
	}
	return null;
}

// plugin.data of the model is a Map in 3.7 (an object in 3.6 and in test fixtures): one field of it, or undefined
export function dataOf(plugin, field) {
	const d = plugin && plugin.data;
	if (!d) return undefined;
	return typeof d.get === 'function' ? d.get(field) : d[field];
}

// the installed Id of that key (without data: the new one)
export function idInstalled(key) {
	const ids = IDS[key] || [key];
	try {
		const pl = modelPlugins();
		for (const id of ids) if (pl && (typeof pl.get === 'function' ? pl.get(id) : pl[id])) return id;
	} catch (e) {
		/* no model yet */
	}
	return ids[0];
}

// Rule: a plugin that refers to another one shows nothing about it (no button, link, text or card:
// hidden, not disabled) when the other one is not installed or not enabled in DWC.
// true when the plugin of that key is installed and enabled. Reactive (it reads the model's plugin list and the enabled list),
// so call it inside computed() or a template. A JS plugin that loaded in this page counts as active, unless the enabled list is loaded
// and does not have it: the registry keeps the entry of a plugin that was stopped for the seconds its poll takes to notice, and for ever
// when DWC loaded it from a list the plugins page does not change. An empty list counts as not read yet for a JS plugin (it is running).
// Same answer as workshopPluginActive of src/_shared/13-presence.js.
export function pluginActive(key) {
	const ids = IDS[key] || [key];
	const enabled = enabledPlugins();
	const loaded = window.__workshop && window.__workshop.versions;
	if (loaded && ids.some(id => loaded[id] && (!enabled || !enabled.length || enabled.includes(id)))) return true;
	if (!pluginOf(modelPlugins(), key)) return false;
	if (!enabled) return true; // list not loaded yet: do not hide
	return ids.some(id => enabled.includes(id));
}

// true when DWC has a page at that route. router = useRouter() of the component. It asks the router when it is called (call it from a computed
// or a method): a route says only that a page was registered, not that its plugin is on. DWC 3.6 cannot remove a route, so for a stopped plugin
// the answer stays true until the page is reloaded: to know whether a PLUGIN is there use pluginActive.
export { pathExists }
