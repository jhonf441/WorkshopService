<template>
	<!-- A table with its title and its bar: 24 px above the block (16 to 24 between blocks), 12 px between the title, the bar and the table. The title is never
	     glued to what follows (tools/dev/layout_audit.js: titlegap). Slots: `bar` (a SvTableBar), the default (the table). -->
	<section class="sv-tblock">
		<h3 v-if="title" class="sv-tblock-title">{{ title }}</h3>
		<slot name="bar" />
		<slot />
	</section>
</template>

<script>
export default { name: 'SvTableBlock', props: { title: { type: String, default: '' } } }
</script>
