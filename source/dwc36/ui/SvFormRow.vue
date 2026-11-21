<template>
	<!-- THE row of a form on a wide screen: the fields sit together on the left (320 px each, 16 px apart, never spread over the card), and the
	     action goes at the end of the group, at the height of the inputs (their base, not the middle of the block with the labels). One column under
	     560 px, everything at full width. The fields are the children (a field with its label above); the action goes in the `act` slot.
	     Nothing here knows what the fields are: no store, no text. Classes: .sv-form-row / .sv-form-act in styles/kit.css. -->
	<div class="sv-form-row">
		<slot />
		<div v-if="$slots.act" class="sv-form-act"><slot name="act" /></div>
	</div>
</template>

<script>
export default { name: 'SvFormRow' }
</script>
