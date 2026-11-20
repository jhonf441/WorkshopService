<template>
	<!-- THE confirmation dialog, for levels 3 and 4, whether the text comes from the service (428) or from the page.
	     Props: confirm ({ level, check, title, text } of an action in state 'confirming', or null = closed), title / text (the page's own,
	     used when confirm brings none), object ({ name, context }: WHAT is affected, always given by the page), effects ([sentences]),
	     verb (the label of the confirm button: it repeats the verb, "Remove Lucia", never "Accept"), danger (the confirm button is filled).
	     Events: accept, cancel. Cancelling is not an error. Level 4: the confirm button stays disabled until the box is ticked.
	     On opening the focus is on Cancel. -->
	<sv-sheet :open="!!confirm" :title="heading" :level="level" role="alertdialog" :describedby="textId" @close="$emit('cancel')">
		<div v-if="object && object.name" class="sv-dialog-object"><b>{{ object.name }}</b><span v-if="object.context">{{ object.context }}</span></div>
		<p :id="textId">{{ body }}</p>
		<ul v-if="effects && effects.length" class="sv-effects"><li v-for="(e, i) in effects" :key="i">{{ e }}</li></ul>
		<label v-if="needsCheck" class="sv-check"><input v-model="ticked" type="checkbox"><span>{{ kt('understand_risk') }}</span></label>
		<template #foot>
			<button type="button" class="sv-btn" data-sv-autofocus @click="$emit('cancel')">{{ kt('cancel') }}</button>
			<button type="button" class="sv-btn sv-danger" :class="{ 'sv-fill': filled }" :disabled="needsCheck && !ticked" @click="accept">{{ verb }}</button>
		</template>
	</sv-sheet>
</template>

<script>
import SvSheet from './SvSheet.vue'
import { svTextMixin } from './sv-text.js'

let serial = 0

export default {
	name: 'SvConfirmDialog',
	components: { SvSheet },
	mixins: [svTextMixin],
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
		return { ticked: false, textId: 'sv-confirm-text-' + serial }
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
		accept() {
			if (this.needsCheck && !this.ticked) return
			this.$emit('accept')
		}
	}
}
</script>
