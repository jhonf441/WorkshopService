<template>
	<div v-if="v.allowed" class="ml-10 mt-2 svc-relay">
		<div class="font-weight-medium text-body-2" :style="{ color: v.color }">{{ v.text }}</div>
		<div class="d-flex flex-wrap mt-1" style="gap:6px">
			<v-btn size="small" :color="v.armed ? 'warning' : 'error'" :disabled="!v.can.stop" @click="stopTap">
				{{ v.armed ? $t('plugins.WorkshopService.api.relay_stop_confirm') : $t('plugins.WorkshopService.api.relay_stop') }}
			</v-btn>
			<v-btn size="small" color="primary" :disabled="!v.can.start" @click="startTap">{{ $t('plugins.WorkshopService.api.relay_start') }}</v-btn>
		</div>
		<div v-if="v.msg" class="text-body-small mt-1 svc-relay-msg">{{ v.msg }}</div>
		<div class="text-body-small text-medium-emphasis mt-1">{{ $t('plugins.WorkshopService.api.relay_help') }}</div>
	</div>
</template>

<script setup>
import { ref, onMounted, onBeforeUnmount } from 'vue'
import { view, subscribe, watch, stopTap, startTap } from './camera-relay.js'

// The control of the camera relay (stop / start), inside the row of the process "camera_relay". Technician and admin only: for the rest the
// card is not drawn. The state is read while the row is on screen (camera-relay.js keeps one model for the page and for the bar tile).
const v = ref(view())
let off = null

onMounted(() => {
	off = subscribe(() => { v.value = view() })
	watch(true)
})
onBeforeUnmount(() => {
	if (off) off()
	watch(false)
})
</script>

<style scoped>
.svc-relay-msg {
	color: var(--tp-amber, #ffe082);
}
</style>
