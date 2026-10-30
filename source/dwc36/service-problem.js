'use strict'

// Why the page cannot count on the service of the workshop, as a code (ServiceNotice shows it in full, PageHeader as a health
// reason): 'no_sbc' (DSF without a Raspberry), 'missing' (plugin not installed), 'stopped' (installed, not running) or null.
// Without a connection to the machine nothing is said: DWC already shows it.

import { pluginOf } from './workshop-ids.js'

export function serviceProblemKind(store) {
	if (!store.getters.isConnected) return null
	const model = store.state.machine.model
	if (!model.sbc) return 'no_sbc'
	const pcc = pluginOf(model.plugins, 'service')
	if (!pcc) return 'missing'
	if (!(pcc.pid > 0)) return 'stopped'
	return null
}

// text keys (under `shared.`) of each problem: the title (short, health reason) and the text (full, the notice)
export const SERVICE_PROBLEM_KEYS = {
	no_sbc: { title: 'service_notice_no_sbc_title', text: 'service_notice_no_sbc_text' },
	missing: { title: 'service_notice_missing_title', text: 'service_notice_missing_text' },
	stopped: { title: 'service_notice_stopped_title', text: 'service_notice_stopped_text' }
}
