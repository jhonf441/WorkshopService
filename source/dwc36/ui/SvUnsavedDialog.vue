<template>
	<!-- THE "You have unsaved changes" dialog of the whole page (mounted once by the shell): three answers with words, one under another and of one width (44 px): discard (red outline, the one that loses
	     something, first and far from the focus), save and leave, and keep editing (the main one, the focused one). The state is unsaved-guard.js. While an editor runs its own review (a before / after dialog) this one steps aside. -->
	<wf-sheet :open="open" :title="kt('unsaved_title')" :level="3" role="alertdialog" describedby="sv-unsaved-text" @close="keep">
		<p id="sv-unsaved-text">{{ kt('unsaved_text') }}</p>
		<p v-if="places.length" class="sv-unsaved-where"><strong>{{ kt('unsaved_where') }}</strong> {{ places.join(' · ') }}</p>
		<p v-if="state.error" class="sv-field-error" role="alert"><span class="mdi mdi-alert-outline sv-ico sv-ico-s" aria-hidden="true" />{{ kt('unsaved_failed') }}</p>
		<template #foot>
			<div class="sv-unsaved-actions">
				<button type="button" class="wf-btn sv-btn wf-danger" data-act="discard" :disabled="busy" @click="discard">{{ kt('unsaved_discard') }}</button>
				<button type="button" class="wf-btn sv-btn" data-act="save" :disabled="busy" @click="save">{{ kt('unsaved_save') }}</button>
				<button type="button" class="wf-btn sv-btn wf-main" data-wf-autofocus data-act="keep" @click="keep">{{ kt('unsaved_keep') }}</button>
			</div>
		</template>
	</wf-sheet>
</template>

<script>
import WfSheet from '../WfSheet.vue'
import { svTextMixin } from './sv-text.js'
import { dirtyEditors, discardAndLeave, keepEditing, saveAndLeave, unsaved } from './unsaved-guard.js'

export default {
	name: 'SvUnsavedDialog',
	components: { WfSheet },
	mixins: [svTextMixin],
	data() {
		return { state: unsaved, busy: false }
	},
	computed: {
		open() {
			return !!this.state.pending && !this.state.waiting
		},
		// WHERE the changes are (section / tab of each editor that holds some): an editor kept alive behind another section is named, not a mystery
		places() {
			return this.open ? dirtyEditors().map(e => e.name).filter(Boolean) : []
		}
	},
	methods: {
		keep() {
			if (!this.busy) keepEditing()
		},
		discard() {
			discardAndLeave()
		},
		async save() {
			this.busy = true
			try { await saveAndLeave() } finally { this.busy = false }
		}
	}
}
</script>
