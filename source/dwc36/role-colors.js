'use strict'

// ONE mapping role -> colour for every chip that names a role (the people table, "my session", the audit rows): RoleChip.vue draws it.
// Only the semantic colours of the design family (DISENO.md: primary / success / warning / error / info, never a palette name): family.css
// draws a v-chip with one of those colours as an outlined chip with a dot of that colour. A palette name such as "amber darken-3" escapes
// that rule and comes out as a solid chip (the "Técnico" badge of 2026-11-06), which is why the map lives here and nowhere else.
//   viewer      no colour (it only looks)
//   operator    primary (it works the machine)
//   technician  warning (it changes settings)
//   admin       error (it manages people, keys and the power)
// A role the map does not know (a custom role, or an older service) has no colour either.

export const ROLE_COLORS = { viewer: '', operator: 'primary', technician: 'warning', admin: 'error' }

export function roleColor(role) {
	return Object.prototype.hasOwnProperty.call(ROLE_COLORS, role) ? ROLE_COLORS[role] : ''
}
