<template>
	<!-- Access > People: the accounts (add, PIN, role, modes, sessions: UsersCard) and, under them, what each person has in the access model (groups, profiles,
	     ceiling: AccessPeople). Nothing here is new: both blocks keep their own operations. `focus` asks AccessPeople to open a person or a group. -->
	<div class="access-people-tab">
		<users-card />
		<access-people :focus="focus" @damaged="v => $emit('damaged', v)" @see-can="n => $emit('see-can', n)" />
	</div>
</template>

<script>
'use strict'

import UsersCard from './UsersCard.vue'
import AccessPeople from './AccessPeople.vue'

export default {
	name: 'AccessPeopleTab',
	components: { UsersCard, AccessPeople },
	props: { focus: { type: Object, default: null } }
}
</script>
