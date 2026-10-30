'use strict'

// THE colors of the plugins (design family, 2026-10-28): the badge of the page bar and the default color of the sections, one place.
// Every plugin has its own color, all different, all dark enough for a white icon (contrast with white >= 3:1;
// tests/family-design.test.js checks both). The page root declares `--wf-badge` from here (PageHeader.vue does it for its bar);
// the open section may take another color (section-colors.js of the plugin, `--wf-sec`), the plugin color is the default.
// WorkshopService/dwc-src and dwc36 hold a copy made by tools/build-family.js: edit only vue/_shared/plugin-colors.js.

export const PLUGIN_COLORS = {
	WorkshopMachine: { badge: '#1565c0', section: '#1565c0' },
	WorkshopPrinting: { badge: '#e65100', section: '#e65100' },
	WorkshopWorkbench: { badge: '#558b2f', section: '#558b2f' },
	WorkshopVision: { badge: '#ad1457', section: '#ad1457' },
	WorkshopMotors: { badge: '#6a40b0', section: '#6a40b0' },
	WorkshopLights: { badge: '#b26a00', section: '#b26a00' },
	WorkshopPower: { badge: '#00838f', section: '#00838f' },
	WorkshopActivity: { badge: '#00796b', section: '#00796b' },
	WorkshopPiHealth: { badge: '#2e7d32', section: '#2e7d32' },
	WorkshopRS485: { badge: '#3f51b5', section: '#3f51b5' },
	WorkshopCamera: { badge: '#6d4c41', section: '#6d4c41' },
	WorkshopService: { badge: '#37474f', section: '#37474f' }
}

const FALLBACK = '#1976d2'

export function pluginBadge(id) {
	return PLUGIN_COLORS[id] ? PLUGIN_COLORS[id].badge : FALLBACK
}

export function pluginSection(id) {
	return PLUGIN_COLORS[id] ? PLUGIN_COLORS[id].section : FALLBACK
}
