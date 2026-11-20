'use strict'

// The operations of the service (api.describe: { op, desc }) for the editor of rules of Access, which lives in the legacy layer and must not reach into core/.
// The host of Access (sections/access/index.vue) puts them here when it has them; the editor reads them.

import Vue from 'vue'

export const opsSource = Vue.observable({ ops: [] })

export function setOps(list) {
	opsSource.ops = Array.isArray(list) ? list : []
}
