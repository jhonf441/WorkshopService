'use strict'

// Control page of the workshop backend (API of the service,
// air/light/LEDs). The Consumption, Motors and Activity pages were split into
// their own plugins (WorkshopPower / WorkshopMotors / WorkshopActivity,
// TallerPlugins repo, vue/ folder) on 2026-10-08; they keep reading the data
// published by this backend.

import './i18n-register.js'
import { registerRoute } from 'DuetWebControl'
import { onPluginUnload, removePluginRoute } from './dwc-host.js'
import './language-reload.js' // the page loads again when the DWC language changes
import './safe-saving.js' // power cut: save with a backup and in one step (copy of TallerPlugins vue/_shared)

import WorkshopService from './WorkshopService.vue'
import './theme.css'

registerRoute(WorkshopService, {
	Plugins: {
		WorkshopService: {
			icon: 'mdi-flash',
			caption: 'plugins.WorkshopService.page.system_service',
			path: '/Plugins/WorkshopService'
		}
	}
});

// DWC 3.7 does not undo anything when a plugin is stopped: take the page and its "System service" menu entry out, so that a stopped
// service leaves no dead route and a later start registers the page again (registerRoute is idempotent by path).
onPluginUnload('WorkshopService', () => {
	removePluginRoute('/Plugins/WorkshopService')
})
