'use strict'

// Control page of the workshop backend (API of the service,
// air/light/LEDs). The Consumption, Motors and Activity pages were split into
// their own plugins (WorkshopPower / WorkshopMotors / WorkshopActivity,
// TallerPlugins repo, vue/ folder) on 2026-10-08; they keep reading the data
// published by this backend.

import './i18n-register.js'
import { registerRoute } from '../../routes'
import './safe-saving.js' // corte de luz: guardar con respaldo y en un paso (copia de TallerPlugins/vue/_shared)

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
