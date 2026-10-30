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
// true when the plugin of that key is installed and enabled. store = this.$store (reactive: it reads the
// plugin list and the enabled list). A JS plugin that loaded in this page counts as active.
export function pluginActive(store, key) {
	const ids = IDS[key] || [key];
	const cargados = window.__workshop && window.__workshop.versions;
	if (cargados && ids.some(id => cargados[id])) return true;
	const st = store && store.state;
	if (!st || !pluginOf(st.machine.model.plugins, key)) return false;
	const ms = st.machine.settings && st.machine.settings.enabledPlugins;
	const gs = st.settings && st.settings.enabledPlugins;
	if (!Array.isArray(ms) && !Array.isArray(gs)) return true; // list not loaded yet: do not hide
	return ids.some(id => (ms || []).includes(id) || (gs || []).includes(id));
}

// true when DWC has a page at that route (the plugin that owns it is installed and enabled).
// router = this.$router; unknown routes fall on the catch-all '*'. Not reactive: call it from render or methods.
export function pathExists(router, path) {
	try {
		const m = router && router.resolve(path).route.matched;
		return !!(m && m.length && m[m.length - 1].path !== '*');
	} catch (e) {
		return false;
	}
}
