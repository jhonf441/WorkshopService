<template>
	<!-- The chip of a role, the same everywhere (people table, my session, audit): outlined, with the dot of the role's colour (role-colors.js).
	     <role-chip role="technician" :text="roleName('technician')" />           x-small (tables)
	     <role-chip :role="me.role" :text="roleName(me.role)" size="small" />    small (next to a name) -->
	<v-chip :small="size === 'small'" :x-small="size !== 'small'" label outlined :color="color">{{ text }}</v-chip>
</template>

<script>
'use strict'

import { roleColor } from './role-colors.js'

export default {
	name: 'RoleChip',
	props: {
		role: { type: String, default: '' },
		text: { type: String, default: '' },
		size: { type: String, default: 'x-small' }
	},
	computed: {
		color() {
			return roleColor(this.role)
		}
	}
}
</script>
