<template>
	<!-- A list to choose one value from, in the style of the buttons of the kit (the native select draws the browser's own box and menu, which do not match). A button that
	     says the chosen option + a listbox of options of 44 px, the chosen one marked. Keyboard: Up / Down / Home / End move, Enter or Space choose, Escape closes, Tab leaves.
	     Props: value, options [{ value, label }] (or `items` as Vuetify has them: strings or { text, value }), label (above the button), clearable (a first option "none" that gives ''), disabled, ariaLabel, id.
	     Event: input (the value), as v-model. -->
	<div class="sv-select" @focusout="onFocusOut">
		<label v-if="label" class="sv-label" :for="id || uid + '-b'">{{ label }}</label>
		<button :id="id || (label ? uid + '-b' : null)" type="button" class="wf-btn sv-btn sv-select-btn" aria-haspopup="listbox" :aria-expanded="open ? 'true' : 'false'" :aria-label="ariaLabel || null" :aria-controls="open ? uid : null" :aria-activedescendant="open ? uid + '-' + active : null" :disabled="disabled" @click="toggle" @keydown="onKey">
			<span class="sv-select-text">{{ currentLabel }}</span><span class="mdi mdi-menu-down sv-ico" aria-hidden="true" />
		</button>
		<ul v-if="open" :id="uid" class="sv-select-list" role="listbox" :aria-label="ariaLabel || null">
			<li v-for="(o, i) in list" :id="uid + '-' + i" :key="String(o.value)" role="option" :aria-selected="same(o.value) ? 'true' : 'false'" :data-active="i === active ? 'true' : null" @mousedown.prevent="choose(o)">
				<span>{{ o.label }}</span><span v-if="same(o.value)" class="mdi mdi-check sv-ico sv-ico-s" aria-hidden="true" />
			</li>
		</ul>
	</div>
</template>

<script>
let serial = 0

export default {
	name: 'SvSelect',
	model: { prop: 'value', event: 'input' },
	props: {
		value: { type: [String, Number, Boolean], default: '' },
		options: { type: Array, default: () => [] },
		items: { type: Array, default: () => [] },
		label: { type: String, default: '' },
		clearable: { type: Boolean, default: false },
		disabled: { type: Boolean, default: false },
		ariaLabel: { type: String, default: '' },
		id: { type: String, default: null }
	},
	data() {
		serial += 1
		return { open: false, active: 0, uid: 'sv-select-' + serial }
	},
	computed: {
		// the options as { value, label }: from `options`, or from `items` of Vuetify; with `clearable` a first "none" (the dash) that gives ''
		list() {
			const own = this.options.length ? this.options : this.items.map(i => (i !== null && typeof i === 'object' ? { value: i.value !== undefined ? i.value : i.text, label: String(i.text !== undefined ? i.text : i.label !== undefined ? i.label : i.value) } : { value: i, label: String(i) }))
			return this.clearable ? [{ value: '', label: '\u2014' }].concat(own) : own
		},
		currentLabel() {
			const o = this.list.find(x => this.same(x.value))
			return o && !(this.clearable && o.value === '') ? o.label : ''
		}
	},
	methods: {
		same(v) {
			return String(v) === String(this.value)
		},
		toggle() {
			if (this.open) this.open = false
			else this.show()
		},
		show() {
			if (this.disabled) return
			const i = this.list.findIndex(o => this.same(o.value))
			this.active = i < 0 ? 0 : i
			this.open = true
		},
		choose(o) {
			this.open = false
			if (!this.same(o.value)) this.$emit('input', o.value)
		},
		onKey(e) {
			const n = this.list.length
			const k = e.key
			if (k === 'Escape') { if (this.open) { this.open = false; e.stopPropagation(); e.preventDefault() } return }
			if (k === 'Tab') { this.open = false; return }
			if (['ArrowDown', 'ArrowUp', 'Home', 'End', 'Enter', ' '].indexOf(k) < 0) return
			e.preventDefault()
			if (!this.open) { if (k !== 'Home' && k !== 'End') this.show(); return }
			if (k === 'ArrowDown') this.active = (this.active + 1) % n
			else if (k === 'ArrowUp') this.active = (this.active - 1 + n) % n
			else if (k === 'Home') this.active = 0
			else if (k === 'End') this.active = n - 1
			else if (this.list[this.active]) this.choose(this.list[this.active])
		},
		onFocusOut(e) {
			if (!this.$el.contains(e.relatedTarget)) this.open = false
		}
	}
}
</script>
