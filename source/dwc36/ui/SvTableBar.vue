<template>
	<!-- THE bar of a table with an order or a filter (people, keys, profiles, activity, commands...): its controls on ONE row from the left, 8 px / 16 px apart,
	     all on the base of their boxes (a field has its label above, a button has none: both end on the same line), 44 px high. It wraps when narrow.
	     The controls are the children; nothing here knows what they do. Class .sv-tbar in styles/kit.css (also the one rule of the old .access-filters). -->
	<div class="sv-tbar" role="toolbar" :aria-label="label || null"><slot /></div>
</template>

<script>
export default { name: 'SvTableBar', props: { label: { type: String, default: '' } } }
</script>
