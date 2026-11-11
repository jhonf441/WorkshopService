'use strict'

// The states every screen of the access section can be in (DISENO-PANTALLAS section 5), one table for <access-state>. Pure data.
//   kind      the cause of the notice (notice-kind.js: one cause, one color)
//   variant   where it is drawn: 'cover' replaces the content, 'section' is a note on top of it
//   title     key of the heading (cover only), text: key of the sentence; both in the area `access` of the catalogs
//   controls  what the screen leaves usable: 'none' | 'retry' | 'create' | 'read' | 'view' | 'partial' | 'review'
// An empty state ('') draws nothing.

export const ACCESS_STATES = Object.freeze({
	loading: { kind: 'resolving', variant: 'section', text: 'state_loading', controls: 'none' },
	slow: { kind: 'down', variant: 'section', text: 'state_slow', controls: 'none' },
	empty: { kind: 'empty', variant: 'section', text: 'state_empty', controls: 'create' },
	error: { kind: 'error', variant: 'section', text: 'state_error', controls: 'retry', retry: true },
	no_permission: { kind: 'role', variant: 'cover', title: 'common_admin_only', text: 'state_no_permission', controls: 'none' },
	damaged: { kind: 'error', variant: 'section', title: 'state_damaged_title', text: 'state_damaged_text', controls: 'read' },
	read_only: { kind: 'role', variant: 'section', text: 'state_read_only', controls: 'view' },
	users_off: { kind: 'down', variant: 'section', title: 'disabled_title', text: 'disabled_text', controls: 'partial' },
	later: { kind: 'empty', variant: 'section', text: 'state_later', controls: 'none' },
	stale: { kind: 'down', variant: 'section', text: 'state_stale', controls: 'review' },
	chain_broken: { kind: 'error', variant: 'section', text: 'audit_chain_broken', controls: 'read' }
})

export const ACCESS_STATE_IDS = Object.freeze(Object.keys(ACCESS_STATES))

export function stateOf(id) {
	return Object.prototype.hasOwnProperty.call(ACCESS_STATES, id) ? ACCESS_STATES[id] : null
}
