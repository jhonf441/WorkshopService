<template>
	<!-- THE confirmation dialog, levels 3 and 4 (FASE2, promoted from the service SvConfirmDialog), over WfSheet. It names WHAT is affected, lists the effects
	     and its confirm button repeats the verb ("Remove Lucia", never "Accept"). Level 4: the confirm button stays disabled until the box is ticked.
	     On opening the focus is on Cancel. Cancelling is not an error.
	       confirm  { level, check, title, text } of an action in state 'confirming' (workshop-action.js), or null = closed
	       title / text   the page's own, used when confirm brings none        object  { name, context }: what is affected, always given by the page
	       effects  [sentences]    verb  the label of the confirm button (required)    danger  the confirm button is red
	     Events: accept, cancel. -->
	<wf-sheet :open="!!confirm" :title="heading" :level="level" role="alertdialog" :describedby="textId" @close="$emit('cancel')">
		<div v-if="object && object.name" class="wf-dialog-object"><b>{{ object.name }}</b><span v-if="object.context">{{ object.context }}</span></div>
		<p :id="textId" class="wf-dialog-text">{{ body }}</p>
		<ul v-if="effects && effects.length" class="wf-effects"><li v-for="(e, i) in effects" :key="i">{{ e }}</li></ul>
		<button v-if="needsCheck" type="button" class="wf-check" role="checkbox" :aria-checked="ticked ? 'true' : 'false'" @click="ticked = !ticked"><span class="wf-check-box mdi" :class="ticked ? 'mdi-checkbox-marked-outline' : 'mdi-checkbox-blank-outline'" aria-hidden="true" /><span>{{ ts('wf_understand_risk') }}</span></button>
		<template #foot>
			<button type="button" class="wf-btn" data-wf-autofocus @click="$emit('cancel')">{{ ts('wf_cancel') }}</button>
			<button type="button" class="wf-btn wf-danger" :class="{ 'wf-fill': filled }" :disabled="needsCheck && !ticked" @click="accept">{{ verb }}</button>
		</template>
	</wf-sheet>
</template>

<script>
import WfSheet from './WfSheet.vue'
import { ts } from './shared-t.js'

let serial = 0

export default {
	name: 'WfConfirm',
	components: { WfSheet },
	props: {
		confirm: { type: Object, default: null },
		title: { type: String, default: '' },
		text: { type: String, default: '' },
		object: { type: Object, default: null },
		effects: { type: Array, default: () => [] },
		verb: { type: String, required: true },
		danger: { type: Boolean, default: false }
	},
	data() {
		serial += 1
		return { ticked: false, textId: 'wf-confirm-text-' + serial }
	},
	computed: {
		level() {
			return (this.confirm && this.confirm.level) || 3
		},
		filled() {
			return this.danger || this.level === 4
		},
		needsCheck() {
			return !!(this.confirm && (this.confirm.check || this.confirm.level >= 4))
		},
		heading() {
			return (this.confirm && this.confirm.title) || this.title
		},
		body() {
			return (this.confirm && this.confirm.text) || this.text
		}
	},
	watch: {
		confirm() {
			this.ticked = false
		}
	},
	methods: {
		ts,
		accept() {
			if (this.needsCheck && !this.ticked) return
			this.$emit('accept')
		}
	}
}
</script>
