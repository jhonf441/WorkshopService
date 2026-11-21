<template>
	<!-- Pick ONE real thing from a list the service has (a profile, a scene, a recipe...), with a search box: the readable name first and the technical id small and grey.
	     It is the ONE picker of the kit (ui/SvCombo.vue) drawn open under its box. Props: options [{ id, name }], value (the id picked, '' = none), label. Event: input (the id), as v-model.
	       <access-target-pick :options="[...]" v-model="id" :label="'Name'" /> -->
	<div class="access-target-pick" data-part="target-pick">
		<span class="sv-label">{{ label }}</span>
		<sv-combo inline :value="value" :options="items" :aria-label="label" :placeholder="$t('plugins.WorkshopService.access.target_pick_search')" :none-text="$t('plugins.WorkshopService.access.target_pick_none')" @input="v => $emit('input', v)" />
	</div>
</template>

<script>
'use strict'

import SvCombo from './ui/SvCombo.vue'

export default {
	components: { SvCombo },
	props: {
		options: { type: Array, default: () => [] },
		value: { type: String, default: '' },
		label: { type: String, default: '' }
	},
	computed: {
		items() {
			return this.options.map(o => ({ value: o.id, label: o.name, hint: o.id }))
		}
	}
}
</script>
