<template>
	<!-- The one dialog every change of access goes through: what it was (before), what it will be (after), what changes in practice, and the verb.
	     Placeholder of step 0: props and slots only; the screens fill the slots in the next steps. A failure of the service keeps it open (`error`).
	       <access-change-dialog v-model="open" :title="..." :confirm-label="..." :risk4="false" :busy="saving" :error="msg" @confirm="save">
	         <template #before>...</template> <template #after>...</template> <template #summary>...</template>
	       </access-change-dialog> -->
	<v-dialog :value="value" max-width="1100" width="100%" scrollable persistent content-class="access-change-dialog" @input="v => $emit('input', v)">
		<v-card role="dialog" aria-labelledby="access-change-title">
			<v-card-title id="access-change-title" class="text-subtitle-1">{{ title }}</v-card-title>
			<v-card-text>
				<div class="access-change-cols">
					<section class="access-change-col">
						<div class="text-caption">{{ $t('plugins.WorkshopService.access.diff_before') }}</div>
						<slot name="before" />
					</section>
					<section class="access-change-col">
						<div class="text-caption">{{ $t('plugins.WorkshopService.access.diff_after') }}</div>
						<slot name="after" />
					</section>
				</div>
				<div class="access-change-summary"><slot name="summary" /></div>
				<v-alert v-if="risk4" type="error" outlined dense class="mt-3">{{ $t('plugins.WorkshopService.access.diff_risk4_title') }}</v-alert>
				<v-checkbox v-model="understood" dense hide-details :label="$t('plugins.WorkshopService.access.common_understood')" />
				<div class="text-caption mt-1">{{ $t('plugins.WorkshopService.access.diff_audit_note') }}</div>
				<v-alert v-if="error" type="error" outlined dense class="mt-3">{{ error }}</v-alert>
			</v-card-text>
			<v-card-actions class="access-change-actions">
				<v-spacer />
				<v-btn small text :disabled="busy" @click="$emit('input', false)">{{ $t('plugins.WorkshopService.access.common_cancel') }}</v-btn>
				<v-btn small color="primary" :loading="busy" :disabled="!understood" @click="$emit('confirm')">{{ confirmLabel }}</v-btn>
			</v-card-actions>
		</v-card>
	</v-dialog>
</template>

<script>
'use strict'

export default {
	props: {
		value: { type: Boolean, default: false },
		title: { type: String, default: '' },
		confirmLabel: { type: String, default: '' },
		risk4: { type: Boolean, default: false },
		busy: { type: Boolean, default: false },
		error: { type: String, default: '' }
	},
	data() {
		return { understood: false }
	},
	watch: {
		value(open) {
			if (open) this.understood = false
		}
	}
}
</script>

<style>
.access-change-cols { display: flex; gap: 16px; }
.access-change-col { flex: 1 1 0; min-width: 0; }
@media (max-width: 900px) {
	.access-change-dialog { margin: 0; max-height: 100%; height: 100%; max-width: 100%; }
	.access-change-cols { flex-direction: column; }
	.access-change-actions { position: sticky; bottom: 0; }
}
</style>
