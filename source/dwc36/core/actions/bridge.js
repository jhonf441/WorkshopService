'use strict'

// What a person does to the G-code bridge through the API of the service (everything else about the bridge goes through its order file,
// core/store/bridge.js).
//
//   unitSwitch.run({ on })   bridge.service.set   starts or stops the systemd unit of the bridge in this Pi; stopping cuts every connection, so it asks a
//                            second touch. Answers { ok, state }: a refusal (a live job is open, no permission) arrives with its reason.

import { createAction } from '../store/action.js'
import { bridge, readState, readUnit } from '../store/bridge.js'

export const unitSwitch = createAction({
	op: 'bridge.service.set', group: 'bridge', arm: args => (args && args.on ? 'none' : 'double'),
	after: data => {
		if (data && data.state) bridge.unit = data.state
		return [readUnit(), readState()]
	}
})
