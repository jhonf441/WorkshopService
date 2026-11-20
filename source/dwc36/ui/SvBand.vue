<template>
	<!-- The band of the page: ONE, under the header, for what changes how everything else must be read (service stopped, damaged
	     file, open mode, reconnecting). The page chooses which one by priority; this only draws it.
	     Props: level ('error' | 'warn'), icon (an mdi class), title (the fact, in bold), text (what it implies), alert (true: role="alert").
	     Slot: default (a button, when there is a way out). Nothing is drawn without a title. -->
	<div v-if="title" class="sv-band" :data-level="level" :role="alert ? 'alert' : 'status'">
		<span class="mdi sv-ico" :class="icon" aria-hidden="true" />
		<span><b>{{ title }}</b> {{ text }}</span>
		<slot />
	</div>
</template>

<script>
export default {
	name: 'SvBand',
	props: {
		level: { type: String, default: 'warn' },
		icon: { type: String, default: 'mdi-alert-outline' },
		title: { type: String, default: '' },
		text: { type: String, default: '' },
		alert: { type: Boolean, default: false }
	}
}
</script>
