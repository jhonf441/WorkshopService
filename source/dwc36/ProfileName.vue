<template>
	<!-- The name of a profile for a person: the readable name of a base or plugin profile with its real id as quiet code beside it; an own profile is its
	     own name. Display only: the id is what the service knows.
	       <profile-name id="base.operator" /> -->
	<span class="access-profile-name">{{ profileText(id) }}<code v-if="profileCode(id)" class="access-id">{{ id }}</code></span>
</template>

<script>
'use strict'

import { displayNamesMixin } from './display-names-mixin.js'

export default {
	mixins: [displayNamesMixin],
	props: { id: { type: String, default: '' } }
}
</script>

<style>
.access-id { margin-left: 6px; padding: 0 4px; font-size: 12px; opacity: 0.65; background: transparent; box-shadow: none; }
</style>
