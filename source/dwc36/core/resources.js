'use strict'

// The reads more than one screen needs, ONE resource each (a screen that owns a read alone declares it next to itself).
//
//   bedZones     bedzones.get: the zones of the bed (enabled, rev). Machine > Automations.
//   cameraRelay  camera.status: is the relay running (operator and above; a viewer reads the published state of the process instead)
//   guardSettings guard.status: the tolerances of the protection guard (settings), for "Advanced"
//   dbStatus     db.status: the database (tables, check) and its backups (last, next, list, settings). Data and backups; read again every 15 s while seen.
//   dbPlaces     db.places: where the backups may be kept (the system card, the USB drives that are connected)
//   startupPlan  startup.plan: what the workshop would change in the files of the SD (technician)
//   startupFiles startup.files: the files each plugin creates or uses and how they are now (technician)
//   startupRuns  startup.runs.list: the history of what was applied or restored, in pages of 20 (technician)
//   apiOps       api.describe: every operation of the service with its arguments (the reference of Connections; read when seen, kept 5 min)
//   readiness    readiness.list: how many steps of the start-up each plugin still has to review. The home counts them, Machine setup
//                lists them. Needs a session (a viewer may read it); read again when it is two minutes old.

import { createResource } from './store/resource.js'
import { createPagedResource } from './store/paged.js'
import { call } from './api/call.js'
import { locale } from './dwc.js'

export const readiness = createResource({
	key: 'readiness',
	needs: 'readiness.list',
	staleMs: 120000,
	load: async () => (await call('readiness.list', {}, { quiet: true })).data || { plugins: {} }
})

export const bedZones = createResource({
	key: 'bedzones',
	needs: 'bedzones.get',
	staleMs: 60000,
	load: async () => (await call('bedzones.get', {}, { quiet: true })).data || null
})

export const cameraRelay = createResource({
	key: 'camera-relay',
	needs: 'camera.status',
	staleMs: 15000,
	load: async () => (await call('camera.status', {}, { quiet: true })).data || null
})

export const guardSettings = createResource({
	key: 'guard-settings',
	needs: 'guard.status',
	staleMs: 60000,
	load: async () => (await call('guard.status', {}, { quiet: true })).data || null
})

export const dbStatus = createResource({
	key: 'db-status',
	needs: 'db.status',
	staleMs: 15000,
	load: async () => (await call('db.status', {}, { quiet: true })).data || null
})

export const dbPlaces = createResource({
	key: 'db-places',
	needs: 'db.places',
	staleMs: 30000,
	load: async () => {
		const d = (await call('db.places', {}, { quiet: true })).data
		return Array.isArray(d) ? d : (d && d.places) || []
	}
})

export const startupPlan = createResource({
	key: 'startup-plan',
	needs: 'startup.plan',
	staleMs: 60000,
	load: async () => (await call('startup.plan', {}, { quiet: true })).data || { items: [], info: [] }
})

export const startupFiles = createResource({
	key: 'startup-files',
	needs: 'startup.files',
	staleMs: 60000,
	load: async () => (await call('startup.files', {}, { quiet: true })).data || { plugins: [] }
})

export const startupRuns = createPagedResource({
	key: 'startup-runs',
	needs: 'startup.runs.list',
	pageSize: 20,
	load: async ({ limit, offset }) => {
		const d = (await call('startup.runs.list', { limit, offset }, { quiet: true })).data || {}
		return { rows: d.rows || [], total: typeof d.total === 'number' ? d.total : (d.rows || []).length }
	}
})

export const apiOps = createResource({
	key: 'api-ops',
	needs: 'api.describe',
	staleMs: 300000,
	load: async () => (await call('api.describe', { lang: String(locale() || 'en').slice(0, 2) }, { quiet: true })).data || { ops: [] }
})
