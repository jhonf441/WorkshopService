'use strict'

// What the parts of the bridge screen share: the translator of the area bridgeCard, the two-touch rule of the orders that cut something, the way
// an order is sent to the bridge (through the order file) and the words of its answer.
//
//   tr(key, params, count)    a text of the area bridgeCard
//   touch(key)                true on the second touch within 4 s (the first one arms it); false otherwise
//   order(data, key)          writes the order and waits for the answer of the bridge
//   busy(key)                 the order with this key is on its way
//   outcome                   the last answer as { ok, text } or null (a refused one stays until the next order)

import { t, tc } from '../../core/dwc.js'
import { bridge, sendAction } from '../../core/store/bridge.js'
import { every, timeNow } from '../../core/clock.js'
import { ARM_MS } from '../../bridge-view.js'
import * as words from '../../bridge-texts.js'

export const tr = (key, params, count) => (count === undefined ? t('bridgeCard.' + key, params) : tc('bridgeCard.' + key, count, params))

export const bridgeOrders = {
	data() {
		return { bridge, armed: '' }
	},
	computed: {
		outcome() {
			const a = this.bridge.act
			if (a.state === 'done') return { ok: true, text: words.actionText(a.result, tr) || tr('done') }
			if (a.state === 'error') {
				if (a.result) return { ok: false, text: words.actionText(a.result, tr) }
				return { ok: false, text: a.text === 'no_answer' ? tr('the_bridge_did_not_respond_is') : tr('could_not_send_the_action_x', { x: String(a.text).replace(/^not_sent:/, '') }) }
			}
			return null
		}
	},
	beforeDestroy() {
		this.disarm()
	},
	methods: {
		tr,
		disarm() {
			this.armed = ''
			if (this.offArm) { this.offArm(); this.offArm = null }
		},
		touch(key) {
			if (this.armed === key) { this.disarm(); return true }
			this.disarm()
			this.armed = key
			const until = timeNow() + ARM_MS
			this.offArm = every(1, () => { if (timeNow() >= until) this.disarm() })
			return false
		},
		order(data, key) {
			return sendAction(data, key)
		},
		busy(key) {
			return this.bridge.act.state === 'sending' && this.bridge.act.key === key
		}
	}
}
