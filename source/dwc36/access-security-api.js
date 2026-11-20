'use strict'

// The two reads of the Security section (administrator only; DISENO-PANTALLAS section 8, step 6). Both take no argument, change nothing and write nothing to the
// activity record. The answer is the service's and is not cached here (the screens ask again on "Review now" and "Refresh").
//
//   securityApi.review()    access.review: { generated, damaged, findings, counts, high, limits }  (see access-review-view.js)
//   securityApi.report()    access.report: { generated, damaged, locked, people, keys }            (see access-report-view.js)
//
// SECURITY_OPS lists the operations once: a test checks each one against dsf/golden/api_contract.json.

import { api } from './workshop-api.js'

export const SECURITY_OPS = Object.freeze({
	review: 'access.review',
	report: 'access.report'
})

export function makeSecurityApi(call) {
	return {
		review: () => call(SECURITY_OPS.review),
		report: () => call(SECURITY_OPS.report)
	}
}

export const securityApi = makeSecurityApi(api)
