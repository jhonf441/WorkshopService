'use strict'

// What every card of a section shares: the question "may I?", the four-line help of a row and ONE lock sentence per card.

import { t, tc } from './dwc.js'
import { can, signIn } from './store/session.js'
import { pageState } from './page-state.js'
import { serviceRunning } from './live/published.js'

// the lock of a zone for the shared WfZone: its title names the needed role as a person reads it ("Administrator"), not by its id; WfZone has no second line, so the help sentence follows the text
export function zoneLock(lock) {
	if (!lock) return null
	const id = lock.neededRole
	return Object.assign({}, lock, { text: [lock.text, lock.help].filter(Boolean).join(' '), neededRole: ['viewer', 'operator', 'technician', 'admin'].indexOf(id) >= 0 ? t('api.role_' + id) : id || '' })
}

export const rowsMixin = {
	computed: {
		// the service is stopped or restarting: what is shown is old and nothing is written
		stale() {
			return !serviceRunning() || !!pageState.restarting
		}
	},
	methods: {
		t,
		tc,
		signIn,
		zoneLock,
		perm(op) {
			return can(op)
		},
		// the cause of the highest lock among the controls of a card: no session before a role that is too low; null when none
		lockOf(ops) {
			const all = ops.map(op => can(op))
			return all.find(c => c.state === 'session') || all.find(c => c.state === 'role') || null
		},
		// the four lines of the help of a row (keys <area>.help_<id>_what / why / missing / how; they feed <help-fold> as what / why / ifMissing / how)
		help(id, area) {
			const a = (area || 'machine') + '.help_' + id + '_'
			return { what: t(a + 'what'), why: t(a + 'why'), ifMissing: t(a + 'missing'), how: t(a + 'how') }
		},
		// keyboard focus holds an armed control; when it leaves, it is disarmed at once
		held(c, on) {
			c.hold(on)
			if (!on) c.cancel()
		}
	}
}
