'use strict'

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

// the installed Id of that key (without data: the new one)
export function idInstalled(key) {
	const ids = IDS[key] || [key];
	try {
		const pl = document.getElementById('app').__vue__.$store.state.machine.model.plugins;
		for (const id of ids) if (pl && (typeof pl.get === 'function' ? pl.get(id) : pl[id])) return id;
	} catch (e) {
		/* sin modelo todavia */
	}
	return ids[0];
}

// Rule: a plugin that refers to another one shows nothing about it (no button, link, text or card:
// hidden, not disabled) when the other one is not installed or not enabled in DWC.
// true when the plugin of that key is installed and enabled. store = this.$store (reactive: it reads the plugin list and the enabled list).
// A JS plugin that loaded in this page counts as active, unless the enabled list is loaded and does not have it: the registry keeps the entry of
// a plugin that was stopped for the seconds its poll takes to notice, and for ever when DWC loaded it from the global list. An empty list counts
// as not read yet for a JS plugin (it is running). Same answer as workshopPluginActive of src/_shared/13-presence.js.
export function pluginActive(store, key) {
	const ids = IDS[key] || [key];
	const st = store && store.state;
	// only the machine list: it is the one the plugins page changes when a plugin is stopped. DWC also loads the ids of the global (`main`)
	// list, and a stop never removes them from there, so counting that list would show a stopped plugin as active for ever.
	const ms = st && st.machine.settings && st.machine.settings.enabledPlugins;
	const enabled = Array.isArray(ms) ? ms : null;
	const loaded = window.__workshop && window.__workshop.versions;
	if (loaded && ids.some(id => loaded[id] && (!enabled || !enabled.length || enabled.includes(id)))) return true;
	if (!st || !pluginOf(st.machine.model.plugins, key)) return false;
	if (!enabled) return true; // list not loaded yet: do not hide
	return ids.some(id => enabled.includes(id));
}

// true when DWC has a page at that route. router = this.$router; unknown routes fall on the catch-all '*'. Call it from render or methods. A route
// says only that a page was registered, not that its plugin is on: DWC 3.6 cannot remove a route, so for a stopped plugin the answer stays true
// until the page is reloaded. To know whether a PLUGIN is there use pluginActive.
export function pathExists(router, path) {
	try {
		const m = router && router.resolve(path).route.matched;
		return !!(m && m.length && m[m.length - 1].path !== '*');
	} catch (e) {
		return false;
	}
}
