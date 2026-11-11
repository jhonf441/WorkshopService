<template>
	<!-- The fixed notice of the access section when users are turned off (DISENO-PANTALLAS 2.1): everybody is an administrator today. It cannot be closed;
	     the button only goes to the Users section, it turns nothing on by itself. -->
	<div class="access-users-notice wf-note is-warn" role="note">
		<v-icon class="wf-note-icon" aria-hidden="true">mdi-alert-outline</v-icon>
		<div class="access-users-notice-body">
			<strong>{{ $t('plugins.WorkshopService.access.disabled_title') }}</strong>
			<div>{{ $t('plugins.WorkshopService.access.disabled_text') }}</div>
		</div>
		<v-btn small outlined color="warning" class="access-touch" @click="$emit('go-users')">{{ $t('plugins.WorkshopService.access.disabled_go') }}</v-btn>
	</div>
</template>

<script>
'use strict'

export default {}
</script>
